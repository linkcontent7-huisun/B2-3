#!/usr/bin/env python3
"""워크플로우 구조도를 PNG 로 그린다.

    python docs/make_diagram.py

명세가 "워크플로우 구조를 보여주는 스크린샷"을 요구한다. 노코드 툴 캔버스를
찍는 대신 구조를 직접 그린다. 스크린샷과 달리 코드로 남아서, 워크플로우가
바뀌면 이 파일을 고쳐 다시 뽑을 수 있다.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.patches as patches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

NAVY = "#1E3A8A"      # VisitHolyKorea 메인 컬러 (A2-1 에서 확정)
SKY = "#38BDF8"
GOLD = "#D4AF37"
CREAM = "#F4F1DE"
GREY = "#6B7280"

KOREAN_FONTS = ("Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR")


def apply_font() -> None:
    installed = {font.name for font in fm.fontManager.ttflist}
    for name in KOREAN_FONTS:
        if name in installed:
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return


def box(axes, x, y, w, h, title, lines, face, edge, title_color="white"):
    axes.add_patch(
        patches.FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            facecolor=face, edgecolor=edge, linewidth=1.6,
        )
    )
    axes.text(x + w / 2, y + h - 0.16, title, ha="center", va="top",
              fontsize=11.5, fontweight="bold", color=title_color)
    for index, line in enumerate(lines):
        axes.text(x + w / 2, y + h - 0.42 - index * 0.2, line, ha="center", va="top",
                  fontsize=9, color=title_color)


def arrow(axes, x1, y1, x2, y2, label=""):
    axes.annotate(
        "", xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(arrowstyle="-|>", color=GREY, linewidth=1.8, mutation_scale=18),
    )
    if label:
        axes.text((x1 + x2) / 2 + 0.06, (y1 + y2) / 2, label, fontsize=8.5,
                  color=GREY, ha="left", va="center")


def main() -> Path:
    apply_font()
    figure, axes = plt.subplots(figsize=(13, 7.2))
    axes.set_xlim(0, 13)
    axes.set_ylim(1.2, 7.2)
    axes.axis("off")

    axes.text(6.5, 6.95, "소셜 미디어 콘텐츠 자동 생성 워크플로우",
              ha="center", va="top", fontsize=16, fontweight="bold", color=NAVY)
    axes.text(6.5, 6.55, "주제 하나 → 3개 플랫폼 텍스트 + 대표 이미지 → 저장",
              ha="center", va="top", fontsize=10, color=GREY)

    # [1] 입력
    box(axes, 0.4, 4.5, 2.5, 1.3, "[1] 주제 입력",
        ["main.py (CLI)", "대화형 input() 또는", "--topic 옵션"], NAVY, NAVY)

    # 설정
    box(axes, 0.4, 2.6, 2.5, 1.4, "설정",
        ["config.json", "· 브랜드 설명", "· 톤 목록", ".env → API 키"], CREAM, GOLD, "#333333")
    arrow(axes, 1.65, 4.0, 1.65, 4.5)

    arrow(axes, 2.9, 5.15, 3.9, 5.1)

    # [2] 텍스트 생성
    box(axes, 3.9, 4.35, 3.6, 1.45, "[2] 플랫폼별 텍스트 생성",
        ["platforms.py 의 규격 + 톤으로", "프롬프트를 만들어 LLM 호출",
         "플랫폼 3 × 톤 N 회"], SKY, SKY, "#0B2545")

    # 플랫폼 3개 — [2] 바로 아래에 붙여 "무엇을 만드는지"를 한눈에 보이게 한다
    for index, (name, spec) in enumerate([
        ("인스타그램", "캡션 150자 + 해시태그 10개"),
        ("블로그", "본문 500자 이상 + 소제목 3개 이상"),
        ("X (구 트위터)", "280자 이내"),
    ]):
        y = 3.55 - index * 0.6
        # 제목 없이 한 줄만 담는 칸이라 box() 대신 직접 그린다.
        # box() 는 제목 자리를 비워 두므로 여기 쓰면 글자가 아래로 밀려난다.
        axes.add_patch(
            patches.FancyBboxPatch(
                (3.9, y), 3.6, 0.5,
                boxstyle="round,pad=0.02,rounding_size=0.06",
                facecolor="white", edgecolor=SKY, linewidth=1.4,
            )
        )
        axes.text(5.7, y + 0.25, f"{name} — {spec}", ha="center", va="center",
                  fontsize=9.5, color="#0B2545")
    axes.plot([5.7, 5.7], [4.35, 4.05], color=SKY, linewidth=1.4, linestyle=":")

    # 규격 검증
    box(axes, 8.0, 3.5, 2.2, 1.0, "규격 검증",
        ["글자 수·태그 수를", "세어 어긋나면 표시"], CREAM, GOLD, "#333333")
    arrow(axes, 7.5, 4.7, 8.0, 4.2)

    # [3] 이미지
    box(axes, 8.0, 4.9, 2.2, 1.4, "[3] 대표 이미지",
        ["LLM 이 영어 장면 묘사", "→ 이미지 API", "→ PNG 1장"], NAVY, NAVY)
    arrow(axes, 7.5, 5.5, 8.0, 5.7)

    # [4] 저장
    box(axes, 10.7, 3.9, 2.0, 2.0, "[4] 저장",
        ["output/날짜-주제/", "· 콘텐츠.md", "· result.json", "· cover.png"], GOLD, GOLD, "#1a1a1a")
    arrow(axes, 10.2, 5.6, 10.7, 5.2)
    arrow(axes, 10.2, 4.0, 10.7, 4.4)

    # 노션
    box(axes, 10.7, 2.0, 2.0, 1.4, "노션 페이지",
        ["플랫폼별로 구분", "팀 역할·작업 요약"], CREAM, NAVY, "#333333")
    arrow(axes, 11.7, 3.9, 11.7, 3.4)

    axes.text(6.5, 1.45,
              "한 단계가 실패해도 다음 단계는 진행한다 — 이미지 API 가 막혀도 텍스트는 남는다.",
              ha="center", fontsize=9.5, color=GREY, style="italic")

    output = Path(__file__).resolve().parent / "workflow.png"
    figure.savefig(output, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    print(f"저장: {output}")
    return output


if __name__ == "__main__":
    main()
