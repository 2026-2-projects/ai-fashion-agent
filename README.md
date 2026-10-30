# AI 기반 개인 맞춤형 패션 에이전트

Qwen3-4B 기반 패션 특화 언어 모델과 Tool Calling을 활용하여, 사용자 취향·보유 의류·날씨·일정에 맞는 코디를 추천하는 팀 프로젝트입니다.

> **진행 상태:** 학습 데이터셋 **v1.1** 준비 및 검증 완료 · Qwen3-4B 파인튜닝과 서비스 연동은 별도 진행 중
> **최종 발표:** 2026년 12월 1일

## 프로젝트 개요

- **Fashion SLM:** Qwen3-4B를 패션 추천(FR) 및 도구 호출(TC) 데이터로 QLoRA(4-bit) 파인튜닝하는 것을 목표로 합니다.
- **AI Agent:** 필요한 경우 사용자 옷장, 위치·날씨, 일정 등을 조회하는 Router + Tool Calling 구조를 지향합니다.
- **맞춤 추천:** 개인 취향과 제약 조건을 반영하여 서비스에서 코디 **3가지**를 제공하는 것이 목표입니다. 학습 데이터의 FR 정답에는 평가·선택을 위한 **5가지 역할별 LOOK 후보**가 포함되어 있으며, 이는 서비스에 5개 코디를 모두 표시한다는 뜻은 아닙니다.

## 주요 기술

| 영역 | 기술 / 계획 |
|---|---|
| AI 모델 | Qwen3-4B |
| 파인튜닝 | QLoRA (4-bit) |
| 백엔드 | Python, FastAPI |
| 데이터베이스 | PostgreSQL |
| 프론트엔드 | JavaScript, HTML, CSS |
| UI/UX | Figma |
| 위치·날씨·일정 연동 | Kakao Local API, 기상청 API, Google Calendar API(Read Only) |

> 위 표는 프로젝트에서 사용하는 기술과 적용 계획을 함께 나타내며, 모든 기능의 구현 완료를 의미하지 않습니다.

## 학습 데이터셋 — v1.1

**현재 인계 기준:** `data/releases/qwen3_fashion_664_v1_1/`

| 구분 | Train | Validation | Test |
|---|---:|---:|---:|
| Gold | 64 | 8 | 8 |
| Synthetic | 600 | 0 | 0 |
| **합계** | **664** | **8** | **8** |

- Train 분포: **FR 415건 / TC 249건**
- JSONL 레코드 형식: `messages`와 `tools` 필드 사용
- FR: 취향 중심·탐색형·보유 의류 기반 등 5가지 역할의 LOOK 후보를 포함
- TC: 도구 호출, 도구 응답, 최종 답변을 포함
- **우선 의미 검수 57건**: 사람이 확인하여 **승인 57 / 수정 필요 0 / 보류 0**으로 기록
- **자동 검사 통과**: SHA256, 데이터 수·분할, 출처 ID, JSON 구조, 도구 호출 연결, 옷장 ID, 동일 사용자 요청 중복 등

**검증 범위에 관한 주의:** 57건의 사람 검수는 **전체 664건 전수 검수와 다릅니다.** 또한 실제 Qwen3 채팅 템플릿·토크나이저의 학습 파이프라인 호환성은 학습 담당자가 별도 확인해야 합니다.

### 파일 안내

```text
data/releases/qwen3_fashion_664_v1_1/
├── train.jsonl                # 모델 학습용 (664건)
├── validation.jsonl           # 검증용 (8건)
├── test.jsonl                 # 최종 평가용 (8건)
├── train_provenance.jsonl     # 학습 데이터별 Gold/Synthetic 출처
├── manifest.json             # 분할·검증·해시 정보
├── priority_review_57.csv    # 사람 의미 검수 승인 기록
├── quality_report.json       # 품질 검증 상태
└── README.md                 # 데이터셋 상세 설명
```

세부 데이터 계약, 사용 주의사항 및 학습 담당자 인계 내용은 **[데이터셋 인계 문서](docs/DATASET_HANDOFF_V1_1.md)**를 참조하세요.

### 인계 전·학습 전 확인

저장소 루트에서 다음을 실행합니다.

```bash
python3 scripts/quality/verify_dataset_v1_1.py
```

검증 출력의 `PASS`는 명시된 자동 검사 항목을 통과했다는 의미입니다. 모델 학습 단계에서는 별도로 **Qwen3 채팅 템플릿 적용, TC 함수 인자 직렬화, 토크나이저 결과**를 확인해야 합니다.

## 프로젝트 디렉터리

```text
backend/                       # 백엔드 코드와 테스트
data/
  releases/qwen3_fashion_664_v1_1/  # 팀원에게 인계하는 v1.1 기준 데이터셋
  gold/                        # Gold 원본 데이터 관련 자산
  synthetic/                   # Synthetic 생성 데이터 관련 자산
  processed/                   # 중간 생성물 (Git 반영 대상과 구분)
docs/                          # 설계·실험·데이터 인계 문서
scripts/
  mixed_dataset/               # 데이터 변환·혼합 스크립트
  quality/                     # 품질 검사 스크립트
```

중간 생성물, 과거 후보본, 원본 배치 파일과 **현재 배포 기준 데이터셋**은 구분해서 관리합니다. 학습 담당자는 우선 `releases/qwen3_fashion_664_v1_1/`을 기준으로 사용하세요.

## Git 브랜치 전략

```text
main
└── develop
    └── feature/*
```

기능 브랜치에서 검증·리뷰를 거친 뒤 팀의 병합 정책에 따라 통합합니다.

## 이후 데이터 확장

Synthetic 데이터를 추가하더라도 **v1.1 데이터셋을 덮어쓰지 않고**, 별도의 후속 버전(v2 등)으로 관리합니다. 데이터 확장에 따른 성능 차이는 동일한 평가 조건에서 비교합니다.

## 상세 설계

Agent Architecture, Tool 구성, 전체 프로젝트 구조 등은 [프로젝트 상세 구조](docs/project-structure.md)를 참조하세요.
