# Qwen3-4B 추가 학습 데이터 200건

## 구성
- Source: 200건
- SFT: 200건
- Fashion Recommendation: 125건
- Tool Calling: 75건

## 기존 데이터
- 기존 Train: 664건
- 추가 Train: 200건
- 통합 Train 후보: 864건
- 기존 Validation: 8건 (유지)
- 기존 Test: 8건 (유지)

## 검증 결과
- Qwen3-4B 토크나이저 검증: 864건
- 평균 토큰: 1462.95
- 최대 토큰: 2198
- 2048 초과: 65건
- 2560 초과: 0건

## 주의사항
- train_864_candidate.jsonl은 학습 후보본입니다.
- 기존 Validation/Test를 학습에 포함하지 마세요.
- 학습 시 최대 시퀀스 길이 2560 이상을 검토하세요.
