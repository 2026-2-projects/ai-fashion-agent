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
