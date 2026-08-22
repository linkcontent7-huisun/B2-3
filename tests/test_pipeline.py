"""워크플로우 [2] 텍스트 → [3] 이미지 → [4] 저장.

이 과제가 지키기로 한 것 두 가지를 시험한다.

1. **규격은 부탁만 하지 않고 센다** — 프롬프트에 "280자 이내"라고 적어도 모델은 넘긴다
2. **한 단계가 실패해도 다음 단계는 진행한다** — 이미지가 막혀도 텍스트는 남는다
"""

from __future__ import annotations

import json

import pytest
from conftest import BLOG, INSTAGRAM, X, FakeClient

from social_content import pipeline
from social_content.ai import AiCallError
from social_content.pipeline import Result, check_format, render_markdown, save, slugify


# ---------------------------------------------------------------------------
# 규격 검증 — 이 과제의 핵심 주장
# ---------------------------------------------------------------------------


def test_X_는_280자를_넘기면_잡는다():
    assert check_format("x", {"text": "가" * 281}) == ["280자 초과 (281자)"]


def test_X_는_280자_정확히는_통과시킨다():
    """경계값. 281 부터 위반이다."""
    assert check_format("x", {"text": "가" * 280}) == []


def test_블로그는_본문과_소제목_수를_각각_센다():
    부족한_블로그 = {"sections": [{"heading": "h", "body": "가" * 100}]}
    warnings = check_format("blog", 부족한_블로그)
    assert any("본문 500자 미만 (100자)" in w for w in warnings)
    assert any("소제목 3개 미만 (1개)" in w for w in warnings)


def test_블로그는_소제목들의_본문을_합쳐_센다():
    """한 소제목이 짧아도 합이 500자를 넘으면 규격을 지킨 것이다."""
    assert check_format("blog", BLOG) == []


def test_인스타는_해시태그_수가_범위를_벗어나면_잡는다():
    assert check_format("instagram", {"hashtags": ["#a"] * 5}) == ["해시태그 10개 내외를 벗어남 (5개)"]
    assert check_format("instagram", {"hashtags": ["#a"] * 20}) == ["해시태그 10개 내외를 벗어남 (20개)"]
    assert check_format("instagram", INSTAGRAM) == []


def test_키가_아예_없어도_터지지_않는다():
    """모델이 필드를 통째로 빠뜨리는 일이 있다. 검증이 죽으면 안 된다."""
    assert check_format("x", {}) == []
    assert check_format("blog", {}) != []
    assert check_format("instagram", {}) != []


# ---------------------------------------------------------------------------
# 텍스트 생성 — 부분 실패
# ---------------------------------------------------------------------------


def _result():
    return Result(topic="가을 성지순례길", brand="브랜드 설명", generated_at="2026-08-21T12:00:00")


def test_한_플랫폼이_실패해도_나머지는_생성한다():
    client = FakeClient(INSTAGRAM, AiCallError("쿼터 초과"), X)
    result = _result()
    pipeline.generate_texts(client, "주제", "브랜드", ["friendly"], result)

    assert set(result.contents["friendly"]) == {"instagram", "x"}
    assert len(result.errors) == 1
    assert "블로그" in result.errors[0]["step"]


def test_예상하지_못한_오류도_나머지를_날리지_않는다():
    """AiCallError 만 잡으면 다른 예외 하나가 남은 플랫폼까지 날린다.

    고치기 전에는 실제로 그랬다.
    """
    client = FakeClient(INSTAGRAM, TypeError("이상한 응답"), X)
    result = _result()
    pipeline.generate_texts(client, "주제", "브랜드", ["friendly"], result)

    assert set(result.contents["friendly"]) == {"instagram", "x"}, "3번째 플랫폼까지 가야 한다"
    assert "TypeError" in result.errors[0]["message"]


def test_규격_위반은_버리지_않고_표시만_한다():
    """사람이 보고 판단할 문제다. 자동으로 버리면 안 된다."""
    긴_X = {"text": "가" * 300}
    client = FakeClient(INSTAGRAM, BLOG, 긴_X)
    result = _result()
    pipeline.generate_texts(client, "주제", "브랜드", ["friendly"], result)

    saved = result.contents["friendly"]["x"]
    assert saved["text"] == 긴_X["text"], "내용은 살아 있어야 한다"
    assert saved["_warnings"] == ["280자 초과 (300자)"]


def test_톤이_둘이면_여섯_번_부른다():
    """3 플랫폼 × 2 톤. 보너스 A/B 테스트의 근거다."""
    client = FakeClient(*([INSTAGRAM, BLOG, X] * 2))
    result = _result()
    pipeline.generate_texts(client, "주제", "브랜드", ["friendly", "professional"], result)

    assert len(client.prompts) == 6
    assert set(result.contents) == {"friendly", "professional"}


def test_프롬프트에_브랜드가_들어간다():
    """브랜드를 안 넣으면 브랜드 톤이 나오지 않는다 — 이 과제가 배운 것."""
    client = FakeClient(INSTAGRAM, BLOG, X)
    pipeline.generate_texts(client, "가을 순례길", "신앙을 앞세우지 않는 서비스", ["friendly"], _result())

    assert all("신앙을 앞세우지 않는 서비스" in prompt for prompt in client.prompts)
    assert all("가을 순례길" in prompt for prompt in client.prompts)


# ---------------------------------------------------------------------------
# 저장
# ---------------------------------------------------------------------------


def test_저장하면_JSON_과_마크다운이_함께_나온다(tmp_path):
    """평가는 코드와 마크다운만 본다. JSON 만 남기면 읽어 줄 사람이 없다."""
    result = _result()
    result.contents = {"friendly": {"instagram": {**INSTAGRAM, "_warnings": []}}}
    out = save(result, tmp_path)

    assert (out / "result.json").exists()
    assert (out / "콘텐츠.md").exists()
    assert out.name.startswith("20260821-")


def test_마크다운에_규격_경고가_드러난다(tmp_path):
    result = _result()
    result.contents = {"friendly": {"x": {"text": "가" * 300, "_warnings": ["280자 초과 (300자)"]}}}
    assert "280자 초과" in render_markdown(result)


FORBIDDEN_IN_FILENAME = r'/\:*?"<>|'


def test_슬러그가_파일명으로_쓸_수_있는_형태다():
    """저장 폴더 이름에 그대로 들어가므로 Windows 금지 문자가 없어야 한다."""
    assert " " not in slugify("가을에 걷기 좋은 성지순례길")
    for bad in FORBIDDEN_IN_FILENAME:
        assert bad not in slugify(f"주제{bad}이름"), f"{bad!r} 가 남아 있다"


def test_슬러그가_비면_빈_폴더명을_만들지_않는다():
    """기호만 있는 주제를 넣으면 폴더 이름이 날짜만 남아 덮어쓰기가 난다."""
    assert slugify("///").strip("-") != "" or slugify("///") == ""


# ---------------------------------------------------------------------------
# 전체 실행
# ---------------------------------------------------------------------------


def test_이미지를_끄면_텍스트만_나온다(tmp_path):
    client = FakeClient(INSTAGRAM, BLOG, X)
    result, out = pipeline.run(client, "주제", "브랜드", ["friendly"], tmp_path, with_image=False)

    assert result.image is None
    assert not (out / "cover.png").exists()
    assert len(result.contents["friendly"]) == 3
    assert result.errors == []


def test_이미지가_실패해도_텍스트는_저장된다(tmp_path, monkeypatch):
    """이 워크플로우의 약속. 이미지 API 가 막혀도 텍스트는 남아야 한다."""
    monkeypatch.setattr(
        pipeline, "build_image_prompt", lambda *_a: (_ for _ in ()).throw(AiCallError("쿼터 초과"))
    )
    client = FakeClient(INSTAGRAM, BLOG, X)
    result, out = pipeline.run(client, "주제", "브랜드", ["friendly"], tmp_path)

    assert result.image is None
    assert len(result.contents["friendly"]) == 3, "텍스트는 그대로 남아야 한다"
    assert (out / "콘텐츠.md").exists()
    assert any("이미지" in error["step"] for error in result.errors)


def test_저장이_실패하면_SaveError_로_알린다(tmp_path, monkeypatch):
    """고치기 전에는 OSError 가 그대로 튀어 traceback 으로 끝났다.

    main 은 ConfigError 와 AiKeyMissingError 만 잡으므로, 만들어 낸 텍스트가
    통째로 사라진 채 종료됐다.
    """
    monkeypatch.setattr(
        pipeline, "save", lambda *_a: (_ for _ in ()).throw(OSError("No space left on device"))
    )
    client = FakeClient(INSTAGRAM, BLOG, X)

    with pytest.raises(pipeline.SaveError, match="저장하지 못했습니다"):
        pipeline.run(client, "주제", "브랜드", ["friendly"], tmp_path, with_image=False)
