# Qwen3 패션 추천 데이터셋 — v1.1 QA 인계본

- Train: **664건** (Gold 64, Synthetic 600; FR 415, TC 249)
- Validation: **8건**; Test: **8건** (훈련 금지)
- 학습 데이터: `train.jsonl` (한 줄에 `messages`, `tools` 를 가진 JSON 객체)
- 출처 정보: `train_provenance.jsonl` (train과 같은 행 순서, `id` 및 `source` 포함)
- 이번 변경: 33℃ 이상 겉옷 착용 조건 보수화, 확실한 한국어 표현 오류 교정, 원본 Gold·TC 및 검증/테스트 원본 불변
- 무결성 검증: 저장소 루트에서 `python3 scripts/quality/verify_dataset_v1_1.py`
- 상세 검수 내역: `quality_report.json`, `quality_edits.csv`, `priority_review_57.csv`

**주의:** 자동/AI 보조 검수와 인간 최종 의미 승인은 다릅니다. 현재 최종 인간 서명 없음. Qwen3 `apply_chat_template` 실환경 검증도 진호가 수행해야 합니다.
