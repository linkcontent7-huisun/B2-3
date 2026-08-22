"""AI API 클라이언트.

A2-1 에서 쓴 구조를 그대로 가져왔다. 무료 티어에서는 모델이 조용히 폐기되거나
쿼터가 차므로, 모델 목록을 앞에서부터 시도하고 먼저 되는 것을 쓴다.
"""

from __future__ import annotations

import json
import logging
import time

import requests

logger = logging.getLogger(__name__)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
OPENAI_BASE = "https://api.openai.com/v1"

# 앞에서부터 시도해 먼저 되는 것을 쓴다. 무료 티어에서는 모델이 조용히 폐기되거나
# (404) 분당 쿼터가 차거나(429) 혼잡해서(503) 실패한다.
#
# `gemini-2.5-flash` 는 실제로 "no longer available to new users" 404 가 떨어졌다.
# 버전이 박힌 이름은 이렇게 죽으므로, 별칭(`-latest`)을 앞에 두고
# 마지막 자리에만 구체적인 이름을 남겨 둔다.
GEMINI_MODELS = ("gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.5-flash-lite")
OPENAI_MODELS = ("gpt-4o-mini", "gpt-4o")

RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 2
RETRY_BACKOFF_SEC = 2.0


class AiKeyMissingError(Exception):
    """API 키가 없을 때."""


class AiCallError(Exception):
    """호출이 최종적으로 실패했을 때."""


def _describe_http_error(response: requests.Response) -> str:
    """상태 코드만 보여 주면 매번 원인을 다시 찾아봐야 한다. 대응 방법까지 붙인다."""
    try:
        detail = response.json().get("error", {})
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
    except ValueError:
        message = response.text[:200]
    message = (message or "").strip().replace("\n", " ")[:160]
    hints = {
        400: "요청 형식이 잘못되었습니다",
        401: "API 키가 유효하지 않습니다",
        403: "이 키로는 해당 모델을 쓸 수 없습니다",
        404: "모델이 없거나 더 이상 제공되지 않습니다",
        429: "무료 사용량(쿼터)을 모두 썼습니다",
        503: "모델이 일시적으로 혼잡합니다",
    }
    return f"HTTP {response.status_code} — {hints.get(response.status_code, '호출 실패')}. {message}"


def _post(url: str, *, headers: dict, payload: dict, timeout: int) -> dict:
    last_error = ""
    for attempt in range(RETRY_ATTEMPTS + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        except requests.Timeout:
            last_error = f"응답 시간 초과({timeout}초)"
        except requests.RequestException as exc:
            last_error = f"네트워크 오류: {exc}"
        else:
            if response.status_code == 200:
                # 200 인데 본문이 JSON 이 아닌 경우가 있다(프록시가 HTML 오류 페이지를
                # 200 으로 실어 보낼 때). 그대로 두면 AiCallError 가 아닌 예외라
                # 호출부의 모델 폴백이 건너뛰어진다.
                try:
                    return response.json()
                except ValueError:
                    raise AiCallError(
                        f"HTTP 200 인데 응답이 JSON 이 아닙니다: {response.text[:120]!r}"
                    ) from None
            last_error = _describe_http_error(response)
            if response.status_code not in RETRY_STATUSES:
                raise AiCallError(last_error)
        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_SEC * (attempt + 1))
    raise AiCallError(last_error)


def _parse_json_text(text: str) -> dict:
    """JSON 모드를 켜도 코드펜스를 붙여 오는 모델이 있어 한 겹 벗겨 낸다."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    text = text.strip()
    if not text:
        raise AiCallError("응답이 비어 있습니다")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AiCallError(f"응답을 JSON 으로 읽지 못했습니다: {exc.msg}") from None
    if not isinstance(parsed, dict):
        raise AiCallError("응답 최상위가 JSON 객체가 아닙니다")
    return parsed


class GeminiClient:
    name = "gemini"

    def __init__(self, api_key: str, timeout_sec: int = 120) -> None:
        if not api_key:
            raise AiKeyMissingError(
                "GEMINI_API_KEY 가 없습니다. .env 에 키를 넣어 주세요.\n"
                "     발급: https://aistudio.google.com/apikey"
            )
        self._key = api_key
        self._timeout = timeout_sec
        self.last_model = ""

    def complete_json(self, prompt: str, schema: dict) -> dict:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                # 요약과 분석은 사실을 옮기는 일이라 창의성이 필요 없다.
                "temperature": 0.3,
            },
        }
        headers = {"x-goog-api-key": self._key, "Content-Type": "application/json"}
        errors = []
        for model in GEMINI_MODELS:
            try:
                data = _post(
                    f"{GEMINI_BASE}/{model}:generateContent",
                    headers=headers,
                    payload=payload,
                    timeout=self._timeout,
                )
            except AiCallError as exc:
                errors.append(f"{model}: {exc}")
                logger.warning("모델 %s 실패, 다음 모델로 넘어갑니다 — %s", model, exc)
                continue
            self.last_model = model
            candidates = data.get("candidates") or []
            if not candidates:
                blocked = (data.get("promptFeedback") or {}).get("blockReason")
                errors.append(f"{model}: 응답 없음 (차단 사유: {blocked})")
                continue
            parts = (candidates[0].get("content") or {}).get("parts") or []
            texts = [part["text"] for part in parts if "text" in part]
            if not texts:
                errors.append(f"{model}: 응답에 텍스트가 없습니다")
                continue
            # 파싱 실패도 다음 모델로 넘긴다. 빈 응답은 위에서 continue 로 넘기면서
            # 정작 "JSON 이 깨져 온" 경우만 여기서 루프를 끝내면 앞뒤가 안 맞는다.
            try:
                return _parse_json_text("".join(texts))
            except AiCallError as exc:
                errors.append(f"{model}: {exc}")
                continue
        raise AiCallError(" / ".join(errors) or "호출 가능한 모델이 없습니다.")


def _openai_text(data: dict) -> str:
    """OpenAI 응답에서 본문을 꺼낸다.

    콘텐츠 필터에 걸리면 200 과 함께 choices 가 빈 배열로 온다. 그대로 인덱싱하면
    IndexError 가 나는데, AiCallError 가 아니라서 다음 모델로 넘어가지 못한다.
    """
    choices = data.get("choices") or []
    if not choices:
        raise AiCallError("응답에 choices 가 없습니다 (콘텐츠 필터에 걸렸을 수 있습니다)")
    content = (choices[0].get("message") or {}).get("content")
    if not content:
        finish = choices[0].get("finish_reason")
        raise AiCallError(
            f"응답에 텍스트가 없습니다 (종료 사유: {finish})" if finish else "응답에 텍스트가 없습니다"
        )
    return content


class OpenAiClient:
    name = "openai"

    def __init__(self, api_key: str, timeout_sec: int = 120) -> None:
        if not api_key:
            raise AiKeyMissingError(
                "OPENAI_API_KEY 가 없습니다. .env 에 키를 넣어 주세요.\n"
                "     발급: https://platform.openai.com/api-keys"
            )
        self._key = api_key
        self._timeout = timeout_sec
        self.last_model = ""

    def complete_json(self, prompt: str, schema: dict) -> dict:
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        errors = []
        for model in OPENAI_MODELS:
            try:
                data = _post(
                    f"{OPENAI_BASE}/chat/completions",
                    headers=headers,
                    payload={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.3,
                    },
                    timeout=self._timeout,
                )
                self.last_model = model
                return _parse_json_text(_openai_text(data))
            except AiCallError as exc:
                errors.append(f"{model}: {exc}")
                continue
        raise AiCallError(" / ".join(errors) or "호출 가능한 모델이 없습니다.")


def build_client(provider: str, api_key: str | None, timeout_sec: int = 120):
    """설정에 맞는 AI 클라이언트를 만든다."""
    if provider == "openai":
        return OpenAiClient(api_key or "", timeout_sec)
    return GeminiClient(api_key or "", timeout_sec)
