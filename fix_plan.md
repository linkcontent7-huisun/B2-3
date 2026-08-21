# fix_plan.md — 랄프 루프 백로그

루프의 기억 장치. 매 반복마다 여기서 **하나**를 골라 끝내고 갱신한다.

## 미완료

- [ ] `check_format` 이 빈 내용을 잡지 못한다 — X `text` 가 빈 문자열이면
      0자라 "280자 초과"에 안 걸려 통과한다. 플랫폼별 최소 길이 검사 추가
- [ ] `pipeline.run` 이 임시 이미지를 `base_dir/_tmp-cover.png` 에 쓴다 —
      동시에 두 번 돌리면 서로 덮어쓰고, 중간에 죽으면 파일이 남는다.
      `tempfile` 을 쓰거나 저장 폴더가 정해진 뒤에 받도록
- [ ] `--ab` 와 `--tone` 을 같이 주면 `--tone` 이 조용히 무시된다 (`main.py:78`).
      경고를 띄우거나 argparse 상호 배타 그룹으로

## 완료

- [x] README 에 랄프 루프 개발 방식 섹션 + 구조 트리 갱신 (2026-08-20)
- [x] 같은 주제 재실행 시 `-2`, `-3` 접미사로 저장 — `pipeline.unique_dir` + 테스트 2건 (2026-08-20)
- [x] 규격·재시도 단위 테스트 12건 — `tests/test_pipeline.py`, `python -m unittest discover tests` (2026-08-20)
- [x] 규격 위반 시 피드백 재시도(최대 2회) — `pipeline.generate_one` (2026-08-20)
- [x] 랄프 루프 도입 — CLAUDE.md · PROMPT.md · ralph.sh · fix_plan.md (2026-08-20)
