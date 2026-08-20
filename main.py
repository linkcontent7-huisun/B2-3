#!/usr/bin/env python3
"""소셜 미디어 콘텐츠 자동 생성 (코디세이 B2-3 / Project C).

    python main.py                              # 대화형 — 주제를 물어본다
    python main.py --topic "가을 순례길" --ab    # 비대화형 + A/B 두 버전

주제 하나를 넣으면 인스타그램·블로그·X 용 텍스트와 대표 이미지를 만들어
`output/` 에 플랫폼별로 정리해 저장한다.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from social_content import pipeline
from social_content.ai import AiKeyMissingError, build_client
from social_content.config import ConfigError, load_config

# 한국 Windows 콘솔 기본 인코딩은 cp949 라, 화살표나 이모지에서 프로그램이 죽는다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format="[%(levelname)s] %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def ask_topic(preset: str | None) -> str:
    """[1] 주제 입력 — 이 워크플로우의 트리거."""
    if preset:
        return preset.strip()
    while True:
        answer = input("주제 또는 키워드를 입력하세요: ").strip()
        if answer:
            return answer
        print("  ⚠️  주제는 비워 둘 수 없습니다.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="주제 하나로 플랫폼별 소셜 콘텐츠를 만듭니다.")
    parser.add_argument("--topic", help="주제 (주면 묻지 않습니다)")
    parser.add_argument("--brand", help="브랜드 설명 (기본값은 config.json)")
    parser.add_argument(
        "--tone",
        choices=["friendly", "professional"],
        help="톤 하나만 생성 (기본은 config.json 의 tones)",
    )
    parser.add_argument("--ab", action="store_true", help="[보너스] 두 톤을 모두 만들어 A/B 비교")
    parser.add_argument("--no-image", action="store_true", help="대표 이미지를 만들지 않습니다")
    parser.add_argument("--config", help="설정 파일 경로 (기본값 config.json)")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING"], default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"[ERROR] 설정 오류: {exc}")
        return 2

    print("\n📣 소셜 미디어 콘텐츠 자동 생성\n")

    try:
        topic = ask_topic(args.topic)
    except (EOFError, KeyboardInterrupt):
        print("\n\n입력이 취소되었습니다.")
        return 130

    tones = ["friendly", "professional"] if args.ab else ([args.tone] if args.tone else config.tones)
    brand = args.brand or config.brand

    try:
        client = build_client(config.llm_provider, config.llm_api_key, config.timeout_sec)
    except AiKeyMissingError as exc:
        print(f"[ERROR] {exc}")
        return 2

    print(f"[1] 주제: {topic}")
    print(f"    톤: {', '.join(tones)} · 플랫폼: 인스타그램, 블로그, X\n")

    result, out = pipeline.run(
        client, topic, brand, tones, config.output_dir, with_image=not args.no_image
    )

    print("\n" + "─" * 60)
    print(f"  저장 위치 : {out}")
    for name in sorted(path.name for path in out.iterdir()):
        print(f"    - {name}")

    made = sum(len(per_platform) for per_platform in result.contents.values())
    print(f"\n  텍스트 {made}건 · 이미지 {'1장' if result.image else '없음'}")

    if result.errors:
        print(f"\n⚠️  {len(result.errors)}개 단계가 실패했습니다.")
        for error in result.errors:
            print(f"   - {error['step']}: {error['message'][:100]}")
        return 0 if made else 1

    print("\n✅ 완료! 노션에 올리려면 콘텐츠.md 를 붙여 넣으세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
