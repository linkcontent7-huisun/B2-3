"""플랫폼별 규격과 프롬프트.

이 파일 하나가 "플랫폼마다 무엇이 다른가"를 전부 담는다.
플랫폼을 더하거나 규격이 바뀌면 여기만 고치면 된다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 톤앤매너 두 가지. 보너스 과제(A/B 테스트)가 이 둘을 같은 주제로 돌려 비교한다.
TONES = {
    "friendly": "친근하고 말 걸듯이. 반말은 쓰지 않되 '~해요' 체로 다정하게.",
    "professional": "차분하고 정보 중심으로. '~합니다' 체로 신뢰감 있게.",
}


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    limit_note: str      # 사람이 읽는 규격 설명
    rules: str           # 프롬프트에 그대로 들어갈 지시
    schema: dict         # 응답 형식 강제


INSTAGRAM = Platform(
    key="instagram",
    name="인스타그램",
    limit_note="캡션 150자 내외 + 해시태그 10개 내외",
    rules=(
        "- caption: 150자 내외의 한국어 캡션. 첫 문장에서 시선을 잡습니다.\n"
        "- 줄바꿈은 쓰지 않고 한 덩어리로 씁니다.\n"
        "- hashtags: 해시태그 10개. '#' 를 포함하고 띄어쓰기 없이 씁니다.\n"
        "- 해시태그는 넓은 것(#여행)과 좁은 것(#성지순례)을 섞습니다."
    ),
    schema={
        "type": "OBJECT",
        "properties": {
            "caption": {"type": "STRING"},
            "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["caption", "hashtags"],
    },
)

BLOG = Platform(
    key="blog",
    name="블로그",
    limit_note="본문 500자 이상 + 소제목 3개 이상",
    rules=(
        "- title: 검색으로 찾아올 만한 제목 한 줄.\n"
        "- sections: 소제목 3~4개. 각 소제목마다 body 를 붙입니다.\n"
        "- 모든 body 를 합쳐 500자 이상이어야 합니다.\n"
        "- 정보를 담습니다. 감탄사로 분량을 채우지 않습니다."
    ),
    schema={
        "type": "OBJECT",
        "properties": {
            "title": {"type": "STRING"},
            "sections": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {"heading": {"type": "STRING"}, "body": {"type": "STRING"}},
                    "required": ["heading", "body"],
                },
            },
        },
        "required": ["title", "sections"],
    },
)

X = Platform(
    key="x",
    name="X (구 트위터)",
    limit_note="280자 이내",
    rules=(
        "- text: 공백 포함 **240자 이내**. 해시태그 2~3개를 문장 끝에 붙입니다.\n"
        "- 280자 제한이라 여유를 두고 240자로 씁니다.\n"
        "- 핵심 하나만 말합니다. 나열하지 않습니다."
    ),
    schema={
        "type": "OBJECT",
        "properties": {"text": {"type": "STRING"}},
        "required": ["text"],
    },
)

PLATFORMS = (INSTAGRAM, BLOG, X)


def build_prompt(platform: Platform, topic: str, tone_key: str, brand: str) -> str:
    """플랫폼 × 톤 조합으로 프롬프트를 만든다.

    구조를 [역할] → [브랜드] → [주제] → [플랫폼 규격] → [톤] → [출력형식] 으로 고정한다.
    순서를 고정해 두면 결과가 나쁠 때 어느 칸을 고칠지 바로 짚을 수 있다.
    """
    return (
        f"당신은 소셜 미디어 콘텐츠 에디터입니다.\n\n"
        f"[브랜드]\n{brand}\n\n"
        f"[주제]\n{topic}\n\n"
        f"[플랫폼] {platform.name} — {platform.limit_note}\n{platform.rules}\n\n"
        f"[톤앤매너]\n{TONES[tone_key]}\n\n"
        f"[공통 규칙]\n"
        f"- 한국어로 씁니다.\n"
        f"- 사실이 아닌 수치나 일정을 지어내지 않습니다.\n"
        f"- 종교를 권하는 표현은 쓰지 않습니다. 누구나 걸을 수 있는 곳으로 소개합니다.\n\n"
        f"[출력 형식] 지정된 JSON 만 출력합니다."
    )
