# AI Fashion Agent Backend

Qwen3-4B 기반 개인화 패션 추천 서비스의 FastAPI 백엔드입니다. PostgreSQL 기반 회원·프로필·옷장 기능과 WBS 4.3 Location·Weather Tool을 포함합니다.

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

로그인 응답의 `csrf_token`은 로그아웃, 프로필·취향 수정, 회원 탈퇴 요청에서 `X-CSRF-Token` 헤더로 전달합니다. 세션 쿠키의 유효시간은 2시간이며 `SameSite=Lax`가 적용됩니다.

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
│   │       └── weather.py       # Location·Weather HTTP 라우트
│   ├── agent/tools/
│   │   └── weather.py           # get_weather(place, date, time) Tool
│   ├── services/
│   │   ├── location.py          # Kakao 장소 검색·동명 장소 판별
│   │   ├── weather.py           # 격자 변환·기상청 조회·정규화
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
│   └── test_weather_api.py
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

## 5. 서버 실행과 Swagger 확인

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

- API 루트: <http://127.0.0.1:8000/>
- Health Check: <http://127.0.0.1:8000/api/v1/health>
- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>

Swagger에서 인증 기능을 확인하는 순서는 다음과 같습니다.

1. `POST /api/v1/auth/signup`으로 12자 이상 비밀번호를 가진 테스트 계정을 만듭니다.
2. `POST /api/v1/auth/login` 응답의 `csrf_token`을 복사합니다. 브라우저는 `fashion_session` 쿠키를 보관합니다.
3. `GET /api/v1/auth/me`로 로그인 상태를 확인합니다.
4. PATCH·로그아웃·탈퇴 요청에서는 `X-CSRF-Token` 입력란에 토큰을 넣습니다.
5. `PATCH /api/v1/profile/me`와 `PATCH /api/v1/preferences/me`로 값을 저장한 뒤 GET으로 재조회합니다.
6. `GET /api/v1/weather?place=전주대학교&date=YYYY-MM-DD&time=HH:MM`으로 단기예보를 조회합니다. 날짜는 오늘부터 글피 범위의 미래 시각을 사용합니다.
7. 탈퇴 검증은 삭제해도 되는 테스트 계정에서만 수행합니다. `DELETE /api/v1/auth/account`에 현재 비밀번호와 CSRF 토큰을 전달하면 204가 반환되고, 이후 `/auth/me`는 401을 반환해야 합니다.

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
