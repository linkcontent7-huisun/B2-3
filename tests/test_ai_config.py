"""AI 클라이언트의 응답 해석과 설정 로딩.

실제 네트워크는 부르지 않는다. `requests.post` 를 가짜로 바꿔 끼워
"이런 응답이 오면 이렇게 해석한다" 만 확인한다.

아래 상당수는 **코드 리뷰(2026-08-21)에서 찾은 결함의 회귀 테스트**다.
A2-1·A2-2·A2-3 과 같은 AI 클라이언트 구조를 쓰다 보니 결함도 함께 왔다.
"""

from __future__ import annotations

import os

import pytest
from conftest import FakeResponse

from social_content import ai as ai_module
from social_content import config as config_module
from social_content.ai import AiCallError, AiKeyMissingError, GeminiClient, _parse_json_text
from social_content.config import ConfigError, load_config


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """재시도 대기 때문에 테스트가 느려지지 않게 한다."""
    monkeypatch.setattr(ai_module.time, "sleep", lambda _s: None)


def _post_sequence(monkeypatch, responses):
    calls = []
    queue = list(responses)

    def fake_post(url, **_kwargs):
        calls.append(url)
        return queue.pop(0) if queue else FakeResponse(500, text="응답 소진")

    monkeypatch.setattr(ai_module.requests, "post", fake_post)
    return calls


def _gemini_ok(text='{"ok": 1}'):
    return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": text}]}}]})


# ---------------------------------------------------------------------------
# 응답 파싱
# ---------------------------------------------------------------------------


def test_코드펜스가_붙어_와도_JSON_을_읽는다():
    """JSON 모드를 켜도 ```json 을 붙여 오는 모델이 있다."""
    assert _parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}


def test_빈_응답은_실패로_본다():
    with pytest.raises(AiCallError, match="비어 있"):
        _parse_json_text("   ")


def test_JSON_이_아니면_실패로_본다():
    with pytest.raises(AiCallError, match="JSON"):
        _parse_json_text("죄송합니다, 답변드릴 수 없습니다")


def test_키가_없으면_발급_주소까지_알려_준다():
    with pytest.raises(AiKeyMissingError, match="aistudio"):
        GeminiClient("")


# ---------------------------------------------------------------------------
# 모델 폴백 — 회귀
# ---------------------------------------------------------------------------


def test_빈_응답이_와도_다음_모델을_시도한다(monkeypatch):
    """안전 필터에 걸려 candidates 가 비어 오는 경우."""
    calls = _post_sequence(monkeypatch, [FakeResponse(200, {"candidates": []}), _gemini_ok()])
    assert GeminiClient("key").complete_json("p", {}) == {"ok": 1}
    assert len(calls) == 2


def test_이백인데_JSON_이_아니면_다음_모델을_시도한다(monkeypatch):
    """프록시가 200 에 HTML 오류 페이지를 실어 보내는 경우.

    고치기 전에는 _post 의 response.json() 이 else 절이라 JSONDecodeError 가
    AiCallError 로 감싸이지 않았고, 그대로 빠져나가 모델 폴백이 건너뛰어졌다.
    """
    calls = _post_sequence(
        monkeypatch, [FakeResponse(200, None, text="<html>502</html>"), _gemini_ok()]
    )
    assert GeminiClient("key").complete_json("p", {}) == {"ok": 1}
    assert len(calls) == 2


def test_JSON_이_깨져_와도_다음_모델을_시도한다(monkeypatch):
    """빈 응답은 이미 continue 로 넘기면서, 정작 깨진 JSON 만 루프를 끝내고 있었다."""
    calls = _post_sequence(monkeypatch, [_gemini_ok("죄송합니다"), _gemini_ok()])
    assert GeminiClient("key").complete_json("p", {}) == {"ok": 1}
    assert len(calls) == 2


def test_choices_가_비면_AiCallError_로_알린다(monkeypatch):
    """콘텐츠 필터에 걸리면 200 과 함께 choices 가 빈 배열로 온다.

    고치기 전에는 그대로 인덱싱해 IndexError 가 났고 폴백도 못 했다.
    """
    calls = _post_sequence(
        monkeypatch,
        [
            FakeResponse(200, {"choices": []}),
            FakeResponse(200, {"choices": [{"message": {"content": '{"ok": 1}'}}]}),
        ],
    )
    assert ai_module.OpenAiClient("key").complete_json("p", {}) == {"ok": 1}
    assert len(calls) == 2


def test_인증_실패는_재시도하지_않는다(monkeypatch):
    """401 은 다시 불러도 결과가 같다. 재시도는 낭비다."""
    calls = _post_sequence(monkeypatch, [FakeResponse(401, {"error": {"message": "bad key"}})] * 6)
    with pytest.raises(AiCallError, match="401"):
        GeminiClient("key").complete_json("p", {})
    assert len(calls) == len(ai_module.GEMINI_MODELS), "모델당 한 번씩만"


# ---------------------------------------------------------------------------
# 설정 — 회귀
# ---------------------------------------------------------------------------


def test_빈_환경변수는_dotenv_값을_가리지_않는다(monkeypatch, tmp_path):
    """셸이나 CI 에 `GEMINI_API_KEY=` 가 남아 있는 상황.

    고치기 전에는 setdefault 가 빈 문자열도 "이미 있음"으로 보아
    .env 에 넣어 둔 진짜 키가 무시됐다.
    """
    (tmp_path / ".env").write_text("GEMINI_API_KEY=real-key\n", encoding="utf-8")
    monkeypatch.setattr("social_content.config.ROOT", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    config_module.load_dotenv()
    assert os.environ["GEMINI_API_KEY"] == "real-key"


def test_이미_있는_환경변수는_dotenv_가_덮지_않는다(monkeypatch, tmp_path):
    """위 수정이 원래 규칙(셸 값 우선)을 깨지 않았는지 확인한다."""
    (tmp_path / ".env").write_text("GEMINI_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setattr("social_content.config.ROOT", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "from-shell")
    config_module.load_dotenv()
    assert os.environ["GEMINI_API_KEY"] == "from-shell"


def _write_config(tmp_path, **ai_overrides):
    import json

    data = {
        "brand": "테스트 브랜드 설명",
        "tones": ["friendly"],
        "ai": {"provider": "gemini", "api_key_env": "GEMINI_API_KEY", **ai_overrides},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("bad", [0, -30])
def test_타임아웃이_1_미만이면_거부한다(tmp_path, bad):
    """tones·provider 는 검사하는데 timeout 만 빠져 있었다.

    0 을 넘기면 requests 가 ValueError 를 던지는데 재시도 처리에 걸리지 않는다.
    """
    with pytest.raises(ConfigError, match="1 이상"):
        load_config(_write_config(tmp_path, timeout_sec=bad))


def test_숫자_자리에_글자가_오면_설정오류로_알린다(tmp_path):
    """`int("120초")` 는 ValueError 를 던지는데 main 은 ConfigError 만 잡는다."""
    with pytest.raises(ConfigError, match="숫자여야"):
        load_config(_write_config(tmp_path, timeout_sec="120초"))


def test_브랜드_설명이_비면_거부한다(tmp_path):
    """브랜드는 프롬프트의 문맥이다. 없으면 브랜드 톤이 나오지 않는다."""
    import json

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"brand": "  ", "tones": ["friendly"]}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
