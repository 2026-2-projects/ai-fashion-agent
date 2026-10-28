# Qwen3.5-4B LoRA Pilot

## 목적

Gold Data 80개를 이용해 Base 평가, LoRA 학습, 학습 후 평가까지
전체 Fine-Tuning 파이프라인을 검증한다.

## 데이터 구성

- 전체: 80개
- Train: 64개
- Validation: 8개
- Test: 8개
- FR: 50개
- TC: 30개

## 학습 설정

- Base Model: unsloth/Qwen3.5-4B
- Method: 16-bit LoRA
- Epoch: 3
- LoRA r: 16
- LoRA alpha: 16
- Learning rate: 2e-4
- GPU: Google Colab T4

## 결과

- FR 3 LOOK 준수: 0/5 → 4/5
- TC 첫 Tool 선택: 3/3 → 3/3
- 전체 단순 평가 통과: 3/8 → 7/8
- FR-015에서 JSON 문법 오류 확인

## 한계

현재 결과는 Gold Data 80개만 사용한 Pilot 결과다.
합성 데이터 500~1,000개와 HITL 검수 후 최종 학습을 다시 진행한다.

## 주의사항

- 이번 학습은 파이프라인 검증용입니다. 80개만으로 얻은 성능을 최종 모델 성능으로 해석하지 않습니다.
- 현재 가이드와 Gold Data 80개는 모두 3 LOOK 구조입니다. README에 남아 있는 5 LOOK 변경 메모는 팀 결정과 전체 데이터 수정이 끝날 때까지 반영하지 않습니다.
- 최종 학습에서는 합성 데이터와 HITL 승인 데이터를 사용하고 동일한 Test Set은 학습에 포함하지 않습니다.
