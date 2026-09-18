# AI 패션 에이전트 프로젝트 최종 구조

> 본 문서는 2026년 2학기 팀 프로젝트의 최종 확정 구조를 정리한 기준 문서이다. 프로젝트 구현, 팀 역할 분담, WBS, 발표, 보고서 작성 시 본 문서를 기준으로 한다.

---

## 1. 프로젝트 개요

### 1.1 프로젝트명
**AI 기반 개인 맞춤형 패션 에이전트**

※ 서비스의 최종 브랜드명과 로고는 개발 중 결정한다.

### 1.2 프로젝트 최종 정의
본 프로젝트는 **Qwen3-4B를 기반으로 패션 도메인에 특화된 SLM(소형 언어 모델)을 QLoRA(4비트 양자화 기반 저자원 파인튜닝 기법) 방식으로 파인튜닝**하고, 사용자의 자연어 요청을 분석하여 **프로필·패션 취향·보유 의류·목적지 날씨·Google Calendar 일정·이전 피드백 중 필요한 정보를 Agent(에이전트)가 선택적으로 조회하고 활용하는 Fashion AI Agent(패션 AI 에이전트)**를 개발하는 것을 목표로 한다.

최종적으로 **Figma를 활용해 UI/UX(사용자 인터페이스/사용자 경험)를 설계**하고, 해당 Agent를 **FastAPI Backend(백엔드) + PostgreSQL + JavaScript/HTML/CSS 기반 반응형 웹**과 통합하여 사용자에게 **개인 맞춤형 3가지 LOOK**을 제공한다.

### 1.3 프로젝트 핵심 방향
- 오픈소스 SLM(소형 언어 모델)을 직접 선정한다.
- Qwen3-4B를 패션 데이터로 직접 특화한다.
- Router(라우터) + Tool Calling(도구 호출) 구조의 Agent를 직접 구현한다.
- Agent(에이전트)가 사용자의 요청에 따라 필요한 Tool(도구)만 선택적으로 호출한다.
- 실제 사용자 옷장, 날씨, 일정, 취향, 피드백을 하나의 추천 판단에 연결한다.
- Wardrobe Validator(추천한 옷이 실제 사용자 옷장에 있는지 검사)와 JSON Validator(추천 결과 형식이 우리가 정한 JSON 구조에 맞는지 검사)로 결과를 검증한다.
- Base Model(기본 모델) → Base Model + Agent(기본 모델 + 에이전트) → Fine-Tuned Fashion Agent(파인튜닝된 패션 에이전트)의 성능 차이를 직접 평가한다.

---

## 2. 전체 시스템 구조

```text
사용자
  ↓
JavaScript + HTML + CSS 반응형 웹
  ↓
FastAPI Backend(백엔드)
  ↓
Fashion AI Agent(패션 AI 에이전트)
  ↓
Qwen3-4B
  ↓
Router(라우터) + Tool Calling(도구 호출)
  ↓
필요한 Tool 선택
  ├─ get_user_context()
  ├─ get_wardrobe()
  ├─ get_weather()
  └─ get_calendar_events()
  ↓
DB(데이터베이스) / Kakao Local / 기상청 / Google Calendar(캘린더)
  ↓
정보 종합
  ↓
패션 추론
  ↓
고정 JSON 구조의 3 LOOK 생성
  ↓
Wardrobe Validator / JSON Validator
  ↓
Frontend(프론트엔드) 결과 표시
```

---

## 3. AI 모델과 Agent의 역할 구분

### 3.1 Fashion SLM(패션 특화 소형 언어 모델)
Fashion SLM은 Agent의 두뇌 역할을 한다.

- 패션 코디 지식
- TPO(Time·Place·Occasion, 시간·장소·상황) 판단
- 계절·날씨 기반 패션 판단
- 스타일·색상·핏 조합 판단
- 코디 생성
- 추천 이유 생성
- Tool Calling(도구 호출) 판단을 위한 언어적 추론

### 3.2 Fashion Agent(패션 에이전트)
Fashion Agent는 전체 시스템의 의사결정 계층이다.

- 사용자 자연어 요청 해석
- 날짜·장소·상황·분위기 파악
- 필요한 Tool(도구) 판단
- Tool(도구) 호출
- Tool(도구) 결과 통합
- Fashion SLM에 필요한 Context(모델 참고정보) 구성
- 결과 JSON(구조화 데이터 형식) 생성
- 결과 검증
- 사용자에게 최종 응답 반환

### 3.3 Fashion SLM(패션 특화 소형 언어 모델)과 Fashion Agent(패션 에이전트)를 쉽게 구분하면

```text
[모델 개발]

Qwen3-4B
  ↓
패션 추천 데이터 + Tool Calling 데이터를 이용해
QLoRA 4bit 방식으로 Fine-Tuning(파인튜닝)
  ↓
Fine-Tuned Qwen3-4B
  ↓
Fashion SLM
```

여기서 **QLoRA는 데이터가 아니라 Fine-Tuning 방법**이다.  
프로젝트에서는 Qwen3-4B에 학습된 QLoRA Adapter(추가 학습 파라미터)를 적용한 결과를 편의상 **Fine-Tuned Qwen3-4B / Fashion SLM**이라고 부른다.

```text
[Agent 개발]

Fashion SLM
+ Router
+ Tool Calling
+ 4개 Tool
+ Context 구성
+ Validator
  ↓
Fashion Agent
```

즉, **Fashion SLM은 패션 판단을 담당하는 AI 두뇌**이고, **Fashion Agent는 그 두뇌가 실제 사용자 데이터·외부 API·검증 로직과 함께 동작하도록 만든 전체 시스템**이다.

### 3.4 핵심 용어 쉬운 설명

| 용어 | 쉬운 의미 | 프로젝트에서의 역할 |
|---|---|---|
| Qwen3-4B | 기본 AI 두뇌 | Fine-Tuning(파인튜닝·추가 학습) 전 Base Model(기본 모델) |
| Fine-Tuning(파인튜닝) | 추가 학습 | Qwen3-4B를 우리 프로젝트 목적에 맞게 특화 |
| QLoRA 4bit(4비트 양자화 기반 저자원 파인튜닝 기법) | Fine-Tuning 방법 | 적은 GPU 메모리로 Qwen3-4B를 학습 |
| Fashion SLM(패션 특화 소형 언어 모델) | 패션을 추가 학습한 AI 두뇌 | 코디 판단·추천 및 Tool Calling 판단 |
| Router(라우터·도구 호출 연결/관리) | 교통정리 담당 | Qwen이 생성한 Tool Call을 검증하고 실제 Python Tool로 연결·실행 |
| Tool(도구) | Agent가 사용할 수 있는 기능 | 사용자 정보·옷장·날씨·일정 조회 |
| Tool Calling(도구 호출) | 실제로 Tool을 사용하는 과정 | 필요한 Tool과 Argument를 결정하고 호출 |
| Context(모델 참고정보) | 모델에게 주는 참고자료 묶음 | 사용자 요청, Tool 결과, 계절·TPO 등의 정보를 정리 |
| Validator(검증 로직) | 결과 검사 로직 | 옷장 준수 여부와 JSON 형식을 검증 |
| JSON(구조화 데이터 형식) | 프로그램이 읽기 쉬운 데이터 형식 | 최종 3 LOOK 결과를 고정된 구조로 전달 |

---

## 4. 팀 구성 및 담당 역할

### 4.1 팀원별 역할

| 팀원 | 담당 |
|---|---|
| 김진호 | AI/ML(인공지능/머신러닝) 및 학습 데이터 |
| 곽준오 | Backend(백엔드) 및 AI Agent(인공지능 에이전트) 연동 |
| 김서진 | DB(데이터베이스)·외부 API(프로그램 간 연동 방식) 및 테스트 |
| 김윤아 | Frontend(프론트엔드) 및 UI/UX(사용자 인터페이스/사용자 경험) |

AI Agent 핵심 설계와 검증은 4명 모두가 공동으로 참여한다.

공동 참여 항목:
- Agent 구조 설계
- Tool Calling 구조
- 학습 데이터 기준 설계
- Gold Data(고품질 기준 정답 데이터) 작성
- HITL(사람 참여형 검증) 검증
- Agent Use Case(에이전트 사용 시나리오) 확인
- Agent 결과 검증
- 통합 테스트
- 최종 시연 및 발표

---

### 4.2 WBS(작업 분해 구조) 역할분류

| 역할분류 | 주요 업무 |
|---|---|
| 공통 | 기획, 기능 통합, 배포, 발표 등 팀 공동 작업 |
| AI/ML(인공지능/머신러닝) | Qwen3-4B, 학습 데이터, QLoRA, 모델 관련 작업 |
| BE/Agent(백엔드/에이전트) | FastAPI Backend, Router, Tool Calling, Validator, Agent 연동 |
| FE(프론트엔드) | JavaScript + HTML + CSS 기반 Frontend 및 Figma UI/UX |
| DB/API(데이터베이스/API) | PostgreSQL, Kakao Local, 기상청, Google Calendar API(Read Only) |
| TEST(테스트) | Tool 단위 테스트, 통합 테스트, Agent 성능 평가, 예외 상황 검증 |

---

## 5. 최종 기술 스택

### Design / UI·UX(디자인 / 사용자 인터페이스·사용자 경험)
- Figma
- Wireframe(화면 구조 설계도)
- UI Prototype(UI 시제품)

### Frontend(프론트엔드)
- JavaScript
- HTML
- CSS
- Responsive Web(반응형 웹)

### Backend(백엔드)
- Python
- FastAPI
- Swagger 자동 API 문서

### Database(데이터베이스)
- PostgreSQL

### AI / ML(인공지능 / 머신러닝)
- Main Base Model(주 기본 모델): **Qwen3-4B**
- Alternative / Comparison Candidate(대안 / 비교 후보): **Gemma 계열**
- Fine-Tuning(파인튜닝): **QLoRA 4bit**
- Training(학습): **Google Colab Pro**
- Inference(추론): **8bit 우선 적용**
- 필요 시 4bit 추론과 비교

### External API(외부 API)
- Kakao Local API
- 기상청 API
- Google Calendar API (Read Only, 읽기 전용)
- Web Geolocation(웹 위치정보 기능)

### Agent(에이전트)
- 직접 구현한 Router
- Qwen Tool Calling
- 고정 JSON Output(고정 JSON 출력)
- Wardrobe Validator
- JSON Validator

---

## 6. Base SLM(기본 소형 언어 모델)

### 6.1 Main Model(주 모델)
**Qwen3-4B**

선정 이유:
- 4B급 경량 모델
- 한국어 처리 가능
- Tool Calling 활용 가능
- Agent 구조에 적합
- QLoRA 파인튜닝 가능
- 로컬 및 자체 환경 추론 가능성
- 프로젝트 규모 대비 성능/자원 균형

### 6.2 Gemma
Gemma 계열은 Main Model(주 모델)이 아니라 예비·비교 후보로 유지한다.

---

## 7. 학습 및 추론 방식

### 7.1 Training(학습)
**QLoRA 4bit**

정확한 의미는 **Qwen3-4B를 패션 추천 데이터와 Tool Calling 데이터를 이용해 QLoRA 4bit 방식으로 Fine-Tuning한다**는 것이다.

```text
Qwen3-4B
  ↓
패션 추천 데이터 + Tool Calling 데이터 준비
  ↓
QLoRA 4bit 방식으로 Fine-Tuning(파인튜닝)
  ↓
Fine-Tuned Qwen3-4B
  ↓
Fashion SLM
```

학습 목적은 크게 2가지다.

1. **패션 추천 능력 학습**
   - 계절·날씨·TPO·스타일·색상·핏·사용자 취향을 고려한 코디 추천
   - LOOK 1·2는 취향 최적, LOOK 3은 새로운 스타일로 구성
   - 추천 이유를 프로젝트가 원하는 형식으로 생성

2. **Tool Calling 능력 학습**
   - 어떤 사용자 요청에서 어떤 Tool이 필요한지 판단
   - Tool에 어떤 Argument를 넣어야 하는지 판단
   - 예: `내일 전주 날씨에 맞게 추천해줘` → `get_weather(place="전주", date="내일")`

> **Tool Calling Data와 Tool Calling은 다르다.**  
> Tool Calling Data는 Fine-Tuning에 사용하는 **학습자료**이고, Tool Calling은 실제 서비스 실행 중 Agent가 **실제로 Tool을 선택·호출하는 행동**이다.

### 7.2 학습 환경
**Google Colab Pro**

### 7.3 Inference(추론)
우선 **8bit Inference**를 적용한다.

확인 항목:
- 응답 속도
- 메모리 사용량
- 안정성
- 패션 추천 품질

필요 시 4bit 추론과 비교한다.

### 7.4 최종 Inference(추론) 환경
아직 확정하지 않는다.

후보:
- 팀원 Mac 로컬
- 자체 서버
- GPU Cloud(GPU 클라우드)

---

## 8. Agent Framework(에이전트 프레임워크)

별도의 LangGraph 등 Agent Framework(에이전트 프레임워크)는 초기 구현에 사용하지 않는다.

최종 구조:
**Qwen3-4B + 직접 Router + Tool Calling**

```text
User Request
  ↓
FastAPI
  ↓
Qwen3-4B
  ↓
Tool Call 생성
  ↓
Router
  ↓
Python Tool 실행
  ↓
Tool Result
  ↓
Qwen3-4B
  ↓
최종 3 LOOK JSON
```

Router 역할:
- 요청된 Tool 허용 여부 확인
- Tool Argument(도구 입력값) 검증
- 실제 Python 함수 실행
- Tool 결과 반환
- 예외 처리

### 8.1 실제 Agent 실행 흐름을 쉽게 보면

예시 요청:

> "내일 저녁 전주 한옥마을에서 데이트하는데 내 옷으로 깔끔하게 입고 싶어."

```text
1. 사용자 요청
   ↓
2. Fashion SLM / Agent가 요청 해석
   - 날짜: 내일
   - 장소: 전주 한옥마을
   - TPO: 데이트
   - 분위기: 깔끔
   - 내 옷 사용: Yes
   ↓
3. 필요한 Tool 판단 및 Tool Call 생성
   - get_user_context()
   - get_wardrobe()
   - get_weather()
   ↓
4. Router가 Tool Call과 Argument 검증
   ↓
5. 실제 Python Tool 실행
   ↓
6. Tool Result(도구 실행 결과) 수집
   - 사용자 취향
   - 실제 옷장
   - 실제 날씨
   ↓
7. 사용자 요청 + Tool Result + 추가 분석 정보를 Context로 구성
   ↓
8. Fashion SLM에 Context 전달
   ↓
9. 3 LOOK 생성
   ↓
10. 고정 JSON 형식으로 출력
   ↓
11. Wardrobe Validator / JSON Validator 검증
   ↓
12. Frontend에 최종 결과 전달
```

쉽게 말하면 **Qwen/Fashion SLM이 어떤 Tool이 필요한지 판단하고 Tool Call을 만들고, Router는 그 호출이 올바른지 확인한 뒤 실제 Backend 함수로 연결하는 역할**을 한다.

### 8.2 Context(모델 참고정보)란?

Context는 특정 프로그램 이름이 아니라 **Fashion SLM이 현재 답변을 만들 때 참고하도록 전달하는 정보 묶음**이다.

```text
Context
=
사용자 원래 요청
+ Tool 결과
+ 계절 계산 결과
+ 날짜·시간·장소·TPO·분위기 등의 분석 정보
```

예:

```text
사용자 요청:
내일 전주에서 데이트하는데 내 옷으로 깔끔하게 입고 싶어.

사용자 취향:
미니멀 / 검정·흰색 선호 / 오버핏 선호

실제 옷장:
item_id 101 검정 셔츠
item_id 102 청바지
item_id 103 흰 운동화

날씨:
17℃ / 흐림 / 강수확률 20%

계절:
가을

상황:
저녁 데이트 / 깔끔한 분위기
```

따라서 Context를 단순하게 이해하면 **Tool에서 가져온 결과를 포함하여, 모델이 추천할 때 필요한 참고자료를 한 번에 정리한 것**이다.

---

## 9. Agent Tool 최종 구성

Agent Tool은 총 **4개**로 확정한다.

### 9.1 `get_user_context()`
가져오는 정보:
- 사용자 Profile(프로필)
- 직접 설정한 Preference(선호 정보)
- 좋아요/싫어요/저장 기반 개인화 요약

### 9.2 `get_wardrobe()`
사용자의 실제 옷장 데이터를 가져온다.

필드:
```text
item_id
category
type
color
fit
season
image
```

### 9.3 `get_weather()`
입력:
```text
place
date
time
```

내부 처리:
```text
장소명
  ↓
Kakao Local API
  ↓
위도 / 경도
  ↓
기상청 API
  ↓
기온 / 강수 / 풍속 / 습도 / 하늘 상태
```

### 9.4 `get_calendar_events()`
Google Calendar에서 지정 날짜의 일정을 Read Only(읽기 전용) 방식으로 조회한다.

가져오는 정보:
- 일정 시간
- 일정 제목
- 장소
- 필요 시 관련 설명

---

## 10. Agent 내부 Helper(보조 함수)

### `derive_season()`
날짜를 기준으로 봄/여름/가을/겨울을 판단한다.

### Wardrobe Validator
내 옷 기반 추천에서 Agent가 추천한 `item_id`가 실제 사용자의 옷장에 존재하는지 검증한다.

- 별도의 외부 AI나 독립 프로그램이 아니라 **FastAPI Backend에서 우리가 직접 구현하는 검증 코드/로직**이다.
- 예: 사용자 옷장에는 `101`, `102`, `103`만 있는데 Agent가 `item_id=999`를 추천하면 검증 실패로 처리한다.

### JSON Validator
Agent 결과가 정의된 JSON 구조를 따르는지 검증한다.

- 이것도 별도의 외부 프로그램이 아니라 **Backend에서 직접 구현하는 검증 코드/로직**이다.
- JSON 문법이 정상인지, 필수 필드가 존재하는지, 각 필드의 자료형과 구조가 정해진 형식에 맞는지 확인한다.

### 날짜/시간 해석
`오늘`, `내일`, `이번 주말`, `저녁`, `오후 7시` 등의 표현을 실제 날짜/시간으로 해석한다.

---

## 11. Tool 호출 기준

| 사용자 요청 | 호출 |
|---|---|
| 일반 개인화 추천 | get_user_context() |
| “내 옷으로 추천” | get_user_context() + get_wardrobe() |
| 특정 목적지·날짜 기반 추천 | get_user_context() + get_weather() |
| “오늘 일정 보고 추천” | get_user_context() + get_calendar_events() |
| 일정 장소의 날씨가 필요한 경우 | get_calendar_events() → get_weather() |
| “내 일정 보고 내 옷으로 추천” | get_user_context() + get_calendar_events() + get_wardrobe() + 필요 시 get_weather() |

---

## 12. 최종 핵심 기능 7개

### 12.1 프로필·취향 기반 개인화

#### 필수 입력
- 좋아하는 스타일
- 좋아하는 색
- 싫어하는 색 (`없음` 가능)
- 선호 핏

#### 선택 입력
- 성별
- 연령대
- 키
- 체형

사이즈 정보는 제외한다.

### 12.2 나만의 옷장
필드:
```text
category
type
color
fit
season
image(optional)
```

사진은 선택사항이다.

### 12.3 내 옷 기반 코디 추천
실제 Wardrobe(사용자의 옷장 데이터) 데이터만 사용한다.

내 옷 기반 추천에 포함되는 각 의류 항목은 실제 사용자의 WardrobeItem에 해당하는 item_id를 반드시 반환하고, Wardrobe Validator로 검증한다.

### 12.4 목적지·계절·날씨 기반 추천

Location(위치):
- Kakao Local API

Weather(날씨):
- 기상청 API
- 기온
- 강수확률 / 강수형태
- 풍속
- 습도
- 하늘상태

Season(계절):
- `derive_season()`으로 날짜 기준 계산
- 계절 + 실제 날씨를 함께 반영

현재 위치:
- 사용자 동의 시 Web Geolocation(웹 위치정보 기능)
- 정확한 GPS는 AI에 직접 전달하지 않음

장소 모호성:
- Tool이 모호함을 감지
- Agent가 사용자에게 재질문

Weather API(날씨 API) 실패:
- 실패 안내
- 날씨를 임의 생성하지 않음
- 나머지 조건으로 추천 지속

### 12.5 Google Calendar 일정 기반 추천
**Google Calendar API Read Only(읽기 전용)**

하지 않는 것:
- 일정 생성 ❌
- 일정 수정 ❌
- 일정 삭제 ❌

사용자는 Google Calendar에서 일정을 직접 관리하고, 서비스는 읽어서 추천에 활용한다.

### 12.6 상황 기반 3종 코디 추천

- LOOK 1: 사용자 취향 최적
- LOOK 2: 사용자 취향 최적 + 다른 조합
- LOOK 3: 새로운 스타일

분석 요소:
- 날짜
- 시간
- 장소
- TPO(Time·Place·Occasion, 시간·장소·상황)
- 분위기
- 원하는 스타일
- 내 옷 사용 여부

### 12.7 피드백·저장 기반 개인화

Feedback(피드백):
- 좋아요
- 싫어요
- 싫어요 이유
- 저장

싫어요 이유 예:
- 색상이 별로예요
- 핏이 별로예요
- 제 스타일이 아니에요
- 너무 꾸민 느낌이에요
- 너무 평범해요

SAVE는 강한 긍정 신호로 활용한다.

---

## 13. 개인화 계산 방식

스타일·핏·색상 등에 간단한 가중치를 부여한다.

개념:
```text
LIKE       → 긍정
SAVE       → 강한 긍정
DISLIKE    → 부정
```

정확한 숫자는 개발 과정에서 조정 가능하다.

---

## 14. Agent Memory(에이전트 개인화 기억 정보)

전체 대화 로그를 매번 Agent에 넣지 않는다.

대신 **요약된 선호 정보만 Context로 전달**한다.

예:
```json
{
  "preferred_styles": ["minimal", "casual"],
  "preferred_fit": "wide",
  "preferred_colors": ["navy", "ivory"],
  "disliked_colors": ["red"]
}
```

---

## 15. 추천 결과 표현 방식

### 일반 추천
**상세 텍스트 중심**

이미지 생성 모델을 사용하지 않는다.

예:
```text
상의: 하늘색 오버핏 체크 셔츠
하의: 연청 와이드핏 데님 팬츠
신발: 화이트 로우탑 스니커즈
아우터: 얇은 네이비 코튼 블루종
액세서리: 실버 메탈 시계
```

### 내 옷 추천
사진이 있으면:
- 사용자 실제 사진 + 텍스트

사진이 없으면:
- 텍스트만 표시

---

## 16. 3 LOOK(코디안) JSON

Agent 최종 출력은 JSON으로 고정한다.

여기서 **고정 JSON 출력**이란 Tool의 결과 자체를 의미하는 것이 아니라, 최종적으로 Fashion SLM/Fashion Agent가 생성한 **3 LOOK(코디안) 추천 결과를 Frontend가 처리하기 쉬운 일정한 JSON 구조로 받는 것**을 의미한다.

Tool 내부 결과도 필요에 따라 JSON 형태로 주고받을 수 있지만, 본 프로젝트에서 말하는 **고정 JSON Output(고정 JSON 출력)의 핵심은 최종 3 LOOK 결과 형식**이다.

```text
Tool Result
  ↓
Context 구성
  ↓
Fashion SLM
  ↓
3 LOOK 생성
  ↓
고정 JSON 형식으로 출력
  ↓
JSON Validator
  ↓
Frontend(프론트엔드)
```

예:
```json
{
  "look": 1,
  "concept": "미니멀 캐주얼",
  "top": {
    "type": "체크 셔츠",
    "color": "하늘색",
    "fit": "오버핏",
    "detail": "얇은 면 소재"
  },
  "bottom": {
    "type": "데님 팬츠",
    "color": "연청",
    "fit": "와이드핏"
  },
  "shoes": {
    "type": "로우탑 스니커즈",
    "color": "화이트"
  },
  "outer": "얇은 네이비 코튼 블루종",
  "accessory": "실버 메탈 시계",
  "reason": "..."
}
```

내 옷 추천에서는 실제 `item_id`를 포함하도록 한다.

---

## 17. 저장한 코디

전체 추천 히스토리는 제공하지 않는다.

사용자가 직접 SAVE한 코디만 별도 화면에서 확인한다.

- 일반 추천 저장: 텍스트 중심
- 내 옷 추천 저장: 사진이 있으면 실제 사진 + 텍스트, 없으면 텍스트

---

## 18. 로그인

### 자체 Login(로그인)
**이메일 + 비밀번호**

실명은 필요하지 않다.

비밀번호는 평문 저장하지 않는다.

### 제외
- Google Login(구글 로그인)
- Kakao Login(카카오 로그인)
- Social Login(소셜 로그인)
- 이메일 인증

---

## 19. Google Calendar 인증

자체 로그인과 Google Calendar 연결은 별개다.

```text
이메일/비밀번호 로그인
  ↓
서비스 이용
  ↓
Google Calendar 연결 버튼
  ↓
Google OAuth(외부 계정 권한 인증)
  ↓
Calendar Read Only(캘린더 읽기 전용)
```

---

## 20. PostgreSQL 주요 데이터 영역

- User
- UserProfile
- UserPreference
- WardrobeItem
- Feedback
- SavedOutfit
- Google Calendar 연결정보

실제 Google Calendar Event(구글 캘린더 일정)는 DB에 복제하지 않는다.

OAuth Token(인증 토큰) 등 필요한 연결정보는 안전하게 저장한다.

---

## 21. 이미지 관리

Wardrobe 이미지 등록은 선택사항이다.

검증:
- 허용 파일 확장자
- 최대 파일 크기

정확한 최대 용량은 구현 시 결정한다.

사용자는 업로드한 사진을 삭제할 수 있다.

---

## 22. 개인정보 처리 원칙

**개인화는 강화하되 개인정보 수집과 활용은 최소화한다.**

AI에 직접 전달하지 않는 정보:
- 비밀번호
- 인증정보
- OAuth Token(인증 토큰)
- 정확한 GPS
- 추천과 무관한 개인정보

정확한 GPS 좌표는 Backend에서 처리하고, AI에는 지역명·날씨 등 필요한 정보만 전달한다.

---

## 23. 데이터 삭제 / 회원 탈퇴

### 내 데이터 삭제
계정은 유지한다.

삭제 대상 예:
- Profile
- Preference
- Wardrobe
- Feedback
- Saved Outfit
- 개인화 요약 데이터

### 회원 탈퇴
**회원 탈퇴 = 계정 삭제 + 관련 사용자 데이터 전체 삭제**

삭제 대상:
- User
- Profile
- Preference
- Wardrobe
- Feedback
- Saved Outfit
- Google OAuth(외부 계정 권한 인증) 연결정보

별도의 `계정 삭제` 버튼은 만들지 않는다.

---

## 24. 패션 학습 Data(데이터)

최종 학습 데이터는 내용 기준으로 크게 **Fashion Recommendation Data(패션 추천 학습 데이터)**와 **Tool Calling Data(도구 호출 학습 데이터)**의 두 축으로 구성한다.

### 24.1 Fashion Recommendation Data(패션 추천 학습 데이터)
패션 추천 자체를 학습한다.

학습 요소 예:
- 계절
- 기온·강수 등 날씨
- TPO(Time·Place·Occasion, 시간·장소·상황)
- 사용자 선호 스타일
- 색상
- 핏
- 장소·시간·분위기
- 3 LOOK 구성
- 추천 이유

예:

```text
입력:
가을 / 16℃ / 저녁 데이트 / 미니멀 / 검정·흰색 선호

출력:
LOOK 1 ...
LOOK 2 ...
LOOK 3 ...
추천 이유 ...
```

### 24.2 Tool Calling Data(도구 호출 학습 데이터)
어떤 상황에서 어떤 Tool을 사용해야 하는지와 Tool Argument(도구 입력값)를 학습/평가한다.

예:

```text
사용자:
"내일 전주 날씨에 맞게 코디 추천해줘."

정답 예:
get_weather(place="전주", date="내일")
```

또는:

```text
사용자:
"내일 일정 보고 내 옷으로 추천해줘."

필요 Tool:
get_user_context()
get_calendar_events()
get_wardrobe()
```

### 24.3 Tool Calling Data(도구 호출 학습 데이터)와 실제 Tool Calling(도구 호출)의 차이

```text
Tool Calling Data
= Fine-Tuning 때 사용하는 'Tool 사용법 학습자료'

Tool Calling
= 실제 서비스 실행 중 Agent가 Tool을 선택하고 호출하는 행동
```

---

## 25. 데이터 출처

### 공개 데이터
- Hugging Face Datasets
- AI Hub
- 기타 라이선스 사용 가능한 공개 패션 데이터

검토 항목:
- 라이선스
- 품질
- 프로젝트 적합성

무단 쇼핑몰 데이터 대량 수집은 하지 않는다.

### Gold Data(고품질 기준 정답 데이터)
팀 직접 작성: **50~100개**

Gold Data는 팀원이 직접 작성하고 검토하는 **고품질 기준 정답 데이터**다.  
Fashion Recommendation Data와 Tool Calling Data 모두 Gold Data로 작성할 수 있다.

예:
- 특정 계절·날씨·TPO·취향에 적합한 3 LOOK 모범답안
- 특정 사용자 요청에서 호출해야 할 Tool과 Argument의 모범답안

### Synthetic Data(합성 데이터)
Gold Data 기반: **500~1,000개**

Synthetic Data는 Gold Data를 기준으로 계절·날씨·TPO·스타일·색상·핏·Tool Calling 상황을 다양화하여 확장한 **합성 데이터**다.

예:

```text
Gold 예시:
가을 / 데이트 / 미니멀

Synthetic 확장:
여름 / 여행 / 스트릿
겨울 / 출근 / 캐주얼
봄 / 소개팅 / 댄디
가을 / 비 / 학교 / 미니멀
```

초기 예:
```text
Gold 100 + Synthetic 500 = 총 600
```

### 25.1 최종 Dataset(데이터셋)은 무엇으로 구성되는가?

최종 Dataset(데이터셋)의 **출처 기준** 구성은 다음과 같다.

```text
활용 가능한 공개 패션 데이터
+
팀원이 직접 작성한 Gold Data
+
Gold Data를 기반으로 생성하고 검증한 Synthetic Data
=
최종 Dataset
```

단, 공개 데이터는 모두 그대로 사용하는 것이 아니라 **라이선스·품질·프로젝트 적합성을 확인한 뒤 필요한 데이터만 선별·가공하여 활용**한다.

최종 Dataset(데이터셋)의 **내용 기준** 구성은 다음과 같다.

```text
최종 Dataset
├─ Fashion Recommendation Data
└─ Tool Calling Data
```

---

## 26. Human-in-the-Loop(사람 참여형 검증)

**HITL(Human-in-the-Loop, 사람 참여형 검증)**은 데이터 종류가 아니라 **AI 등이 생성한 Synthetic Data의 품질을 사람이 직접 확인하고 수정·삭제·승인하는 검증 과정**이다.

합성 데이터 중:
- 최소 20% 교차 검증
- 일정이 허용되면 30% 이상

검증 항목:
- TPO(Time·Place·Occasion, 시간·장소·상황)
- 계절
- 날씨
- 스타일
- 색상
- 핏
- Tool(도구) 호출
- JSON 형태
- 잘못된 추천
- 비현실적 조합

---

## 27. Dataset(데이터셋) 분할

공개 데이터·Gold Data·검증된 Synthetic Data를 정제하여 최종 Dataset을 만든 뒤 다음 비율로 분할한다.

```text
Train      80%
Validation 10%
Test       10%
```

역할:

| 구분 | 역할 |
|---|---|
| Train(학습용 데이터) 80% | Qwen3-4B Fine-Tuning에 실제로 사용 |
| Validation(학습 중 검증용 데이터) 10% | 학습 중 모델이 잘 학습되고 있는지 확인하고 설정을 조정하는 데 사용 |
| Test(최종 평가용 데이터) 10% | 학습 완료 후 최종 성능 평가에 사용 |

**Test Data(최종 평가용 데이터)는 Fine-Tuning(파인튜닝)에 사용하지 않는다.** 학습에 사용한 데이터를 다시 시험 문제로 쓰면 실제 성능을 공정하게 확인하기 어렵기 때문이다.

전체 데이터 흐름:

```text
공개 패션 Dataset 조사·선별
        +
Gold Data 50~100개 직접 작성
        ↓
Synthetic Data 500~1,000개 생성
        ↓
HITL 검증·정제
        ↓
최종 Dataset
        ↓
Train 80% / Validation 10% / Test 10%
        ↓
Train Data로 QLoRA Fine-Tuning(파인튜닝)
+ Validation Data로 학습 중 성능 확인
        ↓
Fashion SLM
        ↓
Test Data로 최종 평가
```

---

## 28. Agent(에이전트) 성능 평가

### A. Base Model(기본 모델)
Qwen3-4B

### B. Base Model + Agent(기본 모델 + 에이전트)
Qwen3-4B + Router + Tool Calling + Context + Validator

### C. Fine-Tuned Fashion Agent(파인튜닝된 패션 에이전트)
Fine-Tuned Qwen3-4B + Router + Tool Calling + Context + Validator

쉽게 구분하면:

```text
A = 원본 Qwen3-4B만 사용

B = 원본 Qwen3-4B
    + Agent 구조

C = 패션 추천·Tool Calling 데이터로 Fine-Tuning한 Qwen3-4B
    + B와 동일한 Agent 구조
```

따라서 B와 C의 외부 Agent 구조는 동일하고, **내부 두뇌인 Qwen3-4B가 Fine-Tuning되었는지가 핵심 차이**다.

### 평가 목적
- A → B: Agent 구조의 효과
- B → C: Fine-Tuning의 추가 효과

### 테스트 질의
- 최소 50개
- 목표 100개
- 가능하면 100개 이상

### 평가 항목
A:
- 패션/TPO 적합성
- 응답 품질

B/C:
- Tool(도구) 선택 정확도
- Tool Argument(도구 입력값) 정확도
- Wardrobe(사용자 옷장) 준수율
- 날씨 반영률
- 일정 반영률
- 패션/TPO 적합성 및 응답 품질

---

## 29. Git 협업 전략

팀원 모두가 하나의 **공유 Repository(코드 저장소)**를 사용한다.

```text
main
develop
feature/*
```

- main(메인 브랜치): 안정된 최종 코드
- develop(개발 브랜치): 통합 개발 코드
- feature/*(기능 브랜치): 기능별 작업

흐름:
```text
develop
  ↓
feature/* 분기
  ↓
기능별 개발
  ↓
develop에 병합
  ↓
통합 확인·안정화
  ↓
main 반영
```

별도의 Pull Request(코드 변경 검토 요청) 절차는 두지 않고, 공유 Repository에서 정한 Branch(브랜치) 규칙에 따라 협업한다.

---

## 30. WBS 기준 개발 흐름

별도의 요구사항 명세서, Use Case 문서, ERD 산출물 제작 단계는 두지 않는다. 세부 일정과 담당자는 Google Sheets WBS를 기준으로 관리하며, 본 문서에서는 개발 단계의 구조를 정리한다.

```text
기획 및 설계
- 프로젝트 방향·차별성 확정
- 핵심 기능 7개 확정
- Agent 구조·4개 Tool 설계
- Figma 기반 UI/UX 설계
- 주요 화면 구성·사용자 흐름 확정
  ↓
환경·DB 구축
- Git·GitHub 협업 환경
- FastAPI Backend 초기 구성
- JavaScript + HTML + CSS Frontend 초기 구성
- PostgreSQL 테이블 구축
- 외부 API·브라우저 기능 연동 준비
  ↓
AI 데이터·모델 개발
- 공개 패션 데이터 조사
- Gold / Synthetic Data 작성
- HITL(사람 참여형 검증) 검증·정제
- Qwen3-4B Base Model 확인
- QLoRA Fine-Tuning(파인튜닝)
  ↓
Backend·Agent / Frontend 구현
- 4개 Tool 구현 및 Agent Core 연동
- 인증·프로필·옷장·피드백 API
- Figma 설계안을 반영한 Frontend 구현
  ↓
핵심 기능 통합
  ↓
Tool·단위 테스트 / Agent 성능 평가 / 통합 테스트
  ↓
최종 보고서·PPT·Q&A
  ↓
배포·시연 준비
```

### 역할별 주요 개발 축

김진호:
- AI/ML 및 학습 데이터 중심
- Frontend 및 AI 결과 형식 연동 지원

곽준오:
- Backend 및 AI Agent 연동 중심
- FastAPI, 4개 Tool 연동, Router, Validator 구현

김서진:
- PostgreSQL·외부 API 및 테스트 중심
- Kakao Local / 기상청 / Google Calendar 연동

김윤아:
- Figma UI/UX 및 Frontend 중심
- JavaScript + HTML + CSS 기반 반응형 UI 구현

---

## 31. 대표 시연 시나리오

사용자:
> "내일 저녁 전주 한옥마을에서 데이트가 있는데 내 옷으로 깔끔하게 입고 싶어."

### 요청 분석
```text
date = 내일
time = 저녁
place = 전주 한옥마을
situation = 데이트
mood = 깔끔
use_wardrobe = true
```

### 계절 계산
`derive_season(date)`

### Tool 선택
```text
get_user_context()
get_wardrobe()
get_weather()
```

### Location / Weather(날씨)
```text
전주 한옥마을
  ↓
Kakao Local
  ↓
좌표
  ↓
기상청
  ↓
실제 날씨
```

### Context(모델 참고정보) 통합
- 사용자 취향
- 색상
- 핏
- 실제 Wardrobe
- 계절
- 실제 날씨
- 이전 Feedback

### 3 LOOK
- LOOK 1: 취향 최적
- LOOK 2: 취향 최적 대안
- LOOK 3: 새로운 스타일

### Validation(검증)
- Wardrobe Validator
- JSON Validator

### Feedback(피드백)
- 좋아요
- 싫어요 + 이유
- 저장

Feedback(피드백)은 다음 추천의 가중치 Context(모델 참고정보)에 반영한다.

---

## 32. 기존 서비스 대비 기술적 차별성

단순 기능 유무보다 기술적 구현 방식에 차별성을 둔다.

핵심:
1. Qwen3-4B 직접 선정
2. 패션 데이터 QLoRA Fine-Tuning(파인튜닝)
3. Router + Tool Calling Agent 직접 구현
4. 요청에 따른 Tool 선택
5. Wardrobe Validator
6. JSON Validator
7. Kakao Local + 기상청 + 계절
8. Google Calendar Read Only(캘린더 읽기 전용)
9. Feedback 가중치 기반 Preference Memory
10. 정확한 GPS는 Backend에서 처리하고 AI에는 직접 전달하지 않음
11. Base → Base+Agent → Fine-Tuned Agent 3단계 정량 평가

---

## 33. 이번 프로젝트에서 제외하는 기능

- AI 이미지 생성
- 현재 착장 사진 AI 분석
- 가상 피팅
- 쇼핑몰 상품 연동
- 가격 비교
- 추천 전체 히스토리
- 스타일 리포트 시각화
- 자체 캘린더
- Google Calendar 일정 생성/수정/삭제
- Google/Kakao 간편 로그인
- 이메일 인증
- 실시간 알림
- 관리자 페이지
- 다크모드
- 사용자별 SLM 재학습
- 초기 LangGraph 도입

---

## 34. 추후 결정 항목

- Gemma 정확한 비교 모델
- 최종 추론 환경
- 최종 배포 환경
- UI 디자인 톤
- 서비스 정식 이름
- 로고
- 이미지 최대 업로드 용량

---

## 35. 최종 요약(영어 용어 한국어 뜻 병기)

```text
Base SLM(기본 소형 언어 모델)
→ Qwen3-4B

Alternative(대안 후보)
→ Gemma

Fine-Tuning(파인튜닝)
→ QLoRA 4bit

Training(학습)
→ Colab Pro

Inference(추론)
→ 8bit 우선

Agent(에이전트)
→ 직접 Router(라우터) + Tool Calling(도구 호출)

Tools(도구)
→ get_user_context()
→ get_wardrobe()
→ get_weather()
→ get_calendar_events()

Helpers(보조 함수)
→ derive_season()
→ Wardrobe Validator
→ JSON Validator

Backend(백엔드)
→ Python + FastAPI

Design / UI·UX(디자인 / 사용자 인터페이스·사용자 경험)
→ Figma

Frontend(프론트엔드)
→ JavaScript + HTML + CSS

DB(데이터베이스)
→ PostgreSQL

Location(위치)
→ Kakao Local

Weather(날씨)
→ 기상청

Calendar(캘린더)
→ Google Calendar Read Only(캘린더 읽기 전용)

Current Location(현재 위치)
→ Web Geolocation(웹 위치정보 기능) + 사용자 동의

Recommendation(추천)
→ LOOK 1 취향 최적
→ LOOK 2 취향 최적 대안
→ LOOK 3 새로운 스타일

일반 추천
→ 상세 텍스트 중심

내 옷 추천
→ 사진이 있으면 사용자 업로드 사진+텍스트, 없으면 텍스트만 표시.

Personalization(개인화)
→ LIKE / DISLIKE + 이유 / SAVE
→ 스타일·핏·색상 가중치
→ 요약 Context(모델 참고정보)

Evaluation(평가)
→ Base Model(기본 모델)
→ Base Model + Agent(기본 모델 + 에이전트)
→ Fine-Tuned Fashion Agent(파인튜닝된 패션 에이전트)
```

---

## 36. 교수님께 한 문장으로 설명

> 저희 프로젝트는 Qwen3-4B를 패션 데이터로 QLoRA 파인튜닝한 Fashion SLM(패션 특화 소형 언어 모델)을 기반으로 Router(라우터) + Tool Calling(도구 호출) 구조의 AI Agent를 직접 구현하고, 사용자의 요청에 따라 프로필·취향, 실제 옷장, 목적지의 기상청 날씨, Google Calendar 일정 중 필요한 정보를 선택적으로 조회하여 취향 최적 코디 2개와 새로운 스타일 코디 1개를 추천하며, Wardrobe Validator(옷장 데이터 검증 로직)와 JSON Validator(JSON 형식 검증 로직)로 결과를 검증하고 Base Model(기본 모델) → Base Model + Agent(기본 모델 + 에이전트) → Fine-Tuned Fashion Agent(파인튜닝된 패션 에이전트)의 3단계 성능평가를 통해 기술적 효과를 검증하는 반응형 웹 서비스입니다.
