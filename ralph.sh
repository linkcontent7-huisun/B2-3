#!/usr/bin/env bash
# 랄프 루프 실행기 — PROMPT.md 를 Claude Code 에 반복해서 먹인다.
#
#   ./ralph.sh          # 무한 루프
#   ./ralph.sh 5        # 5회만 반복
#
# 각 반복은 새 컨텍스트로 시작하며, 진행 상태는 fix_plan.md 와
# git 커밋 이력에만 남는다. 중단은 Ctrl+C.

set -u
MAX=${1:-0}   # 0 = 무한
i=0

while :; do
  i=$((i + 1))
  echo "===== Ralph loop #$i — $(date '+%Y-%m-%d %H:%M:%S') ====="
  cat PROMPT.md | claude -p --verbose
  echo "===== loop #$i 종료 ====="
  [ "$MAX" -gt 0 ] && [ "$i" -ge "$MAX" ] && break
  sleep 2
done
