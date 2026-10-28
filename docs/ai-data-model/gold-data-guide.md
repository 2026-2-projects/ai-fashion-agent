# 3.2 Gold Data 작성 가이드 (v2)

> 2026-10-28 개정 초안 · 교수님 피드백: 통합 5 LOOK 및 의류 이미지 시각화 반영

## 1. 목적

본 문서는 AI 기반 개인 맞춤형 패션 에이전트의 Qwen3-4B Fine-Tuning에 사용할 **v2 Gold Data**의 작성 규칙과 JSON 구조를 정의한다.

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

1. Gold Data 원본은 JSON 객체들의 **배열(JSON Array)** 형식으로 저장한다.
2. 고유 ID `FR-001`~`FR-050`, `TC-001`~`TC-030`을 유지한다.
3. 자연스러운 한국어 사용자 요청, 다양한 계절·날씨·TPO·취향·핏을 유지한다.
4. **5 LOOK 생성 요청**에는 일반 추천 3자리와 실제 옷장 추천 2자리, 총 5개 LOOK 슬롯을 고정 순서로 제공한다.
5. LOOK별로 `status`는 `available` 또는 `unavailable`이다. 불가능한 코디를 지어내지 않는다.
6. 일반 LOOK 1~3에서 `item_id`는 `null`, 실제 옷장 LOOK 4~5에서는 등록된 `item_id`만 사용한다.
7. 사용자 제약(예: **"내 옷만"**, 특정 색상 제외)은 기본 5 LOOK 추천 형식보다 우선한다.
8. Tool Calling은 실제 요청에 필요한 Tool만 실행한다. 추천을 생성한다면 기본적으로 사용자 컨텍스트·옷장 두 정보가 필요하다.
9. 외부 사진의 `image_url`은 모델이 생성하지 않는다. Backend가 실제 이미지 매칭·출처·이용 허락을 처리한다.
10. 팀원이 원본을 작성·수정하고 교차 검수한 뒤 승인한다. 규칙만 적용한 자동 변환물은 곧바로 Gold로 인정하지 않는다.
11. 샘플 JSON은 구조 학습용이며, 실제 80개 수량에 포함하지 않는다.

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

Fashion Recommendation Data는 요청과 Context를 바탕으로 **통합 5 LOOK 결과**를 학습한다. FR은 기존 공통 필드를 유지한다.

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
    "wardrobe": []
  },
  "answer": {"looks": []}
}
```

**위 예시는 필드 설명을 위한 뼈대**다. 승인 가능한 실제 FR 데이터에는 5개 LOOK 객체를 모두 채워야 한다. 전체 작성 예시는 `docs/ai-data-model/sample-gold-data-v2.json`을 참고한다.

기존 `context.use_wardrobe`는 전역적인 추천 방식 구분이어서 v2에서 제거한다. `context.wardrobe`는 빈 배열이라도 항상 포함한다. 실제 옷장 정보인 것처럼 확인되지 않은 항목을 조작하지 않으며, 학습 예시의 Wardrobe는 일관된 **가상 시나리오 데이터**로 작성한다.

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

# 11. 통합 5 LOOK 구성 규칙

**항상 순서가 고정된 5개의 슬롯을 반환**한다. 단, 사용자 제약 또는 옷장 구성 부족 시 `unavailable`을 사용한다.

| LOOK | `role` | 의미 | 의류 출처 |
|---|---|---|---|
| 1 | `preference_best` | 취향을 가장 잘 반영 | 일반 추천 |
| 2 | `preference_alternative` | 취향을 유지하는 다른 조합 | 일반 추천 |
| 3 | `exploration` | 무리하지 않는 새로운 스타일 | 일반 추천 |
| 4 | `wardrobe_best` | 보유 의류 중 최적 조합 | 실제 Wardrobe |
| 5 | `wardrobe_alternative` | 보유 의류의 다른 조합 | 실제 Wardrobe |

- LOOK 1~3: `item_id: null`이다. 사용자의 선호·TPO·날씨 및 싫어하는 색을 고려한다.
- LOOK 4~5: **등록된 옷만** 사용하며 서로 다른 조합이 되어야 한다. 같은 옷을 두 LOOK에서 재사용하는 것은 허용하되, 전체 조합이 같아서는 안 된다.
- 기본 완성 코디 기준: `top` 1개 + `bottom` 1개 + `shoes` 1개. `outer`는 필요할 때만 추가한다. 원피스 등 지원하지 않은 슬롯 조합은 추후 별도 정의한다.
- 옷장 완성 코디 2개 가능: LOOK 4, 5 `available`.
- 옷장 완성 코디 1개 가능: LOOK 4 `available`, LOOK 5 `unavailable`.
- 옷장이 비었거나 완성 코디 0개: LOOK 4, 5 `unavailable`.
- **"내 옷만으로" 같은 명시적 제한**이 있다면 LOOK 1~3의 외부 의류 제안은 `unavailable`로 두고, LOOK 4~5만 옷장 추천을 한다. 화면 슬롯은 5개를 유지하지만, 보유하지 않은 옷을 실제 착용 제안으로 강요하지 않는다.
- 단순 조합 질문, 옷장 목록 조회 등 **5 LOOK 추천 자체가 아닌 요청**은 Tool Calling의 `direct_answer`로 응답할 수 있다.

---

# 12. LOOK JSON 구조

각 LOOK의 필수 필드: `look_id`, `role`, `status`, `style`, `items`, `reason`.

사용할 수 있는 `status`: `available`, `unavailable`.

```json
{
  "look_id": 4,
  "role": "wardrobe_best",
  "status": "available",
  "style": "미니멀 캐주얼",
  "items": [
    {"slot": "top", "name": "화이트 오버핏 셔츠", "item_id": 12},
    {"slot": "bottom", "name": "블루 와이드 데님", "item_id": 24},
    {"slot": "shoes", "name": "화이트 스니커즈", "item_id": 51}
  ],
  "reason": "등록된 옷만으로 카페 방문에 적합한 조합을 구성했습니다."
}
```

불가능한 LOOK 예시:

```json
{
  "look_id": 5,
  "role": "wardrobe_alternative",
  "status": "unavailable",
  "style": null,
  "items": [],
  "reason": "등록된 의류로 서로 다른 두 번째 완성 코디를 만들 수 없습니다."
}
```

- `available`: `style`은 비어 있지 않은 문자열, `items`는 코디를 완성하는 아이템 목록, `reason`은 Context에 근거한 자연스러운 한국어다.
- `unavailable`: `style: null`, `items: []`, `reason`에 **사용자 제약 또는 불가능한 구체적 이유**를 기술한다.
- 각 item의 `slot`은 옷장 `category`와 대응한다. 일반 추천 `item_id`는 `null`, 옷장 추천 `item_id`는 실제 정수 ID다.
- `outer`, `accessory` 등은 불필요하면 생략한다. `top`·`bottom`·`shoes`의 완성 기준은 위 정책에 따른다.
- 날짜는 `reference_datetime`을 기준으로 해석하고, 날씨·일정 정보가 없으면 실측 정보를 꾸며내지 않는다.

---

# 13. 일반 추천과 내 옷 추천의 통합

v1의 `use_wardrobe` 분기 대신 v2에서는 **각 LOOK의 `role`**로 출처를 구분한다.

## 일반 추천 (LOOK 1~3)

모든 추천 아이템은 `item_id: null`을 사용한다. 이는 **미보유·신규 제안**을 뜻하며, 실제 사용자 옷장에 있다고 주장하면 안 된다.

## 내 옷 추천 (LOOK 4~5)

`context.wardrobe`의 각 항목 예:

```json
{
  "item_id": 12,
  "category": "top",
  "item_type": "shirt",
  "color": "white",
  "fit": "oversized",
  "seasons": ["spring", "fall"]
}
```

LOOK 4~5에 들어갈 모든 `item_id`는 `context.wardrobe`에 존재해야 하고, `items[].slot`과 `wardrobe[].category`도 같아야 한다. 색·핏·시즌·의류 종류·이름은 실제 옷장 품목과 의미상 일치해야 한다. `item_id: 999`처럼 없는 ID를 만들면 오류다.

옷장 정보가 부족하면 가상의 item을 채우지 않고 `unavailable`을 사용한다. 사용자가 "내 옷만"이라고 요구한 경우 일반 추천으로 우회하지 않는다.

## 사진 제공 및 이미지 매칭

**이미지 URL은 모델 출력 Gold Data에 넣지 않는다.** FastAPI가 Qwen의 검증된 추천 아이템을 받은 다음 별도로 이미지를 연결한다.

- LOOK 1~3: 이용 권한이 확인된 외부 의류 참고 사진을 검색/매칭한다.
- LOOK 4~5: 사용자가 등록한 의류 사진을 우선한다. 없는 경우 **실제 소유 사진인 척 대체하지 않는다.**
- Frontend 응답 전용 이미지 정보는 `image_url`, `image_source`, `source_url` 등의 별도 필드로 관리한다. 이미지 검색 실패 시 `image_url: null`이다.
- 공식 API, 사이트 이용 약관, 저작권, 출처 표시와 이미지 캐시·재사용 조건을 확인한다. 크롤링 허용 여부가 사진의 재배포 허락은 아니다.

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

v2에서 **5 LOOK을 생성할 때** `get_user_context()`와 `get_wardrobe()`가 기본적으로 필요하다. 날씨와 캘린더는 요청에 따라 추가한다. 단순 질문·조회는 5 LOOK이 아니므로 기존의 최소 Tool 정책을 유지한다.

대표 예시:

```text
사용자: "내일 일정 보고 날씨까지 고려해서 추천해줘"
  ↓
get_calendar_events(date=2026-10-03)
  ↓  일정 장소·시각 확인
get_weather(place=전주 한옥마을, date=2026-10-03, time=18:00)
  ↓
get_user_context()
  ↓
get_wardrobe()
  ↓
generate_five_looks
```

실제 호출 순서는 Tool 의존성을 지키는 범위에서 달라질 수 있다. **Calendar → Weather**처럼 앞선 결과에서 인자를 얻는 흐름은 보존한다. Weather의 장소·날짜·시각을 임의로 만들어서는 안 된다.

추천 TC의 `final_response` 예:

```json
{
  "type": "fashion_recommendation",
  "context_summary": "2026-10-03 18:00 전주 한옥마을 데이트, 17°C, 사용자 취향 및 보유 의류 확인",
  "action": "generate_five_looks"
}
```

`generate_five_looks`는 **별도의 Agent Tool이 아니라 최종 응답 단계의 action 이름**이다. 허용 Tool은 기존 4개 그대로다.

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

허용된 Tool은 다음 4개이다.

| Tool | 실행 조건 | 주요 입력 |
|---|---|---|
| `get_user_context()` | 기존 사용자 프로필·취향·피드백이 필요한 경우, 통합 추천에서는 기본 | `{}` |
| `get_wardrobe()` | 보유 의류 조회가 필요하거나 통합 5 LOOK을 생성하는 경우 | `{}` |
| `get_weather()` | 실제 날씨 확인이 필요한 경우 | `place`, `date`, `time` |
| `get_calendar_events()` | 연결된 Google Calendar의 일정 정보가 필요한 경우 | `date` |

- 통합 5 LOOK 기본 요청: `get_user_context` + `get_wardrobe`.
- 날씨 고려 요청: 위 두 Tool + `get_weather`.
- 일정 고려 요청: 위 두 Tool + `get_calendar_events`.
- 일정 장소 날씨까지 필요한 경우: Calendar의 이벤트 장소·시간 확인 후 Weather 호출.
- 단순 색상 조합 질문: Tool 없음 (`steps: []`, `direct_answer`).
- 옷장 목록·가능 여부 확인만 요청: `get_wardrobe`, `direct_answer` 가능 (TC-019 같은 경우).
- 캘린더 연결되지 않음, 장소 불명확, 날씨 조회 실패 등은 실패/추가 질문으로 다루고, 실시간 결과를 만들어내지 않는다.

---

# 20. Tool Calling 데이터 구성 목표

v1의 30개를 **삭제하거나 재번호 부여하지 않는다**. 기존 30개 중 `direct_answer` 5개는 요청이 적절하면 유지하고, `generate_three_looks` 25개를 우선 `generate_five_looks` 기준으로 검토한다.

v1의 작성 목표는 다음과 같았다 (기존 분포 참고용).

| v1 유형 | 목표 개수 |
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
| **합계** | **30** |

**v2 최종 호출 패턴 분포는 변환 후 재계산**한다. 5 LOOK 추천에 두 기본 Tool이 추가되므로 v1의 단일 Tool 할당표를 그대로 강제해서는 안 된다. 단순 조회·직접 답변·의존적 Tool 호출 사례는 다양성을 위해 유지한다.

---

# 21. Fashion Recommendation Data 구성 목표

FR 50개는 기존 `FR-001`~`FR-050`을 유지한다. 기존 분포는 **일반 추천 35개, 내 옷 추천 15개**이며, v2에서는 각 데이터의 5 LOOK 슬롯과 실제 옷장 Context를 기준으로 변환한다.

다양성 유지 항목:

```text
계절: 봄 / 여름 / 가을 / 겨울
날씨: 맑음 / 흐림 / 비 / 눈 / 더움 / 추움 / 일교차
TPO: 학교 / 데이트 / 여행 / 면접 / 발표 / 결혼식 / 카페 / 축제 / 일상
스타일: 미니멀 / 캐주얼 / 스트릿 / 클래식 / 모던 / 클린
핏: slim / regular / wide / oversized
옷장 상태: 충분 / 대안 1개만 가능 / 비어 있음 / 특정 슬롯 누락
사용자 제한: 통합 추천 / 내 옷만 / 기피 색상·스타일
```

가능한 옷장 조합을 무리하게 2개로 채우지 않는다. 정상 5 LOOK·부분 실패·제약 우선 사례가 모두 포함되도록 팀원들이 실제 분포를 검토한다.

---

# 22. Gold Data 검수 규칙

작성자 자체 검토 → 동료 교차 검토 → 통합 검수 → `approved` 순서로 관리한다.

## Fashion Recommendation

```text
[ ] 사용자 요청과 명시적 제한(내 옷만, 싫어하는 색 등)을 지켰는가?
[ ] LOOK 슬롯이 정확히 5개이며 순서/role이 올바른가?
[ ] 모든 LOOK에 status/style/items/reason이 존재하는가?
[ ] unavailable은 style=null, items=[]이며 reason이 충분한가?
[ ] available은 상의/하의/신발 기본 완성 기준을 만족하는가?
[ ] LOOK 1~3의 item_id는 모두 null인가?
[ ] LOOK 4~5의 item_id는 Wardrobe에 존재하는가?
[ ] item_id에 대응되는 category/slot 및 색·핏·종류가 일치하는가?
[ ] LOOK 4와 5가 서로 다른 완성 조합인가?
[ ] 날씨·계절·TPO·선호·기피 색상을 반영했는가?
[ ] 추천 이유가 실제 Context에 근거하는가?
[ ] 허위 실시간 날씨·허위 보유 의류를 만들지 않았는가?
```

## Tool Calling

```text
[ ] 필요한 Tool을 모두 호출하고 불필요한 Tool을 피했는가?
[ ] Tool 이름과 Arguments가 정확한가?
[ ] Tool Result와 다음 Tool 사이의 장소·날짜·시각이 일치하는가?
[ ] 5 LOOK 추천이면 get_user_context 및 get_wardrobe가 포함되는가?
[ ] 5 LOOK 최종 action은 generate_five_looks인가?
[ ] 단순 질문·조회는 direct_answer를 허용하는가?
[ ] Tool 사용과 final_response.type을 기계적으로 동일시하지 않았는가?
[ ] Tool 없이 설명 가능한 요청에 임의 호출을 하지 않았는가?
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

# 24. 데이터 저장 구조 및 v1 보존

기존 v1 데이터 80개는 `feature/gold-data(WBS-3.2)` 브랜치에 유지한다. **v2 변경은 별도 `feature/gold-data-v2` 브랜치에서만 진행**한다.

권장 저장 구조:

```text
data/
├── gold/
│   ├── hhoaya_gold_data.json
│   ├── joonoh.json
│   ├── yuna.json
│   ├── fr_general_k-dev178.json
│   ├── fr_wardrobe_k-dev178.json
│   ├── wardrobe_k-dev178.json
│   ├── weather_k-dev178.json
│   ├── wardrobe_weather_k-dev178.json
│   ├── sample-gold-data.json         # v1 참고용 (80개 제외)
├── synthetic/
└── processed/

docs/ai-data-model/
├── data-research.md
├── gold-data-guide.md                # v2 기준으로 개정
└── sample-gold-data-v2.json          # v2 참고용 (80개 제외, gold/ 밖에 배치)
```

팀원별 파일 분할은 당장 강제로 통합하지 않는다. 검증·리뷰 완료 후 50 FR + 30 TC를 합치는 별도 프로세스를 두어도 된다. 샘플 파일은 수량 검증에서 반드시 제외한다.

---

# 25. 학습 데이터 변환

Gold Data 원본은 사람이 작성·리뷰하기 좋은 JSON 배열로 유지하고, **승인 후에만** Fine-Tuning용 대화 데이터로 변환한다.

```text
Gold Data v2 JSON (원본)
  ↓  JSON/ID/LOOK/Tool/의류 Validator
팀원 교차 검수 및 승인
  ↓
Conversion Script
  ↓
Qwen Chat / Tool Calling Training Data (JSONL 등)
```

FR은 `context`와 5 LOOK 정답을 사용자·시스템·assistant 메시지로 구성한다. TC는 Tool Call / Tool Result / 최종 action을 실제 대화 흐름에 맞게 변환한다. `reference_datetime`은 상대 날짜의 정답 기준이며, 학습에 앞서 프롬프트 표현을 정한다.

**이미지 URL, review metadata, 학습에 불필요한 관리 필드**는 모델의 출력 정답에 포함하지 않는다. 리뷰 상태·원본 출처는 별도 관리한다. Dataset train/validation/test 분리 및 중복 제거는 Synthetic Data 생성 전에 확정한다.

---

# 26. 최종 목표 및 v2 전환 절차

```text
v1 Gold Data 80개 (FR 50 + TC 30)
  ↓  원본 보존, v2 Guide + Sample 확정
FR 예제 1개 / TC 예제 1개 시범 변환
  ↓
팀원별 담당 ID 변환 + 교차 검수
  ↓
v2 Gold 80개 승인
  ↓
Synthetic Data 500~1,000개 (계획)
  ↓  HITL 검수
Train / Validation / Test
  ↓
Qwen3-4B QLoRA Fine-Tuning
  ↓
Fashion SLM + 5 LOOK Agent
```

v2의 성공 기준은 단순한 JSON 형식 준수가 아니다. 사용자 제약을 지키면서 실제 소유 의류를 위조하지 않고, 5 LOOK 추천과 Tool Calling이 일관되게 동작하는 **검수된 Gold Data**를 만드는 것이다.

