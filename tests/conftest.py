"""테스트 공용 준비물.

실제 API 는 부르지 않는다. 키가 없는 사람도, CI 도 그대로 돌려야 하고,
호출할 때마다 결과가 달라지면 테스트가 무엇을 보장하는지 알 수 없다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FakeClient:
    """지정한 응답을 순서대로 돌려주는 가짜 LLM.

    예외 객체를 넣어 두면 그 자리에서 던진다 — 실패 경로를 시험할 때 쓴다.
    """

    name = "fake"
    last_model = "fake-model"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete_json(self, prompt: str, schema: dict) -> dict:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("FakeClient 에 준비된 응답이 없습니다")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeResponse:
    def __init__(self, status_code, payload=None, text="", content=b""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


INSTAGRAM = {"caption": "가" * 140, "hashtags": [f"#태그{i}" for i in range(10)]}
BLOG = {
    "title": "가을에 걷기 좋은 성지순례길",
    "sections": [
        {"heading": f"소제목 {i}", "body": "나" * 200} for i in range(1, 4)
    ],
}
X = {"text": "다" * 200}

PLATFORM_RESPONSES = {"instagram": INSTAGRAM, "blog": BLOG, "x": X}


@pytest.fixture
def one_tone_responses():
    """톤 하나 × 플랫폼 셋 = 세 번 호출되는 순서대로."""
    from social_content import platforms

    return [PLATFORM_RESPONSES[p.key] for p in platforms.PLATFORMS]
