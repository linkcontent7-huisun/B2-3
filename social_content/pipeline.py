"""워크플로우 본체 — 주제 하나로 플랫폼별 콘텐츠와 대표 이미지를 만든다.

    [1] 주제 입력
         ↓
    [2] 플랫폼별 텍스트 생성   (LLM, 플랫폼 × 톤 조합만큼 호출)
         ↓
    [3] 대표 이미지 생성       (이미지 생성 API)
         ↓
    [4] 결과 저장              (JSON + 마크다운 + PNG, 플랫폼별로 구분)

한 단계가 실패해도 다음 단계는 진행한다. 이미지 API 가 막혀도
텍스트는 남아야 하고, 그 반대도 마찬가지다.
"""

from __future__ import annotations

import io
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from .ai import AiCallError
from .platforms import PLATFORMS, build_prompt

logger = logging.getLogger(__name__)

# 키가 필요 없는 무료 이미지 생성 API. 인증 없이 쓸 수 있는 모델은 sana 하나다.
POLLINATIONS = "https://image.pollinations.ai/prompt"
IMAGE_MODEL = "sana"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

X_LIMIT = 280
BLOG_MIN_CHARS = 500
MAX_FORMAT_RETRIES = 2  # 규격 위반 시 피드백을 붙여 다시 부르는 횟수

TONE_LABELS = {"friendly": "A안 · 친근한 톤", "professional": "B안 · 전문적인 톤"}


@dataclass
class Result:
    topic: str
    brand: str
    generated_at: str
    contents: dict = field(default_factory=dict)  # {tone: {platform_key: {...}}}
    image: dict | None = None
    errors: list = field(default_factory=list)

    def fail(self, step: str, message: str) -> None:
        logger.error("%s 실패 — %s", step, message)
        self.errors.append({"step": step, "message": message})


# ---------------------------------------------------------------------------
# [2] 플랫폼별 텍스트
# ---------------------------------------------------------------------------


def check_format(platform_key: str, data: dict) -> list[str]:
    """규격을 실제로 지켰는지 센다.

    프롬프트에 '280자 이내'라고 적어도 모델은 넘긴다. 세어 보고 어긋나면
    결과에 적어 둔다 — 조용히 넘기면 규격을 어긴 채로 게시된다.
    """
    warnings = []
    if platform_key == "x":
        length = len(data.get("text", ""))
        if length > X_LIMIT:
            warnings.append(f"{X_LIMIT}자 초과 ({length}자)")
    elif platform_key == "blog":
        sections = data.get("sections", [])
        total = sum(len(section.get("body", "")) for section in sections)
        if total < BLOG_MIN_CHARS:
            warnings.append(f"본문 {BLOG_MIN_CHARS}자 미만 ({total}자)")
        if len(sections) < 3:
            warnings.append(f"소제목 3개 미만 ({len(sections)}개)")
    elif platform_key == "instagram":
        tags = data.get("hashtags", [])
        if not 8 <= len(tags) <= 12:
            warnings.append(f"해시태그 10개 내외를 벗어남 ({len(tags)}개)")
    return warnings


def generate_one(client, platform, topic: str, tone: str, brand: str, label: str) -> dict:
    """규격을 지킬 때까지 최대 MAX_FORMAT_RETRIES 회 다시 부른다.

    프롬프트에 규격을 적어도 모델은 가끔 어긴다. 어긴 항목을 그대로
    피드백으로 붙여 다시 시키면 대부분 고쳐 온다. 끝까지 안 되면
    위반이 가장 적은 결과를 채택한다 — 아무것도 없는 것보다 낫다.
    """
    base_prompt = build_prompt(platform, topic, tone, brand)
    prompt = base_prompt
    best: dict | None = None
    for attempt in range(1 + MAX_FORMAT_RETRIES):
        try:
            data = client.complete_json(prompt, platform.schema)
        except AiCallError:
            if best is None:
                raise  # 첫 시도부터 실패면 기존처럼 단계 실패로 올린다
            break  # 재시도 중 통신 실패면 지금까지의 최선을 쓴다
        data["_warnings"] = check_format(platform.key, data)
        if not data["_warnings"]:
            return data
        if best is None or len(data["_warnings"]) < len(best["_warnings"]):
            best = data
        if attempt < MAX_FORMAT_RETRIES:
            logger.warning(
                "  규격 위반 — %s (%d/%d 재시도): %s",
                label, attempt + 1, MAX_FORMAT_RETRIES, ", ".join(data["_warnings"]),
            )
            prompt = (
                f"{base_prompt}\n\n"
                f"[재작성 요청]\n"
                f"직전 결과가 규격을 어겼습니다: {', '.join(data['_warnings'])}.\n"
                f"위 규격을 정확히 지켜 처음부터 다시 작성하세요."
            )
    assert best is not None
    logger.warning("  규격 위반 유지 — %s: %s", label, ", ".join(best["_warnings"]))
    return best


def generate_texts(client, topic: str, brand: str, tones: list[str], result: Result) -> None:
    """플랫폼 × 톤 조합마다 한 번씩 LLM 을 부른다."""
    for tone in tones:
        result.contents.setdefault(tone, {})
        for platform in PLATFORMS:
            label = f"{platform.name}/{tone}"
            logger.info("[2] 텍스트 생성 — %s", label)
            try:
                data = generate_one(client, platform, topic, tone, brand, label)
            except AiCallError as exc:
                result.fail(f"텍스트 생성 {label}", str(exc))
                continue
            result.contents[tone][platform.key] = data


# ---------------------------------------------------------------------------
# [3] 대표 이미지
# ---------------------------------------------------------------------------

SCENE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"scene_en": {"type": "STRING"}, "why_ko": {"type": "STRING"}},
    "required": ["scene_en", "why_ko"],
}


def build_image_prompt(client, topic: str, brand: str) -> tuple[str, str]:
    """LLM 에게 '무엇을 그릴지' 영어로 먼저 옮기게 한다.

    한국어 주제를 이미지 API 에 그대로 넘기면 엉뚱한 그림이 나온다.
    (A2-1 에서 '20-30대 여성'을 인물 사진 요청으로 읽어 사람 사진이 나왔다.)
    """
    prompt = (
        f"소셜 미디어 대표 이미지로 무엇을 그릴지 정하세요.\n\n"
        f"[브랜드]\n{brand}\n\n[주제]\n{topic}\n\n"
        "[요청]\n"
        "- scene_en: 이미지 생성 AI 에게 넘길 영어 묘사. 20단어 안팎.\n"
        "- scene_en 에 사람 얼굴과 글자를 넣지 않습니다. 한국어를 섞지 않습니다.\n"
        "- why_ko: 이 장면을 고른 이유를 한국어 한 문장으로.\n\n"
        '[출력 형식]\n{"scene_en": "english scene", "why_ko": "이유"}'
    )
    data = client.complete_json(prompt, SCENE_SCHEMA)
    scene = str(data.get("scene_en") or "").strip()
    if not scene or any("가" <= char <= "힣" for char in scene):
        raise AiCallError(f"쓸 수 있는 영어 장면 묘사를 받지 못했습니다: {scene[:40]!r}")
    return scene, str(data.get("why_ko") or "").strip()


def generate_image(scene_en: str, output_path: Path, seed: int = 1) -> Path:
    """대표 이미지 1장을 PNG 로 저장한다."""
    prompt = (
        f"{scene_en}, serene documentary photography, soft natural morning light, "
        "deep navy and warm cream tones, no text, no letters, no watermark"
    )
    url = (
        f"{POLLINATIONS}/{urllib.parse.quote(prompt)}"
        f"?width=1024&height=1024&nologo=true&model={IMAGE_MODEL}&seed={seed}"
    )
    response = requests.get(url, timeout=240)
    if response.status_code != 200 or not response.content:
        raise AiCallError(f"이미지 생성 실패: HTTP {response.status_code}")

    data = response.content
    if data[:8] != PNG_SIGNATURE:
        # 공급자가 JPEG 로 줄 때가 있다. 확장자만 png 로 바꾸면 파일이 깨진다.
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
            data = buffer.getvalue()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return output_path


# ---------------------------------------------------------------------------
# [4] 저장
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    return re.sub(r"[^\w가-힣]+", "-", text).strip("-")[:40] or "topic"


def render_markdown(result: Result) -> str:
    """사람이 그대로 복사해 붙여 넣을 수 있는 형태로 만든다."""
    lines: list[str] = [f"# {result.topic}", ""]
    add = lines.append
    add(f"- 생성 시각: {result.generated_at}")
    add(f"- 브랜드: {result.brand}")
    if result.image:
        add(f"- 대표 이미지: {result.image['why_ko']}")
    add("")
    if result.image:
        add(f"![대표 이미지]({result.image['file']})")
        add("")

    for tone, per_platform in result.contents.items():
        add(f"## {TONE_LABELS.get(tone, tone)}")
        add("")
        for platform in PLATFORMS:
            data = per_platform.get(platform.key)
            add(f"### {platform.name}")
            add("")
            if not data:
                add("(생성 실패)")
                add("")
                continue

            if platform.key == "instagram":
                add(f"> {data['caption']}")
                add("")
                add(f"`{' '.join(data['hashtags'])}`")
                add("")
                add(f"*캡션 {len(data['caption'])}자 · 해시태그 {len(data['hashtags'])}개*")
            elif platform.key == "blog":
                total = sum(len(section["body"]) for section in data["sections"])
                add(f"**{data['title']}**")
                add("")
                for section in data["sections"]:
                    add(f"#### {section['heading']}")
                    add("")
                    add(section["body"])
                    add("")
                add(f"*본문 {total}자 · 소제목 {len(data['sections'])}개*")
            else:
                add(f"> {data['text']}")
                add("")
                add(f"*{len(data['text'])}자 / {X_LIMIT}자*")

            if data.get("_warnings"):
                add("")
                add(f"⚠️ 규격 확인 필요: {', '.join(data['_warnings'])}")
            add("")

    if result.errors:
        add("## 실패한 단계")
        add("")
        for error in result.errors:
            add(f"- **{error['step']}**: {error['message']}")
        add("")
    return "\n".join(lines)


def unique_dir(base_dir: Path, name: str) -> Path:
    """이미 있으면 -2, -3 … 을 붙인다. 같은 주제를 다시 돌려도 이전 결과를 지키기 위해."""
    out = base_dir / name
    suffix = 2
    while out.exists():
        out = base_dir / f"{name}-{suffix}"
        suffix += 1
    return out


def save(result: Result, base_dir: Path) -> Path:
    """플랫폼별로 구분해 저장한다. JSON 은 기계용, 마크다운은 사람용."""
    stamp = result.generated_at[:10].replace("-", "")
    out = unique_dir(base_dir, f"{stamp}-{slugify(result.topic)}")
    out.mkdir(parents=True, exist_ok=True)

    payload = {
        "topic": result.topic,
        "brand": result.brand,
        "generated_at": result.generated_at,
        "contents": result.contents,
        "image": result.image,
        "errors": result.errors,
    }
    (out / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "콘텐츠.md").write_text(render_markdown(result), encoding="utf-8")
    return out


def run(
    client,
    topic: str,
    brand: str,
    tones: list[str],
    base_dir: Path,
    with_image: bool = True,
) -> tuple[Result, Path]:
    """[1]~[4] 를 순서대로 실행한다."""
    result = Result(
        topic=topic, brand=brand, generated_at=datetime.now().isoformat(timespec="seconds")
    )

    generate_texts(client, topic, brand, tones, result)

    image_bytes = None
    if with_image:
        logger.info("[3] 대표 이미지 생성")
        try:
            scene, why = build_image_prompt(client, topic, brand)
            logger.info("  장면: %s", why)
            temp = base_dir / "_tmp-cover.png"
            generate_image(scene, temp)
            image_bytes = temp.read_bytes()
            temp.unlink(missing_ok=True)
            result.image = {"file": "cover.png", "scene_en": scene, "why_ko": why}
        except (AiCallError, requests.RequestException, OSError) as exc:
            result.fail("이미지 생성", str(exc))

    logger.info("[4] 결과 저장")
    out = save(result, base_dir)
    if image_bytes:
        (out / "cover.png").write_bytes(image_bytes)
    return result, out
