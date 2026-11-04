# AI Fashion Agent Backend

Qwen3-4B 기반 개인화 패션 추천 서비스의 FastAPI 백엔드입니다. PostgreSQL 기반 회원·프로필·옷장 기능, WBS 4.3 Location·Weather Tool, WBS 4.4 Google Calendar 읽기 전용 연동, WBS 4.5 모델 비의존 Mock Agent Core를 포함합니다.

이 문서는 로컬 개발과 팀원 인계를 위한 기준입니다. 아래 검증 결과는 명시된 로컬 환경에서 확인한 값이며, 배포 환경의 성능·가용성·보안을 보장한다는 뜻은 아닙니다.

## 1. 목표와 구성

```text
브라우저·Swagger UI
        │ HTTP 요청/응답, 서명된 세션 쿠키, X-CSRF-Token
        ▼
FastAPI + Pydantic + SessionMiddleware
        │ Depends(get_db), SQLAlchemy text() 쿼리
        ▼
SQLAlchemy Engine · Session
        │ PostgreSQL 연결 규약
        ▼
psycopg 3 드라이버
        │
        ▼
PostgreSQL 15
```

- **FastAPI**: URL 라우팅, 요청 처리, 의존성 주입과 OpenAPI 문서를 제공합니다.
- **SQLAlchemy**: Python과 DB 사이의 툴킷입니다. 이 프로젝트는 ORM 라이브러리인 SQLAlchemy의 `Engine`·`Session`·`text()`를 사용하지만, 현재는 ORM 모델 클래스를 정의하지 않고 SQL을 직접 실행합니다.
- **Engine / Session**: `Engine`은 연결 풀과 DB 연결의 진입점이고, `Session`은 요청 중 쿼리·커밋·롤백의 작업 단위를 관리합니다. `pool_pre_ping=True`로 풀에서 꺼낸 연결이 유효한지 먼저 확인합니다.
- **psycopg 3**: SQLAlchemy가 PostgreSQL과 실제로 통신할 때 사용하는 Python 드라이버입니다. 연결 URL의 `postgresql+psycopg://`가 이 드라이버를 지정합니다.
- **PostgreSQL 15**: 사용자, 프로필, 취향 등 관계형 데이터를 저장합니다. 로컬 확인 환경은 Homebrew `postgresql@15` 15.15 계열입니다.
- **Pydantic**: 이메일 형식, 비밀번호 길이, 키 값 같은 요청 데이터를 검증하고 응답 구조를 정의합니다.
- **Uvicorn**: FastAPI 애플리케이션을 실행하는 ASGI 개발 서버입니다.
- **pwdlib[argon2]**: 비밀번호를 평문으로 저장하지 않고 권장 Argon2 해시로 저장·검증합니다.
- **SessionMiddleware / itsdangerous**: 로그인 상태를 `fashion_session` 쿠키에 서명해 보관합니다. 서명은 위·변조를 탐지하지만 내용을 암호화하지는 않습니다. `itsdangerous`는 이 서명 처리에 필요한 의존성입니다.
- **CSRF**: 로그인 시 난수 토큰을 만들고, 상태를 변경하는 요청의 `X-CSRF-Token` 헤더와 세션 값을 상수 시간 비교로 검증합니다. 다른 사이트가 사용자의 쿠키를 이용해 변경 요청을 보내는 공격을 줄입니다.
- **python-dotenv**: Git에 올리지 않는 `backend/.env`의 환경변수를 애플리케이션 시작 시 읽습니다.
- **httpx**: Kakao Local API와 기상청 단기예보 API를 호출합니다. 자동 테스트에서는 `MockTransport`로 외부 네트워크를 대체합니다.
- **Google OAuth 2.0 Authorization Code Flow**: 서비스 로그인 사용자와 Google Calendar 권한을 연결합니다. 웹 서버가 인증 코드를 Access/Refresh Token으로 교환하며, 브라우저에는 토큰을 전달하지 않습니다.
- **Fernet 암호화**: Google Access/Refresh Token을 평문이 아닌 인증 암호문으로 DB에 저장합니다. 암호화 키는 세션 키와 분리해 `.env`에서만 관리합니다.
- **pytest / TestClient**: 실제 API 요청과 유사한 방식으로 상태 코드·응답·쿠키를 자동 검증합니다.
- **savepoint**: DB 테스트가 기존 데이터를 남기지 않도록 바깥 트랜잭션 안에 테스트용 `Session`을 savepoint 방식으로 참여시키고 마지막에 롤백합니다.
- **PostgreSQL FK `ON DELETE CASCADE`**: `users` 행을 삭제하면 FK로 연결된 6개 테이블의 해당 사용자 행도 DB가 함께 삭제합니다.

인증은 현재 요구사항에 따라 **쿠키 세션 방식만 사용하며 JWT는 사용하지 않습니다.**

## 2. 구현 기능과 응답 코드

모든 URL은 `/api/v1`을 기준으로 합니다.

| 기능 | 메서드·경로 | 정상 | 주요 오류 |
|---|---|---:|---:|
| 상태 확인 | `GET /health` | 200 | - |
| 회원가입 | `POST /auth/signup` | 201 | 409 중복 이메일, 422 입력 검증 |
| 로그인 | `POST /auth/login` | 200 | 401 인증 실패, 422 입력 검증 |
| 현재 사용자 | `GET /auth/me` | 200 | 401 로그인 필요 |
| 로그아웃 | `POST /auth/logout` | 204 | 403 CSRF 실패 |
| 프로필 조회 | `GET /profile/me` | 200 | 401 로그인 필요 |
| 프로필 수정 | `PATCH /profile/me` | 200 | 403 CSRF 실패, 422 입력 검증 |
| 패션 취향 조회 | `GET /preferences/me` | 200 | 401 로그인 필요 |
| 패션 취향 수정 | `PATCH /preferences/me` | 200 | 403 CSRF 실패, 422 입력 검증 |
| 회원 탈퇴 | `DELETE /auth/account` | 204 | 401 유효하지 않은 세션 사용자, 403 비밀번호·CSRF 실패 |
| 장소별 단기예보 | `GET /weather` | 200 | 401 로그인 필요, 404 장소 없음, 409 장소 모호, 422 날짜·예보 범위, 502 외부 API, 503 설정 누락 |
| Calendar OAuth 시작 | `POST /calendar/oauth/start` | 200 | 401 로그인 필요, 403 CSRF 실패, 503 설정 누락 |
| Calendar OAuth 콜백 | `GET /calendar/oauth/callback` | 200 | 400 거부·코드·state 오류, 502 Google 인증 오류 |
| Calendar 연결 상태 | `GET /calendar/connection` | 200 | 401 로그인 필요 |
| 날짜별 일정 | `GET /calendar/events?date=YYYY-MM-DD` | 200 | 409 미연결·재인증 필요, 429 호출 한도, 502 Google API 오류 |
| Calendar 연결 해제 | `DELETE /calendar/connection` | 204 | 403 CSRF 실패, 502 Google 권한 철회 미확인 |
| Agent 5 LOOK 추천 | `POST /agent/recommend` | 200 | 401 로그인, 403 CSRF, 409 Tool 연결·장소 모호, 422 Tool 인자, 502 외부 API·Tool 계획, 503 설정 누락 |

로그인 응답의 `csrf_token`은 로그아웃, 프로필·취향 수정, 회원 탈퇴, Agent 추천 요청에서 `X-CSRF-Token` 헤더로 전달합니다. 세션 쿠키의 유효시간은 2시간이며 `SameSite=Lax`가 적용됩니다.

회원 탈퇴는 비밀번호와 CSRF 토큰을 다시 검증한 뒤 `users` 행을 삭제하고 세션을 비웁니다. 현재 로컬 스키마에서 아래 6개 FK는 모두 `ON DELETE CASCADE`로 확인했습니다.

- `user_profiles.user_id`
- `user_preferences.user_id`
- `wardrobe_items.user_id`
- `feedback.user_id`
- `saved_outfits.user_id`
- `google_calendar_connections.user_id`

## 3. 프로젝트 구조

```text
backend/
├── .env.example                 # 커밋 가능한 환경변수 예시
├── .python-version              # Python 3.12
├── app/
│   ├── main.py                  # FastAPI 앱과 세션 미들웨어
│   ├── api/
│   │   ├── router.py            # v1 라우터 결합
│   │   └── v1/
│   │       ├── health.py        # 상태 확인
│   │       ├── auth.py          # 회원가입·로그인·로그아웃·탈퇴
│   │       ├── settings.py      # 프로필·패션 취향 조회·수정
│   │       ├── weather.py       # Location·Weather HTTP 라우트
│   │       ├── calendar.py      # Google OAuth·일정 조회·연결 해제 API
│   │       └── agent.py         # 인증된 5 LOOK 추천 API와 오류 매핑
│   ├── agent/
│   │   ├── contracts.py         # Tool 계획·고정 5 LOOK JSON 계약
│   │   ├── inference.py         # 교체 가능한 추론 인터페이스와 Mock 구현
│   │   ├── tool_registry.py     # Tool 허용 목록·인자 검증·실제 호출
│   │   ├── service.py           # Plan → Tool → Generate 오케스트레이션
│   │   └── tools/
│   │       ├── user_context.py  # get_user_context(db, user_id) Tool
│   │       ├── wardrobe.py      # get_wardrobe(db, user_id) Tool
│   │       ├── weather.py       # get_weather(place, date, time) Tool
│   │       └── calendar.py      # get_calendar_events(db, user_id, date) Tool
│   ├── services/
│   │   ├── location.py          # Kakao 장소 검색·동명 장소 판별
│   │   ├── weather.py           # 격자 변환·기상청 조회·정규화
│   │   ├── google_calendar.py   # OAuth·암호화 저장·갱신·Events API
│   │   └── errors.py            # 외부 API 키를 노출하지 않는 도메인 오류
│   └── core/
│       ├── config.py            # .env 로딩과 설정값
│       └── database.py          # Engine, Session, get_db
├── tests/
│   ├── test_health.py
│   ├── test_signup.py
│   ├── test_auth_session.py
│   ├── test_settings.py
│   ├── test_location_service.py
│   ├── test_weather_service.py
│   ├── test_weather_tool.py
│   ├── test_weather_api.py
│   ├── test_google_calendar_service.py
│   ├── test_calendar_api.py
│   ├── test_user_context_tool.py
│   ├── test_agent_core.py
│   └── test_agent_api.py
├── pyproject.toml               # pytest·Ruff 설정
├── requirements.txt             # 실행 의존성
└── requirements-dev.txt         # 테스트·정적 검사 의존성
```

## 4. 로컬 준비

### 4.1 Python과 PostgreSQL

확인한 개발 환경은 Python 3.12와 Homebrew PostgreSQL 15입니다.

```bash
brew install postgresql@15
brew services start postgresql@15
createdb ai_fashion_agent
```

이미 설치했다면 상태와 버전을 확인합니다.

```bash
psql --version
pg_isready
psql -d ai_fashion_agent -c '\dt'
```

현재 API가 기대하는 테이블은 다음 7개입니다.

```text
users
user_profiles
user_preferences
wardrobe_items
feedback
saved_outfits
google_calendar_connections
```

주의: 현재 저장소에는 DB 마이그레이션이나 초기 DDL 파일이 없습니다. 따라서 위 스키마가 준비된 로컬 DB가 필요합니다. 새 팀원 환경에서는 DB 스키마 담당자에게 같은 스키마를 전달받은 뒤 테이블과 FK를 확인해야 합니다.

### 4.2 가상환경과 패키지

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

`requirements-dev.txt`는 실행 의존성도 함께 설치합니다.

### 4.3 환경변수

실제 `.env`는 비밀번호와 비밀키가 들어갈 수 있으므로 Git에 커밋하지 않습니다. 예시 파일을 복사한 뒤 로컬 값만 채웁니다.

```bash
cp .env.example .env
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

출력된 난수를 `.env`의 `SESSION_SECRET_KEY`에 넣습니다.

```dotenv
# macOS 로컬 소켓과 현재 OS 사용자 역할을 이용하는 기본 예시
DATABASE_URL=postgresql+psycopg:///ai_fashion_agent
SESSION_SECRET_KEY=여기에_최소_32자_이상의_새_난수_입력

# localhost의 HTTP 개발 서버에서만 false
SESSION_COOKIE_SECURE=false

# Kakao Developers 앱의 REST API 키
KAKAO_REST_API_KEY=로컬에서_발급받은_키

# 공공데이터포털 기상청 단기예보 조회서비스의 일반 인증키
KMA_SERVICE_KEY=로컬에서_발급받은_키

# Google Cloud의 웹 OAuth 클라이언트 값
GOOGLE_CLIENT_ID=발급받은_클라이언트_ID
GOOGLE_CLIENT_SECRET=발급받은_클라이언트_보안_비밀번호
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/calendar/oauth/callback

# Google Token 암호화 전용 키. SESSION_SECRET_KEY와 같은 값을 쓰지 않습니다.
GOOGLE_TOKEN_ENCRYPTION_KEY=Fernet_키
```

Fernet 키는 의존성을 설치한 뒤 다음 명령으로 한 번 생성합니다. 출력값을 `backend/.env`에만 넣고 팀 공용 문서나 Git에 복사하지 않습니다.

```bash
.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

DB 사용자와 비밀번호를 명시해야 하는 환경은 다음 형태를 사용합니다. 실제 값은 문서나 Git에 남기지 않습니다.

```dotenv
DATABASE_URL=postgresql+psycopg://DB_USER:DB_PASSWORD@localhost:5432/ai_fashion_agent
```

- `SESSION_SECRET_KEY`가 없거나 32자 미만이면 서버는 시작하지 않습니다.
- HTTP 로컬 개발에서는 `SESSION_COOKIE_SECURE=false`가 필요합니다.
- HTTPS 환경에서는 `SESSION_COOKIE_SECURE=true`를 사용해야 합니다.
- 비밀키를 바꾸면 기존 세션 쿠키는 더 이상 유효하지 않습니다.
- `KAKAO_REST_API_KEY`, `KMA_SERVICE_KEY`가 없으면 서버 시작은 가능하지만 날씨 조회는 503을 반환합니다.
- 실제 키는 `.env`에만 저장하고 응답, 로그, README, 테스트 fixture에 넣지 않습니다.
- Google에서 다운로드한 OAuth JSON은 실행에 필요하지 않습니다. `client_id`와 `client_secret`만 `.env`로 옮긴 뒤 JSON은 저장소 밖의 안전한 위치에 보관합니다. 저장소는 `backend/client_secret*.json`, `credentials*.json`, `token*.json`, `.secrets/`를 추가로 무시합니다.
- `GOOGLE_TOKEN_ENCRYPTION_KEY`를 잃어버리거나 바꾸면 기존 토큰 암호문을 복호화할 수 없습니다. 키를 교체하려면 사용자가 Calendar를 다시 연결해야 합니다.

## 5. 서버 실행과 Swagger 확인

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --no-access-log
```

- API 루트: <http://localhost:8000/>
- Health Check: <http://localhost:8000/api/v1/health>
- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>

Swagger에서 인증 기능을 확인하는 순서는 다음과 같습니다.

1. `POST /api/v1/auth/signup`으로 12자 이상 비밀번호를 가진 테스트 계정을 만듭니다.
2. `POST /api/v1/auth/login` 응답의 `csrf_token`을 복사합니다. 브라우저는 `fashion_session` 쿠키를 보관합니다.
3. `GET /api/v1/auth/me`로 로그인 상태를 확인합니다.
4. PATCH·로그아웃·탈퇴 요청에서는 `X-CSRF-Token` 입력란에 토큰을 넣습니다.
5. `PATCH /api/v1/profile/me`와 `PATCH /api/v1/preferences/me`로 값을 저장한 뒤 GET으로 재조회합니다.
6. `GET /api/v1/weather?place=전주대학교&date=YYYY-MM-DD&time=HH:MM`으로 단기예보를 조회합니다. 날짜는 오늘부터 글피 범위의 미래 시각을 사용합니다.
7. 탈퇴 검증은 삭제해도 되는 테스트 계정에서만 수행합니다. `DELETE /api/v1/auth/account`에 현재 비밀번호와 CSRF 토큰을 전달하면 204가 반환되고, 이후 `/auth/me`는 401을 반환해야 합니다.

Calendar OAuth는 리디렉션 URI가 `localhost`로 등록되어 있으므로 Swagger와 API도 반드시 `http://localhost:8000`으로 엽니다. `127.0.0.1`에서 시작하면 호스트가 달라 세션 쿠키가 콜백에 전달되지 않고 state 검증이 실패할 수 있습니다.
OAuth 콜백 URL에는 일회용 인증 코드가 포함됩니다. 로컬 서버는 `--no-access-log`로 실행하고, 운영 환경에서도 해당 쿼리 문자열이 접속 로그에 남지 않도록 설정해야 합니다.

## 6. 실제 확인 결과

### 6.1 사용자가 Swagger에서 확인한 결과

2026-11-01 로컬 개발 환경에서 직접 확인한 관측값입니다.

- `GET /api/v1/profile/me` → 200
  - `gender: "male"`
  - `age_group: "20s"`
  - `height_cm: 175`
  - `body_type: "slim"`
  - `user_id: 9`
- `GET /api/v1/preferences/me` → 200
  - `preferred_styles: ["casual", "minimal"]`
  - `preferred_colors: ["black", "navy"]`
  - `disliked_colors: ["red"]`
  - `preferred_fit: "regular"`
- 프로필 PATCH와 패션 취향 PATCH → 각각 200
- `DELETE /api/v1/auth/account` → 204
- 탈퇴 직후 `GET /api/v1/auth/me` → 401
- PostgreSQL Engine 연결과 7개 테이블 조회 성공

위 결과는 해당 시점의 테스트 계정과 로컬 DB에서 확인한 값입니다. 다른 계정·DB 또는 운영 환경에서도 항상 같은 데이터가 나온다는 의미는 아닙니다.

### 6.2 자동 테스트 재실행 결과

2026-11-01 현재 로컬 PostgreSQL에 연결해 전체 테스트를 다시 실행했습니다.

```text
7 passed, 1 warning
```

경고 1건은 현재 FastAPI/Starlette `TestClient`가 `httpx` 사용 방식의 향후 변경을 알리는 `StarletteDeprecationWarning`입니다. 테스트 실패는 아니지만, 의존성 업데이트 시 `TestClient` 호환성을 다시 확인해야 합니다.

검증 범위는 다음과 같습니다.

- 루트·Health Check 200
- 회원가입 201, 중복 이메일 409, 잘못된 이메일 422
- 비밀번호가 해시로 저장되는지 확인
- 로그인 전 접근 401, 로그인 200, 쿠키 세션 유지
- CSRF 없는 로그아웃·수정 요청 403, 정상 로그아웃 204
- 프로필·패션 취향 저장과 사용자별 데이터 격리
- 잘못된 프로필 값 422
- 잘못된 비밀번호·CSRF로 회원 탈퇴 차단 403
- 정상 회원 탈퇴 204, 세션 해제 후 401
- 탈퇴 후 사용자·연관 행 조회 결과 0

테스트는 로컬 PostgreSQL의 실제 스키마를 사용하되, 바깥 트랜잭션과 savepoint를 이용해 테스트가 만든 데이터를 마지막에 롤백합니다.

## 7. 테스트와 정적 검사

PostgreSQL 서비스와 7개 테이블이 준비된 상태에서 실행합니다.

```bash
cd backend
source .venv/bin/activate
pytest -q
ruff check .
```

테스트 실패 시 먼저 다음을 확인합니다.

```bash
pg_isready
psql -d ai_fashion_agent -c '\dt'
```

## 8. 주의사항과 현재 한계

- `.env`, `.venv`, `__pycache__`, 테스트 캐시와 실제 비밀번호·비밀키는 커밋하지 않습니다.
- 세션 쿠키는 서명되지만 암호화되지 않으므로 민감정보를 세션에 넣지 않습니다. 현재는 사용자 ID와 CSRF 토큰만 저장합니다.
- 상태 변경 요청에는 세션 쿠키와 올바른 `X-CSRF-Token`이 모두 필요합니다.
- 회원 탈퇴는 되돌릴 수 없으므로 테스트 전용 계정으로만 확인합니다.
- 현재 코드에는 DB 마이그레이션, 운영용 비밀 관리, HTTPS 종료, CORS 정책, rate limit, 감사 로그가 포함되어 있지 않습니다.
- 테스트는 로컬 개발 검증입니다. 운영 배포 검증이나 부하·침투 테스트를 대신하지 않습니다.
- JWT는 이번 범위에서 의도적으로 제외했습니다. 별도 요구사항 없이 추가하지 않습니다.

## 9. 팀원 인계 순서

1. `feature/fastapi-postgresql` 브랜치를 받아 `backend/`에서 작업합니다.
2. Python 3.12와 PostgreSQL 15를 준비합니다.
3. 동일한 7개 테이블과 FK `ON DELETE CASCADE`가 적용된 `ai_fashion_agent` DB를 전달받습니다.
4. `.env.example`을 `.env`로 복사하고 각자 새 세션 비밀키를 만듭니다.
5. `requirements-dev.txt`를 설치하고 `pytest -q`, `ruff check .`을 실행합니다.
6. Uvicorn을 시작하고 Swagger에서 회원가입 → 로그인 → 프로필·취향 → 로그아웃 순서로 확인합니다.
7. 회원 탈퇴 검증은 삭제 가능한 테스트 계정에서만 마지막에 수행합니다.

인계 시에는 테스트 통과 여부와 함께 사용한 Python/PostgreSQL 버전, 스키마 준비 방식, 환경변수 이름만 공유하고 실제 비밀번호와 비밀키는 공유 문서나 Git에 남기지 않습니다.


## WBS 4.2 — Wardrobe CRUD

### 구현 기능
- 사용자별 옷장 데이터 등록·조회·수정·삭제
- 의류 속성 관리: category, item_type, color, fit, seasons
- 선택적 의류 이미지 업로드 및 관리
- 이미지 크기·형식·유효성 검사
- 사용자 인증 및 본인 소유 데이터 접근 제한
- 회원 탈퇴 시 관련 의류 데이터와 이미지 파일 정리
- 비밀번호 검증 실패 시 계정과 이미지 보존
- Agent 연동을 위한 `get_wardrobe()` Tool 구조 준비

### 주요 기술
| 기술 | 역할 |
|---|---|
| FastAPI | Wardrobe REST API |
| PostgreSQL | 의류 데이터 영구 저장 |
| SQLAlchemy | 데이터베이스 연결 및 SQL 처리 |
| Pillow | 이미지 유효성 검사 |
| python-multipart | 이미지 업로드 처리 |
| pytest | API 자동화 테스트 |
| Ruff | Python 코드 정적 검사 |

### 테스트 실행
프로젝트의 `backend` 디렉터리에서 실행합니다.

```bash
.venv/bin/ruff check app tests
.venv/bin/python -m pytest -q
```

### 검증 결과
- Ruff: All checks passed
- pytest: 12 passed, 1 warning
- 옷장 CRUD 및 이미지 관련 자동화 테스트 통과
- 회원 탈퇴 시 이미지 삭제 테스트 통과
- 잘못된 비밀번호로 탈퇴할 경우 계정 및 이미지 보존 테스트 통과

검증 결과는 로컬 개발 환경 기준입니다.
Agent의 실제 모델 연동과 전체 서비스 통합 검증은 후속 단계에서 진행합니다.

## WBS 4.3 — Location·Weather Tool

### 처리 흐름

```text
get_weather(place, date, time)
  → Kakao 키워드 장소 검색
  → 위도·경도를 기상청 nx·ny 격자로 변환
  → 안전 지연 25분을 반영한 최신 단기예보 발표시각 선택
  → 요청 날짜에서 가장 가까운 시간별 예보 선택
  → Agent용 6개 필드로 정규화
```

Tool과 `GET /api/v1/weather`는 다음 필드를 반환합니다.

```json
{
  "temperature_c": 7,
  "precipitation_probability": 0,
  "precipitation_type": "none",
  "wind_mps": 0.2,
  "humidity_percent": 80,
  "sky": "clear"
}
```

- 날짜는 `YYYY-MM-DD`, 시간은 `HH:MM` 형식이며 Asia/Seoul 기준입니다.
- 분 단위 시각은 요청 날짜 안에서 가장 가까운 기상청 시간별 예보를 사용합니다.
- 과거 1시간보다 이전 또는 오늘 기준 글피 이후의 시각은 조회하지 않습니다.
- 검색어와 정확히 일치하는 장소가 하나면 선택합니다. 동명 장소가 여러 개이거나 정확히 일치하지 않는 후보가 여러 개면 409와 이름·주소 후보를 반환하며 임의로 고르지 않습니다.
- 정확한 좌표, Kakao 장소 ID, API 키는 Agent Tool 응답에 포함하지 않습니다.
- 기상청 API 실패 시 날씨를 추측하거나 생성하지 않고 오류를 반환합니다.

### 검증 범위

자동 테스트는 실제 외부 API를 호출하지 않습니다. Kakao·기상청 응답을 mock하여 다음을 검증합니다.

- 전주대학교 좌표 `(35.814114..., 127.089881...)`가 기상청 격자 `nx=62`, `ny=89`로 변환됨
- Kakao 인증 헤더와 장소 응답 파싱
- 동명 장소, 검색 결과 없음, 잘못된 날짜·시간, 과거·예보 범위 밖 요청 차단
- 기상청 발표시각, 동일 날짜의 최근접 예보, 코드·수치 정규화
- FastAPI 200/409/502 응답 매핑
- 오류 메시지에 API 키가 포함되지 않음

2026-11-02 현재 검증 결과는 다음과 같습니다.

- Location·Weather 범위 테스트: `16 passed, 1 warning`
- PostgreSQL을 포함한 전체 백엔드 테스트: `28 passed, 1 warning`
- Ruff 검사: `All checks passed`
- 이번에 변경한 Python 파일의 Ruff format 검사: `11 files already formatted`

경고 1건은 기존 `TestClient`와 `httpx` 조합의 향후 변경을 알리는 `StarletteDeprecationWarning`이며 테스트 실패는 아닙니다.

2026-11-02 사용자가 로컬에서 별도로 확인한 관측값은 Kakao 장소 검색 200, 전주대학교 위·경도 조회, `nx=62`·`ny=89` 변환, 기상청 단기예보 200 및 정상 데이터 응답입니다. 이는 해당 시점의 키·외부 서비스 상태 확인이며 자동 테스트나 운영 가용성 보장은 아닙니다.

## WBS 4.4 — Google Calendar OAuth·일정 조회

### 처리 흐름

```text
서비스 로그인 + X-CSRF-Token
  → POST /calendar/oauth/start
  → 일회용 state를 서명된 세션에 사용자 ID·시작시각과 함께 저장
  → Google 계정 선택·동의 화면
  → GET /calendar/oauth/callback
  → state·사용자·10분 만료 검증 후 인증 코드를 Token으로 교환
  → Access/Refresh Token을 Fernet 암호문으로 사용자별 DB 1행에 저장
  → get_calendar_events(db, user_id, date)
  → 만료 임박 Token 자동 갱신 후 primary Calendar 일정 조회
```

- 요청 범위는 `https://www.googleapis.com/auth/calendar.events.readonly` 하나입니다. 일정 생성·수정·삭제 권한은 요청하지 않습니다.
- `prompt=consent select_account`를 사용해 매 연결마다 사용자가 Google 계정을 직접 고르고 동의하도록 합니다.
- OAuth `state`는 일회용이며 서비스 로그인 사용자와 묶고 10분 뒤 만료합니다. 콜백 성공·실패와 관계없이 한 번 확인한 state는 재사용할 수 없습니다.
- Access/Refresh Token은 API 응답·로그·세션 쿠키에 넣지 않습니다. DB의 `access_token_encrypted`, `refresh_token_encrypted`에는 별도 Fernet 키로 만든 암호문만 저장합니다.
- 서비스 계정 간 연결은 `google_calendar_connections.user_id UNIQUE`와 모든 조회의 `WHERE user_id = :user_id`로 격리합니다.
- 최소 범위를 유지하기 위해 Google 이메일/OpenID 범위를 추가하지 않았습니다. 따라서 `google_account_email`은 `NULL`이며, 이 단계의 계정 분리는 Google 이메일 수집이 아니라 서비스 사용자별 Token 격리를 뜻합니다.
- Access Token이 만료 임박했거나 Google API가 401을 반환하면 Refresh Token으로 한 번 갱신하고 DB의 새 암호문·만료시각을 저장한 뒤 재시도합니다. `invalid_grant` 또는 권한 취소는 일정을 추측하지 않고 재연결 필요 오류로 반환합니다.
- 연결 해제는 Google 토큰 철회를 먼저 시도한 뒤 로컬 암호문을 삭제합니다. Google에 연결할 수 없더라도 로컬 Token은 삭제하며, 이 경우 502로 Google 계정 보안 설정에서 권한을 확인하도록 알립니다.
- 일정은 한국 시간 기준 하루를 조회하고 반복 일정을 개별 인스턴스로 펼칩니다. 제목·시작·종료·종일 여부·장소만 반환하며 참석자, 설명, 화상회의 링크는 요청하지 않습니다.

### Swagger에서 연결 확인

1. `http://localhost:8000/docs`에서 회원가입·로그인하고 `csrf_token`을 복사합니다.
2. `POST /api/v1/calendar/oauth/start`의 `X-CSRF-Token`에 값을 넣어 실행합니다.
3. 응답의 `authorization_url`을 같은 브라우저에서 엽니다. 테스트 사용자로 등록한 Google 계정을 선택하고 일정 읽기 권한에 동의합니다.
4. Google이 `http://localhost:8000/api/v1/calendar/oauth/callback`으로 돌아오면 `connected: true`를 확인합니다.
5. `GET /api/v1/calendar/connection`으로 현재 서비스 사용자의 연결 상태를 확인합니다.
6. `GET /api/v1/calendar/events?date=2026-11-03`처럼 날짜를 넣어 해당 날짜의 일정을 읽습니다.
7. 연결 해제는 `DELETE /api/v1/calendar/connection`에 현재 `X-CSRF-Token`을 넣어 실행합니다.

OAuth JSON, Client Secret, 실제 Token, `GOOGLE_TOKEN_ENCRYPTION_KEY`는 화면 캡처·채팅·이슈·커밋에 넣지 않습니다. 테스트는 실제 Google 계정을 호출하지 않고 `httpx.MockTransport`를 사용합니다.

### 자동 검증 범위

- 정확한 읽기 전용 범위, offline access, 계정 선택, state 전달
- 잘못되거나 재사용된 state, 사용자 동의 거부, 미연결 상태
- 인증 코드 교환, 만료 Token 갱신, 401 후 한 번만 갱신·재시도
- Token 평문이 DB에 남지 않는지와 서비스 사용자 간 연결 격리
- 날짜 범위·반복 일정 페이지네이션·취소 일정 제외·최소 응답 필드
- 401/403/429/5xx·잘못된 응답 형식·네트워크 오류의 안전한 매핑
- 연결 해제와 Google 철회 실패 시에도 로컬 암호문 삭제

2026-11-03 현재 Calendar 범위 자동 테스트는 `19 passed, 1 warning`, PostgreSQL을 포함한 전체 백엔드 테스트는 `47 passed, 1 warning`입니다. Ruff 검사와 이번 변경 파일의 Ruff format 검사도 통과했습니다. 실제 Google 동의 화면과 실제 일정 조회는 사용자의 로컬 테스트 계정으로 별도 확인해야 하며, 자동 테스트 통과가 Google Cloud 설정이나 외부 서비스 가용성을 보장하지는 않습니다.

## WBS 4.5 — Agent Core·Tool Calling

### 현재 구현 범위

```text
POST /api/v1/agent/recommend
  → 쿠키 세션 사용자 + X-CSRF-Token 검증
  → MockInferenceEngine.plan()
  → 허용된 Tool 이름·중복·인자 전체 선검증
  → 필요한 실제 Tool만 순서대로 실행
  → MockInferenceEngine.generate()
  → 정확히 5개 LOOK과 고정 역할·옷장 ID 검증
  → 검증된 옷장 항목에만 Backend가 사진 URL 연결
  → AgentRecommendationResponse JSON
```

Router가 허용하는 Tool은 다음 4개뿐입니다.

| Tool | 공개 인자 | Backend가 주입하는 값 |
|---|---|---|
| `get_user_context()` | 없음 | `db`, 인증된 `user_id` |
| `get_wardrobe()` | 없음 | `db`, 인증된 `user_id` |
| `get_weather()` | `place`, `date`, `time` | 없음 |
| `get_calendar_events()` | `date` | `db`, 인증된 `user_id` |

- 통합 5 LOOK 추천은 `get_user_context()`와 `get_wardrobe()`를 기본 호출합니다.
- 날씨·일정은 요청에 해당 의도가 있을 때만 호출합니다.
- 사용자가 “날씨를 다시 조회하지 말라”고 명시하면 날씨 Tool을 호출하지 않습니다.
- Tool 계획은 전부 검증한 뒤 실행하므로 뒤쪽 호출의 인자가 잘못된 경우 앞쪽 Tool도 실행하지 않습니다.
- 현재 Mock Router는 날짜·시간을 구조화 필드 또는 `YYYY-MM-DD`, `HH:MM` 문자열에서만 읽습니다. “내일”, “저녁” 같은 상대 표현 해석과 Calendar 결과 장소를 이용한 후속 Weather 호출은 최종 모델/날짜 해석기 연동 단계에서 보강해야 합니다.

요청 예시는 다음과 같습니다.

```json
{
  "message": "내 옷으로 내일 서울역 날씨에 맞는 출근 코디를 추천해줘",
  "place": "서울역",
  "date": "2026-11-04",
  "time": "08:30"
}
```

응답에는 `action: "generate_five_looks"`와 고정 순서의 LOOK 5개가 포함됩니다. 학습 데이터의 `look_id / role / status / style / items / reason` 구조를 따릅니다.

1. `preference_best`: 사용자 취향 최적
2. `preference_alternative`: 취향 범위의 다른 조합
3. `exploration`: 새로운 스타일 탐색
4. `wardrobe_best`: 실제 보유 의류의 최적 조합
5. `wardrobe_alternative`: 실제 보유 의류의 다른 조합

`available` LOOK에는 `top`, `bottom`, `shoes` 아이템이 각각 하나씩 필요합니다. 1~3번 아이템의 `item_id`는 `null`이며, 4~5번은 실제 사용자 옷장의 ID만 허용합니다. Mock을 포함한 모델 출력에는 사진 URL을 넣지 않습니다. Backend가 옷장 `item_id`와 `slot`을 확인한 뒤 등록된 사진 URL만 최종 응답에 붙이며, 모델이 직접 만든 URL은 거부합니다. 완성 코디를 만들 수 없거나 두 번째 조합이 없으면 `status: "unavailable"`, `style: null`, `items: []`와 이유를 반환합니다. “내 옷만” 요청에서는 일반 추천 1~3번도 사용 불가로 표시합니다. 별도의 피드백·저장 기능은 4.6 범위입니다.

### 최종 Qwen3 모델 교체 지점

`InferenceEngine`은 `plan(request)`와 `generate(request, tool_results)`를 정의합니다. 현재 FastAPI 의존성 `get_agent_service()`가 `MockInferenceEngine`을 주입합니다. 진호의 학습 모델이 준비되면 모델 호출·응답 파싱을 담당하는 구현을 만들고 이 주입 지점에서 연결합니다. Tool Registry, 인증, 실제 Tool과 5 LOOK 응답 계약은 그대로 사용합니다.

학습 데이터 가이드의 `generate_five_looks` 계약을 서비스 API에도 적용했습니다. WBS의 기존 3 LOOK 문구보다 확정된 5 LOOK 기준을 우선합니다.

### 4.5 남은 작업과 인계 순서

2026-11-03 기준 Mock Agent를 통한 Router·Tool Calling, 실제 4개 Tool 연결, 고정 5 LOOK JSON, Backend 사진 URL 연결과 자동 테스트까지 확인했습니다. 아래 자동 검증 결과는 **학습 모델의 실제 추론 결과를 검증한 것이 아닙니다.** 모델 통합 전에는 4.5를 완료로 표시하지 않습니다.

**학습 완료 전 준비할 일**

1. 진호와 모델 인계 형식을 맞춥니다. 실제 기반 모델·학습 산출물 버전, 토크나이저와 채팅 템플릿, 모델 로딩 또는 추론 서버 방식, 실행 환경을 확인합니다. 특히 모델이 요청을 받아 Tool 계획을 먼저 만들고, Tool 결과를 받은 뒤 최종 추천을 생성할 수 있는지 확인합니다. 체크포인트나 접속 정보의 실제 값은 README에 적지 않습니다.
2. [Agent 계약 파일](app/agent/contracts.py)을 공통 계약으로 전달합니다. `plan()`은 허용된 4개 Tool의 이름과 공개 인자만 담은 `AgentPlan`을, `generate()`는 `AgentDraft`를 반환해야 합니다. `db`와 인증된 `user_id`는 Backend가 주입하므로 모델 출력에 넣지 않습니다. 최종 응답은 `generate_five_looks`와 고정 순서의 5 LOOK을 사용합니다.
3. 실모델 테스트용 사례와 예상 결과를 준비합니다. 기본 추천, 날씨만 필요한 요청, 일정만 필요한 요청, 날씨 조회 거부, “내 옷만”, 옷장 완성 조합 0·1·2개, 잘못된 Tool 이름·인자, 잘못된 JSON·옷장 ID를 포함합니다. 기존 Mock 테스트와 별도로 모델 응답을 흉내 낸 fixture를 이용해 계약·오류 처리를 검증할 수 있습니다.
4. 현재 작업 브랜치의 변경 사항을 팀 기준에 따라 리뷰·커밋·병합하고, WBS와 화면 담당자에게 **3 LOOK이 아닌 5 LOOK** 계약을 전달합니다. 이 전달 작업은 모델 학습 완료를 기다릴 필요가 없습니다.

**학습 모델을 받은 뒤 해야 할 일**

1. 모델 어댑터에서 프롬프트·Tool 정의를 전달하고 모델 응답을 `AgentPlan`과 `AgentDraft`로 파싱·검증합니다. `get_agent_service()`의 Mock 주입을 이 어댑터로 바꿉니다. 현재 흐름은 `plan → Tool 실행 → generate` 한 번씩이므로, 모델이 중간 Tool 결과를 보고 추가 Tool을 선택하는 방식이라면 서비스 흐름과 테스트도 확장해야 합니다.
2. 상대 날짜·시간 표현을 실제 날짜·시각으로 해석해 Tool 인자에 넣을 방법을 정하고 검증합니다. 일정에서 얻은 장소로 날씨를 다시 조회하는 흐름은 현재 한 번의 Tool 계획으로 처리하지 못하므로, 필요하면 WBS 6.5 통합 작업과 맞춰 구현합니다.
3. 실제 모델로 로그인·옷장·Tool 호출·5 LOOK 응답을 끝까지 시험합니다. 요청별 Tool 선택, 인자, 5개 역할 순서, 일반 LOOK의 `item_id: null`, 실제 옷장 ID·사진 연결과 서로 다른 4·5번 조합, 만들 수 없는 LOOK의 `unavailable`을 확인합니다. 외부 API는 먼저 mock으로 재현하고, 실제 계정·API를 쓰는 확인은 별도로 진행합니다.
4. 모델 응답 지연·실패, 잘못된 JSON·Tool 호출, 외부 Tool 오류의 처리 방식과 추론 시간·메모리 사용량을 확인합니다. 테스트한 모델 버전, 입력 사례, 호출 Tool, 결과, 실패 사례를 비밀키·OAuth Token 없이 인계 기록에 남깁니다.

**4.5 완료 기준:** 실제 학습 모델이 Backend에 연결되고, 필요한 Tool만 안전하게 호출하며, 위 정상·예외 사례에서 계약에 맞는 5 LOOK 또는 명확한 오류를 반환해야 합니다. Mock 테스트만 통과하거나 모델 파일만 전달받은 상태는 완료 근거가 아닙니다. 피드백·저장 기능은 WBS 4.6 범위입니다.

현재 Mock 단계는 위 4절의 로컬 환경과 PostgreSQL을 준비한 뒤 `backend` 디렉터리에서 재검증할 수 있습니다. 모델 어댑터를 추가하면 같은 명령으로 기존 기능의 회귀 여부를 확인하고, 실제 모델 통합 테스트를 별도로 실행합니다.

```bash
.venv/bin/ruff check app tests
.venv/bin/python -m pytest -q
```

### 자동 검증 결과

2026-11-03 현재 확인 결과입니다.

- 전체 백엔드 테스트: `68 passed, 1 warning`
- Ruff: `All checks passed!`
- 기존 47개 테스트와 Agent Core·Tool·API 신규 21개 테스트를 함께 실행
- 등록 사진 업로드 → 옷장 Tool → Agent 응답의 사진 URL 연결을 PostgreSQL 통합 테스트로 확인
- PostgreSQL 통합 테스트는 트랜잭션 롤백으로 테스트 사용자·옷장 데이터를 남기지 않음
- 네 Tool 어댑터는 외부 네트워크 대신 mock 함수로 전달 인자와 호출 순서를 검증
- Weather·Calendar 자체 외부 API 동작은 기존 `httpx.MockTransport` 테스트가 담당

경고 1건은 기존 `TestClient`와 `httpx` 조합의 `StarletteDeprecationWarning`입니다. 실제 Qwen3 추론 품질·속도·메모리, 실제 Kakao·기상청·Google API 가용성, 상대 날짜 해석은 이 자동 테스트 결과에 포함되지 않습니다.
