# 4.6 Feedback · Save · Validator

4.5의 Mock Agent와 실제 네 Tool을 기반으로 피드백·저장·선호 요약을 연결한다.
FastAPI·DB·Agent 연동 범위이며, 웹 화면과 Qwen 추론 어댑터는 별도 작업이다.
기존 5 LOOK 필드는 유지하고 서버 발급 식별자인 `look_refs`를 응답에 추가한다.

## DB 초기 구성

PostgreSQL 15 이상과 Python 3.12 이상을 사용한다. Docker는 필수가 아니다.
빈 프로젝트 DB를 만든 뒤 저장소 루트에서 SQL을 순서대로 적용한다.

```bash
createdb ai_fashion_agent
psql -d ai_fashion_agent -v ON_ERROR_STOP=1 -f backend/sql/001_initial.sql
psql -d ai_fashion_agent -v ON_ERROR_STOP=1 -f backend/sql/002_feedback_save.sql
```

- `001_initial.sql`: 인증·프로필·취향·옷장·Calendar 테이블
- `002_feedback_save.sql`: 추천 LOOK 스냅샷·피드백·저장 테이블
- `schema_migrations`: 적용한 SQL 버전 기록

각 SQL은 트랜잭션으로 실행한다. 기존 테이블이 있거나 같은 버전을 다시 적용하면 실패하며
기존 데이터를 덮어쓰지 않는다. 기존 팀 DB에 적용할 때는 먼저 스키마를 대조해야 한다.
앱 시작 시 자동 DDL 실행이나 기존 DB 초기화는 하지 않는다.

`backend/.env.example`을 참고해 `.env`를 준비한다. 이미 있는 `.env`는 유지한다.
`DATABASE_URL`, 32자 이상의 `SESSION_SECRET_KEY`를 설정하고 로컬 HTTP에서는
`SESSION_COOKIE_SECURE=false`를 사용한다. Google·Weather 키는 해당 Tool을 호출할 때 필요하다.

```bash
cd backend
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

## 추천에서 피드백까지

1. 회원가입·로그인 후 받은 세션 쿠키와 `csrf_token`을 사용한다.
2. `POST /api/v1/agent/recommend`에 `X-CSRF-Token`과 추천 요청을 전달한다.
3. 응답의 LOOK 번호와 `look_refs`를 대응시켜 버튼의 대상을 정한다.

```json
{
  "look_refs": [
    {"look_id": 1, "outfit_id": "서버가-발급한-UUID"}
  ]
}
```

실제 응답에는 기존 `type`, `action`, `context_summary`, `called_tools`, `looks`와
다섯 LOOK의 `look_refs`가 함께 있다. 위 JSON은 추가 필드만 보여 주는 예시다.
정수 `look_id`는 화면의 1~5번 슬롯이고, UUID `outfit_id`는 특정 추천의 LOOK을 식별한다.
다음 추천의 같은 1번 LOOK은 다른 UUID를 받는다.

모든 조회는 로그인한 사용자 범위로 제한하고, 변경 요청에는 CSRF가 필요하다.
프론트엔드는 `status=unavailable`인 LOOK의 좋아요·싫어요·저장 버튼을 비활성화한다.
서버도 해당 LOOK의 반응 등록과 저장을 422로 거부한다.

| 메서드·경로 (`/api/v1` 기준) | 동작 |
|---|---|
| `GET /outfits/{outfit_id}/feedback` | 현재 반응, 이유, 추가 설명 조회. 반응이 없으면 `reaction: null` |
| `PUT /outfits/{outfit_id}/feedback` | 반응 등록 또는 교체 |
| `DELETE /outfits/{outfit_id}/feedback` | 반응 취소 |
| `PUT /saved-outfits/{outfit_id}` | 저장. 요청 본문은 생략하거나 `{}` |
| `GET /saved-outfits` | 저장한 코디 목록 |
| `GET /saved-outfits/{outfit_id}` | 저장한 코디 상세 |
| `DELETE /saved-outfits/{outfit_id}` | 저장 취소 |

좋아요 본문:

```json
{"reaction": "like"}
```

싫어요 본문:

```json
{
  "reaction": "dislike",
  "reason_codes": ["color", "fit"],
  "comment": "색상이 밝고 핏이 너무 넓어요."
}
```

싫어요 이유는 하나 이상 필요하다. `color`, `fit`, `style`, `too_formal`, `too_plain`을
지원하며 중복 선택은 한 번으로 정리한다. 추가 설명은 선택 사항이고 최대 1,000자다.
좋아요에는 싫어요 이유를 지정할 수 없다. 같은 LOOK에서 마지막으로 지정한 반응만 유지한다.

저장과 반응은 독립적이다. 저장을 취소해도 좋아요는 유지되고, 반응을 취소해도 저장은 유지된다.
중복 저장은 행을 추가하거나 저장 시각을 바꾸지 않는다. 삭제 요청은 대상이 본인 코디이면
이미 취소된 상태에서도 204를 반환한다.

목록 응답은 `{items, total, limit, offset}`이다. 기본 20개, 최대 100개이며
`?limit=20&offset=20`으로 다음 페이지를 조회한다. 저장 시각 내림차순, 동률이면 UUID
내림차순이다. 상세와 목록의 각 항목은 `look`, `feedback`, `saved_at`, `missing_item_ids`를 포함한다.

## 가중치와 추천 Context

| 신호 | 반영 |
|---|---|
| 좋아요 | 확인된 스타일·핏·색상 각각 +1 |
| 저장 | 확인된 스타일·핏·색상 각각 +3 |
| 싫어요: `color` / `fit` / `style` | 선택한 차원만 각각 -1 |
| 싫어요: `too_formal` / `too_plain` | 스타일 -1 및 해당 경향 요약 |

같은 LOOK 안의 흰색 옷 두 벌은 흰색을 한 번만 계산한다. 한국어·영어 별칭은 정규화한다.
좋아요와 저장을 모두 선택하면 +4다. 저장한 코디에 색상 싫어요를 선택하면 색상은 +2,
나머지 확인된 속성은 +3이다. 모든 계산은 현재 반응·저장 상태를 다시 집계한 결과다.
변경·취소 후 이전 점수가 남거나 반복 클릭으로 점수가 증가하지 않는다.

일반 LOOK의 속성은 Mock이 의류를 생성할 때 사용한 구조화된 값에서 얻는다.
옷장 LOOK의 색상·핏은 검증한 DB 품목에서 얻는다. 자유 형식의 코디 이름이나 사용자가 쓴
설명을 파싱해 속성을 추측하지 않는다. 탐색 LOOK처럼 스타일 코드가 명확하지 않은 경우,
또는 옷장 항목에 스타일 정보가 없는 경우에는 그 스타일 차원의 가중치를 만들지 않는다.

`user_preferences.feedback_summary`에는 차원별 상위 양수 5개·하위 음수 5개,
`liked_styles`, `disliked_tendencies`, 현재 신호 수를 저장한다. 원문 설명이나 전체 코디
기록을 Agent Context에 넣지 않는다. `get_user_context()`는 직접 설정한 `preference`와
이 요약을 함께 반환한다.

Mock 추론기는 요약으로 직접 설정한 스타일·색상의 순서와 옷장 항목의 선택 순서를 조정한다.
명시한 싫어하는 색은 피드백보다 우선하며, 직접 지정한 핏은 변경하지 않는다.
설정하지 않은 차원은 학습된 양수 선호를 사용할 수 있다. 수동 취향 설정 API가 피드백
요약을 덮어쓰지 않도록 둘은 별도로 갱신한다.

모든 반응·저장 변경은 사용자 행을 잠근 뒤 변경·요약 갱신을 하나의 트랜잭션에서 수행한다.
다른 요청의 갱신이 끝난 후 현재 상태로 계산하므로 동시 요청에도 신호 수와 가중치가 맞는다.

## Validator와 데이터 보관

- JSON Validator는 JSON 문법, 추가 필드, 엄격한 자료형, 5 LOOK 역할·순서,
  `available/unavailable` 및 필수 슬롯 규칙을 확인한다. 변경된 Pydantic 객체도 다시 검사한다.
- Wardrobe Validator는 ID·슬롯을 검증하고, 의류 이름과 사진 주소를 서버 데이터로 연결한다.
  추천 직후 DB를 다시 조회하고, 신규 저장 시에도 현재 사용자의 옷이 맞는지 재검증한다.
- 추천과 저장 검사에는 같은 Validator를 사용한다. 다른 사용자나 없는 코디는 404,
  잘못된 피드백은 422, 삭제·분류 변경된 옷이 포함된 신규 저장은 409,
  잘못된 모델 JSON·옷장 결과는 502다.
- 이미 저장한 코디에서 옷이 삭제되더라도 원래 코디 텍스트와 반응은 남긴다.
  조회할 때 현재 옷장의 사진만 연결하고 삭제된 ID는 `missing_item_ids`에 담는다.
- 서버는 추천한 LOOK과 계산에 필요한 속성을 내부 스냅샷으로 보관한다. 사용자 메시지,
  일정·날씨 원문은 보관하지 않는다. 전체 추천 이력 조회 기능은 없으며 저장한 코디만 조회한다.
  현재 자동 만료 정책은 없고 회원 탈퇴 시 스냅샷·반응·저장·선호 요약이 함께 삭제된다.

## 모델 어댑터 인계

`InferenceEngine.generate()`의 `AgentDraft` 계약은 유지한다. 기존 Gold Data JSON에
속성 필드를 추가하지 않는다. 런타임에서 확인 가능한 속성이 있으면
`draft._look_features[look_id] = LookFeatures(styles=[...], fits=[...], colors=[...])`로 전달한다.
이 메타데이터는 모델 JSON과 API LOOK 필드에 직렬화되지 않는다. 속성이 없으면 해당 차원의
가중치 계산만 생략한다. 서버는 옷장 LOOK의 색상·핏을 DB로 다시 확인한다.

향후 실제 모델 어댑터는 `feedback_summary`를 프롬프트에 포함하고, 코드로 확인한 구조화
속성만 전달해야 한다. 모델 연결과 실제 추론 품질 검증은 4.5 후속 통합 범위다.

## 테스트

개발 DB와 별도로 빈 테스트 DB를 만들고 SQL을 적용한다.

```bash
createdb ai_fashion_agent_test
psql -d ai_fashion_agent_test -v ON_ERROR_STOP=1 -f backend/sql/001_initial.sql
psql -d ai_fashion_agent_test -v ON_ERROR_STOP=1 -f backend/sql/002_feedback_save.sql
cd backend
export TEST_DATABASE_URL=postgresql+psycopg:///ai_fashion_agent_test
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests
```

테스트 전용 세션 설정은 `tests/conftest.py`에서 제공한다. `TEST_DATABASE_URL`이 없으면
DB 연결이 필요한 테스트는 건너뛰고 단위 테스트만 실행한다. 기본 개발 DB에는 접속하지 않는다.
`TEST_DATABASE_URL`은 테스트 프로세스에서만 앱 DB URL로 사용한다.
기존 통합 테스트와 새 API 테스트는 트랜잭션을
롤백한다. 동시 요청 테스트는 독립 연결에서 테스트 사용자만 커밋하고 종료 시 삭제하며,
명시적인 `TEST_DATABASE_URL`이 없으면 실행하지 않는다. DDL 테스트는 독립 스키마를
만들어 적용·재적용 실패를 검사한 뒤 해당 스키마만 삭제한다.

검증 범위는 반응 변경·취소, 저장 취소, 중복·동시 클릭, 사용자·CSRF 격리, 삭제된 의류,
회원 탈퇴, 초기 SQL, JSON/옷장 오류, 다음 추천의 순서 변화와 수동 제외 조건 우선이다.
실제 Qwen이나 Google·Kakao·기상청 계정을 호출하는 테스트는 포함하지 않는다.
