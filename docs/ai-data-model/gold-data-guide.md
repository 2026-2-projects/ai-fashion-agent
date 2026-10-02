  # 3.2 Gold Data 작성 가이드

## 1. 목적

본 문서는 AI 기반 개인 맞춤형 패션 에이전트의 Qwen3-4B Fine-Tuning에 사용할 Gold Data의 작성 규칙과 JSON 구조를 정의한다.

Gold Data는 팀원이 직접 작성하고 검토하는 고품질 기준 데이터이며, 이후 Synthetic Data 생성의 기준으로 사용한다.

본 프로젝트의 Gold Data는 크게 두 종류로 구성한다.

```text
Gold Data
├── Fashion Recommendation Data
└── Tool Calling Data
```

목표 수량은 총 80개로 설정한다.

```text
Fashion Recommendation Data : 50개
Tool Calling Data           : 30개
--------------------------------
Total                       : 80개
```

---

# 2. 기본 원칙

모든 Gold Data는 다음 규칙을 따른다.

1. Gold Data 원본은 여러 JSON 객체를 하나의 배열에 저장하는 JSON 형식을 사용한다.
2. 모든 데이터에는 고유한 ID를 부여한다.
3. 사용자의 자연어 요청은 실제 서비스에서 입력할 법한 자연스러운 한국어로 작성한다.
4. 사용자 요청의 계절, 날씨, TPO, 스타일, 색상, 핏 등을 다양하게 구성한다.
5. Tool Calling Data에서는 불필요한 Tool을 호출하지 않는다.
6. 존재하지 않는 Tool을 생성하지 않는다.
7. 내 옷 추천에서는 실제 Wardrobe Context에 존재하는 `item_id`만 사용한다.
8. LOOK은 항상 3개를 생성한다.
9. LOOK 1, LOOK 2, LOOK 3의 역할을 고정한다.
10. 데이터 작성 후 다른 팀원이 교차 검증한다.

---

# 3. 공통 ID 규칙

Fashion Recommendation Data:

```text
FR-001
FR-002
FR-003
...
```

Tool Calling Data:

```text
TC-001
TC-002
TC-003
...
```

ID는 중복될 수 없다.

---

# 4. 공통 정규화 규칙

내부 데이터에서는 가능한 한 일정한 값을 사용한다.

예:

```text
gender
male
female
null

age_group
10s
20s
30s
40s
50s
null

preferred_fit
slim
regular
wide
oversized

style
minimal
casual
street
classic
modern
clean
etc.

season
spring
summer
fall
winter
```

사용자에게 보여주는 최종 코디 설명은 자연스러운 한국어로 작성한다.

예:

```text
minimal
→ 미니멀

wide
→ 와이드핏
```

---

# 5. 상대 날짜 처리

사용자 요청에는 다음과 같은 상대적인 시간 표현이 존재할 수 있다.

```text
오늘
내일
모레
이번 주말
다음 주
```

Gold Data에서는 상대 날짜를 정확하게 해석할 수 있도록 `reference_datetime`을 함께 저장한다.

예:

```json
{
  "reference_datetime": "2026-10-02T18:00:00+09:00",
  "user_request": "내일 전주에서 데이트하는데 뭐 입지?"
}
```

이 경우 `내일`은 다음 날짜를 의미한다.

```text
2026-10-03
```

Tool Argument에는 가능하면 해석된 실제 날짜를 사용한다.

---

# 6. Fashion Recommendation Data

Fashion Recommendation Data는 사용자 요청과 Context가 주어졌을 때 적절한 3개의 LOOK을 추천하는 방법을 학습하기 위한 데이터이다.

기본 구조는 다음과 같다.

```json
{
  "id": "FR-001",
  "type": "fashion_recommendation",

  "reference_datetime": "2026-10-02T18:00:00+09:00",

  "user_request": "내일 전주 한옥마을에서 저녁 데이트하는데 깔끔하게 입고 싶어",

  "context": {
    "profile": {},
    "preference": {},
    "weather": {},
    "schedule": {},
    "wardrobe": [],
    "use_wardrobe": false
  },

  "answer": {
    "looks": []
  }
}
```

---

# 7. Profile

Profile은 사용자 기본 정보이다.

모든 값은 선택사항이므로 정보가 없는 경우 `null`을 사용할 수 있다.

```json
{
  "gender": "male",
  "age_group": "20s",
  "height_cm": 175,
  "body_type": "normal"
}
```

예:

```json
{
  "gender": null,
  "age_group": "20s",
  "height_cm": null,
  "body_type": null
}
```

---

# 8. Preference

사용자의 패션 취향이다.

```json
{
  "preferred_styles": [
    "minimal",
    "casual"
  ],

  "preferred_colors": [
    "black",
    "white",
    "navy"
  ],

  "disliked_colors": [
    "red"
  ],

  "preferred_fit": "wide"
}
```

---

# 9. Weather

Weather Tool 또는 Context를 통해 제공되는 날씨 정보이다.

```json
{
  "temperature_c": 17,
  "precipitation_probability": 20,
  "precipitation_type": "none",
  "wind_mps": 2.1,
  "humidity_percent": 55,
  "sky": "cloudy"
}
```

모든 추천은 날씨와 크게 충돌하지 않아야 한다.

예:

```text
30°C
→ 두꺼운 니트 / 패딩 추천 X

비
→ 스웨이드 신발 우선 추천 X

5°C
→ 반팔 단독 추천 X
```

---

# 10. Schedule / TPO

사용자의 일정 정보이다.

```json
{
  "date": "2026-10-03",
  "time": "18:00",
  "place": "전주 한옥마을",
  "tpo": "date"
}
```

TPO 예시는 다음과 같다.

```text
school
date
meeting
interview
travel
festival
wedding
presentation
cafe
daily
etc.
```

---

# 11. LOOK 구성 규칙

모든 Fashion Recommendation Data는 정확히 3개의 LOOK을 제공한다.

역할은 고정한다.

```text
LOOK 1
role = preference_best

사용자의 취향을 가장 충실하게 반영한 코디


LOOK 2
role = preference_alternative

사용자의 취향을 유지하면서 다른 조합을 제공


LOOK 3
role = exploration

사용자가 평소 선호하는 스타일에서 조금 확장된 새로운 스타일
```

LOOK 3도 사용자의 싫어하는 색이나 명백한 제약을 무시해서는 안 된다.

---

# 12. LOOK JSON 구조

각 LOOK은 다음과 같은 구조를 사용한다.

```json
{
  "look_id": 1,
  "role": "preference_best",

  "style": "미니멀 캐주얼",

  "items": [
    {
      "slot": "top",
      "name": "화이트 셔츠",
      "item_id": null
    },
    {
      "slot": "bottom",
      "name": "베이지 와이드 슬랙스",
      "item_id": null
    },
    {
      "slot": "shoes",
      "name": "화이트 스니커즈",
      "item_id": null
    },
    {
      "slot": "outer",
      "name": "아이보리 가디건",
      "item_id": null
    }
  ],

  "reason": "사용자가 선호하는 미니멀 스타일과 와이드핏을 반영하고, 17도의 선선한 저녁 날씨를 고려해 가벼운 아우터를 추가했습니다."
}
```

필요하지 않은 아이템은 억지로 추가하지 않는다.

예:

```text
outer 필요 없음
→ items에서 outer를 생략
```

---

# 13. 일반 추천과 내 옷 추천의 차이

## 일반 추천

`use_wardrobe`가 `false`인 경우 실제 Wardrobe Item을 사용할 필요가 없다.

따라서:

```json
{
  "item_id": null
}
```

을 사용한다.

---

## 내 옷 추천

`use_wardrobe`가 `true`인 경우 반드시 Context의 Wardrobe에 존재하는 아이템을 사용해야 한다.

예:

```json
{
  "wardrobe": [
    {
      "item_id": 12,
      "category": "top",
      "item_type": "shirt",
      "color": "white",
      "fit": "oversized",
      "seasons": [
        "spring",
        "fall"
      ]
    },

    {
      "item_id": 24,
      "category": "bottom",
      "item_type": "denim",
      "color": "blue",
      "fit": "wide",
      "seasons": [
        "spring",
        "fall",
        "winter"
      ]
    }
  ],

  "use_wardrobe": true
}
```

추천 결과:

```json
{
  "slot": "top",
  "name": "화이트 셔츠",
  "item_id": 12
}
```

존재하지 않는 `item_id`를 생성해서는 안 된다.

예:

```text
Wardrobe
12
24
31

추천 결과
item_id = 999

→ 잘못된 데이터
```

이는 실제 서비스의 Wardrobe Validator에서도 검증한다.

---

# 14. Tool Calling Data

Tool Calling Data는 사용자 요청을 분석하여 필요한 Tool을 선택하는 방법을 학습하기 위한 데이터이다.

본 프로젝트에서 사용할 Tool은 다음 4개이다.

```text
get_user_context()
get_wardrobe()
get_weather()
get_calendar_events()
```

이 외의 Tool을 생성해서는 안 된다.

---

# 15. Tool Calling 기본 구조

Tool Calling Gold Data는 다음 형식을 사용한다.

```json
{
  "id": "TC-001",

  "type": "tool_calling",

  "reference_datetime": "2026-10-02T18:00:00+09:00",

  "user_request": "내일 일정에 맞게 날씨까지 보고 코디 추천해줘",

  "steps": [],

  "final_response": {}
}
```

---

# 16. Tool Call Step

Tool을 사용하는 경우 하나의 Step에 Tool Call과 Tool Result를 함께 저장한다.

```json
{
  "step": 1,

  "tool_call": {
    "name": "get_calendar_events",

    "arguments": {
      "date": "2026-10-03"
    }
  },

  "tool_result": {
    "events": [
      {
        "time": "18:00",
        "place": "전주 한옥마을",
        "summary": "데이트"
      }
    ]
  }
}
```

Tool Result를 기반으로 다음 Tool을 호출할 수도 있다.

---

# 17. Multi-Tool Calling

예:

```text
사용자
"내일 일정 보고 날씨까지 고려해서 추천해줘"

↓

get_calendar_events()

↓

일정 확인
18:00
전주 한옥마을
데이트

↓

get_weather()

↓

날씨 정보 확보

↓

Fashion Recommendation
```

Gold Data에서는 실제 Tool 실행 순서와 동일하게 Step을 작성한다.

---

# 18. Tool을 호출하지 않는 데이터

Tool Calling Data라고 해서 모든 데이터가 Tool을 호출하면 안 된다.

예:

```text
사용자:
"검정 셔츠랑 청바지 잘 어울려?"
```

이 요청은 다음 Tool이 필요하지 않다.

```text
get_weather() X
get_calendar_events() X
get_wardrobe() X
get_user_context() X
```

따라서:

```json
{
  "steps": []
}
```

형태의 데이터도 반드시 포함한다.

이를 통해 모델이 모든 요청에서 무조건 Tool을 호출하는 현상을 방지한다.

---

# 19. Tool 선택 기준

## get_user_context()

사용자의 기존 취향 또는 프로필을 실제 DB에서 가져와야 할 때 사용한다.

예:

```text
"내 취향에 맞게 추천해줘"

"평소 내가 좋아하는 스타일로 골라줘"
```

---

## get_wardrobe()

사용자의 실제 보유 의류가 필요한 경우 사용한다.

예:

```text
"내 옷으로 코디해줘"

"내 옷장에 있는 옷 중에서 골라줘"
```

---

## get_weather()

장소와 날짜의 실제 날씨가 필요한 경우 사용한다.

예:

```text
"내일 전주 날씨에 맞게 입고 싶어"

"오늘 서울에서 뭐 입을까?"
```

---

## get_calendar_events()

사용자의 Google Calendar 일정 정보가 필요한 경우 사용한다.

예:

```text
"내일 일정에 맞게 추천해줘"

"이번 주말 일정 보고 코디해줘"
```

---

# 20. Tool Calling 데이터 구성 목표

총 30개를 다음과 같이 분산한다.

| 유형 | 목표 개수 |
|---|---:|
| Tool 호출 없음 | 4 |
| get_user_context | 4 |
| get_wardrobe | 4 |
| get_weather | 4 |
| get_calendar_events | 4 |
| Calendar → Weather | 4 |
| UserContext + Weather | 2 |
| Wardrobe + Weather | 2 |
| 여러 Tool 복합 호출 | 2 |
| 합계 | 30 |

Tool Calling Data가 특정 Tool에 편중되지 않도록 한다.

---

# 21. Fashion Recommendation Data 구성 목표

Fashion Recommendation Data 50개는 다음 요소가 최대한 다양하게 포함되도록 작성한다.

```text
계절
봄
여름
가을
겨울

날씨
맑음
흐림
비
눈
더움
추움
일교차

TPO
학교
데이트
여행
면접
발표
결혼식
카페
축제
일상

스타일
미니멀
캐주얼
스트릿
클래식
모던
클린

핏
Slim
Regular
Wide
Oversized

추천 방식
일반 추천
내 옷 추천
```

동일한 유형의 예제만 반복하지 않는다.

---

# 22. Gold Data 검수 규칙

Gold Data 작성자는 본인이 작성한 데이터를 먼저 검토하고 이후 다른 팀원이 교차 검증한다.

검수 항목은 다음과 같다.

## Fashion Recommendation

```text
[ ] 사용자 요청을 정확하게 이해했는가?
[ ] 날씨에 적합한 코디인가?
[ ] TPO에 적합한가?
[ ] 사용자의 선호 스타일을 반영했는가?
[ ] 싫어하는 색상을 불필요하게 사용하지 않았는가?
[ ] 선호 핏을 적절하게 반영했는가?
[ ] LOOK 1, 2, 3 역할이 구분되는가?
[ ] 추천 이유가 실제 Context에 근거하는가?
[ ] 내 옷 추천 시 item_id가 실제 Wardrobe에 존재하는가?
```

## Tool Calling

```text
[ ] 필요한 Tool을 모두 호출했는가?
[ ] 불필요한 Tool을 호출하지 않았는가?
[ ] Tool 이름이 정확한가?
[ ] Arguments가 올바른가?
[ ] Tool 호출 순서가 자연스러운가?
[ ] Tool Result를 다음 판단에 올바르게 사용했는가?
[ ] Tool이 필요하지 않은 요청에서 Tool을 호출하지 않았는가?
```

---

# 23. Review Metadata

Gold Data 원본 관리 시 다음과 같은 검수 정보를 추가할 수 있다.

```json
{
  "review": {
    "status": "approved",
    "reviewer": "team_member",
    "notes": null
  }
}
```

상태 예:

```text
draft
reviewing
approved
rejected
```

Fine-Tuning용 데이터로 변환할 때는 이러한 관리용 Metadata를 제거할 수 있다.

---

# 24. 데이터 저장 구조

프로젝트에서는 다음과 같이 관리한다.

```text
data/
├── gold/
│   ├── fashion-recommendation.json
│   └── tool-calling.json
│
├── synthetic/
│
└── processed/
```

문서는 다음 위치에 저장한다.

```text
docs/
└── ai-data-model/
    ├── data-research.md
    └── gold-data-guide.md
```

---

# 25. 학습 데이터 변환

Gold Data 원본은 사람이 작성하고 검수하기 좋은 구조로 관리한다.

Fine-Tuning 직전 별도의 변환 Script를 통해 Qwen 학습 형식으로 변환한다.

```text
Gold Data JSON
        ↓
Validation
        ↓
Conversion Script
        ↓
Qwen Training Data
(JSON / JSONL)
```

학습 데이터는 최종적으로 대화 구조를 사용한다.

예:

```json
{
  "messages": [
    {
      "role": "system",
      "content": "당신은 개인 맞춤형 패션 추천 에이전트입니다."
    },
    {
      "role": "user",
      "content": "내일 전주에서 데이트하는데 뭐 입지?"
    },
    {
      "role": "assistant",
      "content": "..."
    }
  ]
}
```

Tool Calling Data는 Tool Call과 Tool Result가 포함되는 대화 형식으로 별도 변환한다.

---

# 26. 최종 목표

본 Gold Data는 다음 단계의 기준 데이터로 사용한다.

```text
Gold Data
약 80개

↓

Synthetic Data 생성
약 500~1,000개

↓

HITL 검증

↓

Train / Validation / Test

↓

Qwen3-4B QLoRA Fine-Tuning

↓

Fashion SLM
```

Gold Data의 품질이 Synthetic Data와 최종 Fashion SLM의 품질에 직접적인 영향을 미치므로 수량보다 일관성, 정확성, 다양성을 우선한다.