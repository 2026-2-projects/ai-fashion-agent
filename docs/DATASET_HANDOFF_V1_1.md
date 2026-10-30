# Qwen3-4B 패션 추천 에이전트 — 학습 데이터 인계

## 릴리스 요약

| 항목 | 내용 |
|---|---|
| 릴리스 | `qwen3_fashion_664_v1_1` |
| 학습 | 664건 = Gold 64 + Synthetic 600 |
| 유형 | FR 415 / TC 249 |
| 검증 / 테스트 | 8 / 8, 동결 (학습 및 합성 참조 금지) |
| 상태 | 자동 검증 및 AI 보조 품질 점검 완료 / 인간 최종 의미 서명 대기 |

## 진호에게 전달할 파일

- `data/releases/qwen3_fashion_664_v1_1/train.jsonl` — 학습 데이터
- `data/releases/qwen3_fashion_664_v1_1/validation.jsonl` — 검증용 (튜닝과 성능 점검용)
- `data/releases/qwen3_fashion_664_v1_1/test.jsonl` — 최종 평가 전용 (학습 제외, 성능 튜닝 반복 참조 지양)
- `data/releases/qwen3_fashion_664_v1_1/train_provenance.jsonl` — 출처/ID; train과 행 순서 일치
- `data/releases/qwen3_fashion_664_v1_1/manifest.json` — 버전, 각 파일 SHA256, 상태
- `data/releases/qwen3_fashion_664_v1_1/quality_report.json` — 실제 품질 점검 결과
- `data/releases/qwen3_fashion_664_v1_1/quality_edits.csv` — 수정 이력
- `data/releases/qwen3_fashion_664_v1_1/priority_review_57.csv` — 50개 표본과 고온 15개 중 중복 제외 57건 검수 목록; 사람 서명은 별도

## 학습 데이터 형식

JSONL 각 줄은 `{"messages": [...], "tools": [...]}`. FR은 system/user/assistant와 5개 LOOK을 담은 JSON 문자열을 포함한다. TC는 assistant의 `tool_calls`, 도구 결과, 최종 JSON 응답이 포함된다. `generate_five_looks`는 실제 Tool 이름이 아니라 최종 응답의 `action` 값이다.

**중요:** Qwen3 학습 스택의 `apply_chat_template`와 실제 `tool_calls[].function.arguments`(객체 형태) 처리 호환성은 현재 미검증이다. 진호가 반드시 소량 렌더링 후 학습을 시작해야 한다.

## v1 기준선 보호 & 확장

1. 이 폴더는 버전 고정. 수정을 원할 경우 v1.2 / v2 새 릴리스 디렉터리 생성.
2. Synthetic 추가 시 기존 Val/Test 참조나 복제 금지.
3. 동일한 검증/평가 세트로 성능 비교. 8개씩은 작기 때문에 추가 독립 평가세트 확보 권장.
4. 학습 전에 `python3 scripts/quality/verify_dataset_v1_1.py` 실행.

## GitHub 푸시

기존 v1 경로를 덮어쓰지 않고 v1.1 릴리스만 추가한다. 먼저 `git status --short`와 `git remote -v`를 확인한다.

```bash
python3 scripts/quality/verify_dataset_v1_1.py
git add data/releases/qwen3_fashion_664_v1_1 docs/DATASET_HANDOFF_V1_1.md scripts/quality/verify_dataset_v1_1.py
git diff --cached --stat
git commit -m "data: add QA-reviewed Qwen3 fashion SFT dataset v1.1"
git push origin HEAD
```

GitHub에 게시했다고 최종 인간 서명이 완료된 것은 아니다. 미검증 조건은 항상 문서로 남긴다.
