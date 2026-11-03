# Google Calendar 읽기 전용 연결 및 Tool

Google Calendar를 웹 OAuth로 연결하고, 로그인한 사용자의 지정 날짜 일정·시간·장소를 읽습니다.
일정 등록·수정·삭제 기능은 없습니다. 프론트엔드 화면과 모델/Agent 실행 루프는 후속 통합 대상입니다.

## 1. 로컬 DB 준비

Docker Desktop을 실행한 뒤 **저장소 루트**에서 실행합니다.

```bash
export POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
docker compose up -d --wait db
```

생성된 비밀번호는 현재 터미널의 환경변수에 있습니다. `backend/.env`의 `DATABASE_URL`에 같은 값을 사용하세요.
기본 접속 대상은 `127.0.0.1:5432`, DB는 `ai_fashion_agent`, 사용자는 `fashion`입니다.
다른 서버가 5432 포트를 사용한다면 `export POSTGRES_PORT=5433`을 먼저 실행하고 URL도 맞춥니다.
같은 DB를 다시 시작할 때는 최초 설정한 비밀번호를 사용합니다.

빈 Docker 볼륨에서 `backend/sql/001_calendar.sql`이 자동 실행되어 다음 테이블이 생성됩니다.

- `users`: 회원가입·세션 로그인에 필요한 최소 회원 정보
- `google_calendar_connections`: 사용자별 암호화 토큰·만료시각·재연결 상태
- `google_calendar_oauth_states`: 사용자·브라우저에 묶인 10분짜리 일회성 OAuth 요청

기존 PostgreSQL을 사용할 때는 빈 DB에 SQL을 직접 적용할 수 있습니다.

```bash
psql -d ai_fashion_agent -v ON_ERROR_STOP=1 -f backend/sql/001_calendar.sql
```

이 SQL은 초기 구성용이며 기존 테이블을 덮어쓰거나 삭제하지 않습니다. 이미 같은 테이블이 있으면
적용을 중단하므로 기존 구조를 확인하고 별도 마이그레이션을 작성해야 합니다.
컨테이너 재시작으로 기존 볼륨에 초기 SQL이 다시 실행되지는 않습니다.

## 2. Python 및 환경변수

Python 3.12 이상을 사용합니다. `backend` 디렉터리에서 실행합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python -c 'import secrets; print(secrets.token_urlsafe(48))'
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

첫 난수는 `SESSION_SECRET_KEY`, 두 번째는 `GOOGLE_TOKEN_ENCRYPTION_KEY`에 넣습니다.
`DATABASE_URL`에도 실제 DB 비밀번호를 넣습니다. `.env`는 Git에서 제외됩니다.
암호화 키는 재시작 이후에도 동일하게 유지해야 저장된 토큰을 읽을 수 있습니다.
`SESSION_COOKIE_SECURE=false`는 로컬 HTTP 전용이며 HTTPS에서는 `true`로 설정합니다.
토큰·OAuth 클라이언트 비밀키는 세션 쿠키나 Agent 출력에 넣지 않습니다.

## 3. Google Cloud 설정

1. Google Cloud 프로젝트에서 **Google Calendar API**를 활성화합니다.
2. OAuth 동의 화면을 설정하고, Testing 상태라면 사용할 Google 계정을 테스트 사용자로 추가합니다.
3. **Web application(웹 애플리케이션)** 유형의 OAuth 클라이언트를 만듭니다.
   예전 검증 브랜치의 Desktop app 클라이언트와 로컬 `token.json`은 사용하지 않습니다.
4. 승인된 리디렉션 URI를 다음 값과 정확히 일치시킵니다.
   `http://127.0.0.1:8000/api/v1/calendar/callback`
5. `.env`의 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`를 채웁니다.

요청 권한은 `https://www.googleapis.com/auth/calendar.events.readonly` 하나입니다.
토큰 응답에 권한 목록이 있으면 이 읽기 전용 권한만 포함되어 있는지 검사합니다.
OAuth는 PKCE(S256)·일회성 state·로그인 세션을 검증합니다. 백엔드가 code를 토큰으로 교환하고,
access/refresh token을 Fernet으로 암호화해 DB에 저장합니다. 토큰 갱신 시 새 refresh token이
없으면 기존 값을 유지합니다. 새 OAuth 연결에는 새 refresh token을 요구해 다른 Google 계정과
이전 토큰이 섞이지 않도록 합니다. 실패한 재연결은 기존 정상 연결을 덮어쓰지 않습니다.

참고: [웹 OAuth](https://developers.google.com/identity/protocols/oauth2/web-server),
[Calendar 권한](https://developers.google.com/workspace/calendar/api/auth),
[일정 조회](https://developers.google.com/workspace/calendar/api/v3/reference/events/list).

## 4. 실행 및 실제 연결 확인

```bash
uvicorn app.main:app --reload
```

**항상 `http://127.0.0.1:8000/docs`로 접속**합니다. `localhost`와 섞으면 콜백에 로그인 쿠키가 전달되지 않습니다.

1. `POST /api/v1/auth/signup`: 이메일과 12자 이상 비밀번호로 회원가입합니다.
2. `POST /api/v1/auth/login`: 로그인 응답의 `csrf_token`을 복사합니다.
3. `POST /api/v1/calendar/connect`: `X-CSRF-Token` 헤더에 위 값을 넣습니다.
4. 응답의 `authorization_url`을 **동일한 브라우저**의 새 탭에서 엽니다.
5. Google 읽기 권한에 동의하면 콜백이 `connected: true`를 반환합니다.
6. `GET /api/v1/calendar/connection`으로 상태를 확인합니다.
7. `GET /api/v1/calendar/events?date=2026-11-03`처럼 날짜를 지정해 실제 일정과 대조합니다.

로그아웃은 `POST /api/v1/auth/logout`과 CSRF 헤더를 사용합니다.
Google 연결은 서비스 로그인과 별개이며 로그아웃 후에도 DB에 유지됩니다.

조회 결과 예:

```json
{
  "date": "2026-11-03",
  "timezone": "Asia/Seoul",
  "events": [
    {
      "id": "google-event-id",
      "title": "저녁 약속",
      "start": "2026-11-03T19:00:00+09:00",
      "end": "2026-11-03T20:00:00+09:00",
      "all_day": false,
      "location": "전주 한옥마을"
    }
  ]
}
```

기본(`primary`) 캘린더에서 한국 시간 자정부터 다음 자정까지 겹치는 일정을 조회합니다.
반복 일정은 개별 발생 건으로 펼치고, 취소 일정은 제외하며 모든 페이지를 읽습니다.
종일 일정은 `YYYY-MM-DD` 문자열로 반환하고 `end`는 마지막 날의 다음 날짜입니다.
제목·장소가 없으면 빈 문자열이며 일정이 없으면 `events: []`입니다. 설명·참석자는 반환하지 않습니다.
일정은 DB에 저장하지 않습니다.

주요 오류는 로그인 필요 401, CSRF/권한 부족 403, OAuth state 오류 400, 재연결 필요 409,
날짜 오류 422, 호출 한도 429, 외부 응답 오류 502, 설정 누락 503, 타임아웃 504입니다.
조회 실패는 빈 일정으로 바꾸지 않습니다. 만료된 access token은 갱신하며 401 응답 시 최대 한 번
갱신·재조회를 수행합니다. 권한 철회·갱신 토큰 만료 시 연결을 다시 시작합니다.
콜백 인증 코드는 Uvicorn 접근 로그에서 제거하며 캘린더 응답은 `no-store`입니다.
배포 시 앞단 프록시에서도 콜백 쿼리 문자열을 로그에 기록하지 않도록 설정해야 합니다.

## 5. Agent Tool 사용

```python
from app.agent.tools.calendar import CALENDAR_TOOL_SCHEMA, get_calendar_events

# db와 user_id는 백엔드의 인증된 실행 문맥에서 주입합니다.
result = get_calendar_events(db, authenticated_user_id, date="2026-11-03")
```

모델에는 `CALENDAR_TOOL_SCHEMA`의 날짜 인자만 공개합니다. 사용자 ID·토큰·DB 연결을 모델에게
입력받지 않습니다. `오늘/내일` 같은 표현은 Agent 계층에서 절대 날짜로 변환한 뒤 호출합니다.
Tool 실패 시 `CalendarError.code`, `.status_code`로 재연결·실패를 구분할 수 있습니다.

## 6. 자동 테스트

```bash
# backend 디렉터리. 테스트 전용 DB 접속 URL을 지정합니다.
export TEST_DATABASE_URL='postgresql+psycopg://fashion:YOUR_PASSWORD@127.0.0.1:5432/ai_fashion_agent'
pytest -q
ruff check .
```

테스트는 지정 DB 안에 임의의 독립 스키마를 만들고 초기 SQL을 적용합니다. 테스트별 변경은
롤백하고 종료 시 **테스트가 만든 스키마만** 삭제합니다. 테스트 DB 계정에 스키마 생성 권한이 필요합니다.
`TEST_DATABASE_URL`이 없으면 PostgreSQL 통합 테스트는 skip되며, 전체 검증 완료를 의미하지 않습니다.
실제 Google 요청·토큰 교환은 모의 처리하므로 자동 테스트는 실제 계정 연결 성공의 증거가 아닙니다.

실제 검증 체크리스트:

- [ ] Google 동의 및 콜백 성공
- [ ] 알려진 일정의 제목·시간·장소 일치
- [ ] 종일·반복 일정과 일정 없는 날짜 확인
- [ ] 재시작 후 저장된 인증정보로 조회
- [ ] 두 서비스 사용자 사이 연결·일정 격리

인증·DB 기반은 `origin/feature/fastapi-postgresql`, 일정 조회 클라이언트는
`origin/feature/google-calendar-api`의 코드를 필요한 범위에서 재사용했습니다.
