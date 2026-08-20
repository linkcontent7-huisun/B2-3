# fix_plan.md — 랄프 루프 백로그

루프의 기억 장치. 매 반복마다 여기서 **하나**를 골라 끝내고 갱신한다.

## 미완료

- [ ] README 에 랄프 루프 사용법(`./ralph.sh`) 섹션 추가

## 완료

- [x] 같은 주제 재실행 시 `-2`, `-3` 접미사로 저장 — `pipeline.unique_dir` + 테스트 2건 (2026-08-20)
- [x] 규격·재시도 단위 테스트 12건 — `tests/test_pipeline.py`, `python -m unittest discover tests` (2026-08-20)
- [x] 규격 위반 시 피드백 재시도(최대 2회) — `pipeline.generate_one` (2026-08-20)
- [x] 랄프 루프 도입 — CLAUDE.md · PROMPT.md · ralph.sh · fix_plan.md (2026-08-20)
