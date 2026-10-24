# 김서진 Gold Data

FR-026~035와 TC-016~025, 총 20개를 카테고리별로 나눴습니다.
모든 JSON 파일은 이 폴더 바로 아래에 있으며, 기존 JSON 구조를 유지한 배열입니다.

| 분류 | 파일 | ID | 개수 |
|---|---|---|---:|
| 일반 패션 추천 | [fr_general_k-dev178.json](fr_general_k-dev178.json) | FR-026~029 | 4 |
| 내 옷 패션 추천 | [fr_wardrobe_k-dev178.json](fr_wardrobe_k-dev178.json) | FR-030~035 | 6 |
| 옷장 조회 | [wardrobe_k-dev178.json](wardrobe_k-dev178.json) | TC-016~019 | 4 |
| 날씨 조회 | [weather_k-dev178.json](weather_k-dev178.json) | TC-020~023 | 4 |
| 옷장 + 날씨 조회 | [wardrobe_weather_k-dev178.json](wardrobe_weather_k-dev178.json) | TC-024~025 | 2 |

데이터를 취합할 때는 이 폴더의 `*_k-dev178.json` 배열을 모두 합치면 됩니다.
분리 전 통합 파일 `data/gold/seojin.json`은 중복을 피하기 위해 제거했습니다.

---

# 김진호 Gold Data

FR-001...015와 TC-001...005, 총 20개의 Gold Data를 작성하고 하나의 .json 파일로 통합시킴.


| 분류 | ID | 개수 | 내용 |
|---|---|---:|---|
| 일반 패션 추천 | `FR-001~012` | 12 | 프로필, 취향, 날씨, 일정에 따른 코디 3개 추천 |
| 내 옷 패션 추천 | `FR-013~015` | 3 | 등록된 옷장의 `item_id`만 사용한 코디 추천 |
| 사용자 맥락 조회 | `TC-001~004` | 4 | `get_user_context()`를 이용한 취향·프로필 조회 |
| Tool 호출 없음 | `TC-005` | 1 | 외부 정보 없이 직접 답변할 수 있는 요청 |
| **해당파일** | [hhoyaa_gold_data.json](hhoyaa_gold_data.json) | - | - |

### 구성 특징
- 장소는 전주 도심 번화가를 중심으로 작성함.
- 미니멀·캐주얼, 애슬레저, 원마일웨어, 고프코어, 올드머니, 프레피, 아이비리그 등 다양한 스타일을 포함.
- Fashion Recommendation은 각 데이터마다 정확히 3개의 LOOK을 제공함. -> 5개로 수정할것(10/06 발표 피드백)
- Tool Calling은 필요한 Tool만 호출하며, TC-005는 과도한 Tool 호출을 방지하기 위한 무호출 예제임.

### 검증 사항
- JSON 문법 및 ID 중복 확인
- Fashion Recommendation의 LOOK 개수와 역할 확인
- 내 옷 추천의 item_id가 Wardrobe에 존재하는지 확인
- Tool 이름, Arguments, 호출 횟수 및 결과 구조 확인
- 기준 날짜와 상대 날짜 표현의 일치 여부 확인
