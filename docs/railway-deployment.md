# CLOMORI Railway 배포 절차

이 절차는 웹과 PostgreSQL을 같은 Railway 환경에 두고, 옷장 사진용 볼륨 하나를 웹에 연결하는 구성이다. 웹 이미지가 프런트엔드와 FastAPI를 함께 제공한다. 첫 배포는 Mock 추천으로 검증한다.

## 1. 배포 소스와 대시보드

1. 배포 승인을 받은 뒤 배포할 브랜치·커밋을 확인한다. 그 커밋에 루트 Dockerfile, .dockerignore, backend/app/web.py, DB 초기화 모듈, baseline SQL, readiness 코드가 모두 있어야 한다. Mac의 미추적 파일은 Git 소스 배포에 포함되지 않는다.
2. 결제 후 사용할 프로젝트·환경을 선택한다. 동일 환경에 전용 PostgreSQL 서비스(로컬 검증 기준 메이저 버전 15)와 웹 서비스를 구성한다. 기존 DB를 선택했다면 아래의 **기존 DB** 절차로 진행한다.
3. Git 소스는 `feature/clomori-deployment-kwak` 또는 해당 변경을 포함하도록 승인된 브랜치, Root Directory는 저장소 루트 `/`로 설정한다. Dockerfile 자동 감지를 사용하고 Build/Start Command 재정의는 비워 둔다. 시작 명령은 Railway가 주입하는 `PORT`에서 모든 인터페이스를 수신한다.
4. 웹에 영구 볼륨 한 개를 `/app/.wardrobe_media`로 마운트하고 아래 환경변수를 설정한다. DB 저장소는 PostgreSQL 서비스에서 관리한다. 웹은 한 인스턴스로 시작한다. 새 볼륨은 비어 있다.
5. 웹의 Healthcheck Path를 `/api/v1/health/ready`로 설정한다. 웹에만 공개 HTTPS 도메인을 연결한다. DB는 사설망에서 접근한다.

| 웹 서비스 변수 | 설정 |
| --- | --- |
| `DATABASE_URL` | 같은 환경의 DB 서비스 참조. 서비스 이름이 Postgres일 때 `${{Postgres.DATABASE_URL}}`. 드라이버는 앱이 psycopg 3으로 지정한다. |
| `SESSION_SECRET_KEY` | 암호학적으로 무작위인 32자 이상 고정값. 로컬 테스트값을 재사용하지 않고 서버의 비밀 변수에 저장한다. 변경 시 기존 세션이 만료된다. |
| `SESSION_COOKIE_SECURE` | 운영 HTTPS에서는 `true`. 같은 도메인의 프런트엔드가 HttpOnly·SameSite=Lax 쿠키로 로그인하고, 상태 변경 요청에 `X-CSRF-Token`을 보낸다. 세션 유효 시간은 2시간이다. |
| `WARDROBE_MEDIA_ROOT` | `/app/.wardrobe_media` (위 웹 볼륨 경로와 일치). 사용자 이미지는 소유권 확인 API가 제공한다. |
| `AGENT_INFERENCE_PROVIDER` | 첫 배포는 `mock`. 모델 서버 검증 후 별도로 `qwen`으로 바꾼다. |

## 2. 첫 배포와 이후 재배포

**새 DB**에서는 웹 서비스의 Pre-deploy Command를 첫 배포에 한해 다음과 같이 지정한다. 실행 위치는 이미지의 기본 디렉터리인 `/app/backend`다. 대상이 맞는지 대시보드의 프로젝트·환경·DB 서비스 참조로 확인한다.

```sh
python -m app.init_db
```

초기화는 이미지 안의 SQL을 읽어 지정한 DB의 빈 상태를 확인하고 001~003까지 한 트랜잭션으로 적용한다. 종료 코드 0과 기준 버전 003을 확인한다. 비어 있지 않은 DB, 중복 실행, 연결 오류는 0이 아닌 코드로 종료한다. **첫 성공 후에는 다음 배포 전에 Pre-deploy Command를 지우고 변경을 저장한다.** 초기화는 완료됐지만 웹 배포가 실패한 경우에도 DB 상태를 먼저 확인하고 명령을 제거한 뒤 웹 설정을 수정한다. 해당 명령을 상시 등록하면 이후 배포가 중복 초기화 보호로 중단된다. 볼륨은 Pre-deploy 단계에서 마운트되지 않으며 사진 작업은 웹 실행 단계에서 이루어진다.

**기존 DB 또는 부분 초기화 DB**에서는 Pre-deploy Command를 비워 둔다. 복구 가능한 백업을 확인하고 적용 이력과 실제 제약·인덱스 정의를 대조한 뒤, 복제 DB에서 검증한 누락 증분만 적용한다. 이미 003까지 반영됐으면 스키마 작업 없이 배포한다. 자세한 판별 기준은 [PostgreSQL 마이그레이션 절차](../backend/migrations/README.md)를 따른다. 사용자 행이 포함된 Mac 덤프나 사진을 운영 초기 데이터로 사용하지 않는다.

## 3. 외부 기능별 변수

| 기능 | Railway 및 공급자 설정 |
| --- | --- |
| Google Calendar | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_TOKEN_ENCRYPTION_KEY`(세션 키와 별도로 생성한 고정 Fernet 키), `GOOGLE_REDIRECT_URI=https://<웹 도메인>/api/v1/calendar/oauth/callback`. Google Cloud에서 Calendar API와 웹 OAuth 클라이언트를 설정하고 완전히 동일한 HTTPS 콜백을 등록한다. 동의 화면과 테스트 사용자를 확인한 뒤 허용된 계정으로 연결·일정 조회를 검증한다. 암호화 키 교체는 저장 토큰의 재암호화 또는 재연결을 계획한 후 진행한다. |
| 장소·날씨 | `KAKAO_REST_API_KEY`에 Kakao Local REST API 키, `KMA_SERVICE_KEY`에 기상청 단기예보 서비스 키를 설정한다. 두 서비스의 권한과 할당량을 확인하고 위치·날짜가 있는 요청으로 검증한다. |
| 쇼핑 이미지 | 기본 `SERPAPI_IMAGE_SEARCH_ENABLED=false`. 활성화 시 서버에 `SERPAPI_API_KEY`, `SERPAPI_IMAGE_SEARCH_ENABLED=true`, `SERPAPI_TIMEOUT_SECONDS=8`을 설정한다. 검색 할당량과 이미지 사용 조건을 확인한다. 옷장 사진 조회는 이 키를 사용하지 않는다. |
| Qwen | 모델 확인 전 `AGENT_INFERENCE_PROVIDER=mock`. 이후 `QWEN_BASE_URL=https://<pod-id>-<공개 HTTP 포트>.proxy.runpod.net/v1`, `QWEN_MODEL=clomori-fashion-v2`, `QWEN_API_KEY=<모델 서버의 비밀 토큰>`으로 설정하고 provider를 `qwen`으로 전환한다. 초기값은 `QWEN_RESPONSE_FORMAT=json_schema`, `QWEN_SEND_CHAT_TEMPLATE_KWARGS=true`, `QWEN_TIMEOUT_SECONDS=60`, `QWEN_MAX_TOKENS=1600`, `QWEN_TEMPERATURE=0.35`, `QWEN_TOP_P=0.9`, `QWEN_REPETITION_PENALTY=1.08`, `QWEN_MAX_INPUT_CHARS=60000`, `QWEN_MAX_RESPONSE_BYTES=524288`이다. 도구 조회를 포함한 프런트 제한은 90초다. [모델 서버 실행](qwen-runpod.md) · [실제 추천 확인](qwen-integration.md) |

실제 키는 서버의 서비스 변수에서 관리한다. 프런트엔드, Docker 빌드 인자, Git, 배포 로그에 넣지 않는다. OAuth 콜백의 쿼리, 요청 본문, DB URL이 출력되지 않게 프록시·외부 관측 도구의 로그 설정도 점검한다. 자동으로 발급된 도메인을 바꾸면 Google 콜백 설정 두 곳도 함께 갱신한다.

## 4. 공개 전 확인

- `GET /api/v1/health`는 프로세스 상태를 나타낸다. `GET /api/v1/health/ready`는 DB와 필수 테이블 8개가 준비되면 200, 연결 실패·테이블 누락이면 503이다. 외부 API와 모델 상태는 각 기능으로 별도 확인한다.
- HTTPS 도메인에서 합성 계정으로 가입·로그인하고 프로필 저장, 옷 등록 및 테스트 사진 조회, Mock 추천 5개, 코디 저장·재조회를 확인한다. 테스트값·쿠키·토큰을 로그나 화면 공유에 노출하지 않는다.
- Pre-deploy 초기화 명령이 제거됐는지 확인한 뒤 같은 볼륨으로 웹을 재배포한다. 재로그인 후 옷장 사진과 저장 코디가 유지되는지 확인하고 DB·사진 볼륨의 백업 및 복구 절차를 정한다.
- 외부 기능은 필요한 것부터 하나씩 켜고 정상 요청과 실패 시 응답을 확인한다. 실모델 확인 전에는 추천 결과를 Mock으로 기록한다.
- Railway에서 저장소 Dockerfile을 빌드하면 Mac CPU에 의존하지 않는다. 추후 자체 레지스트리 이미지를 사용할 때에는 `linux/amd64`를 포함해 빌드·확인한다.

공식 문서: [Dockerfile 빌드](https://docs.railway.com/builds/dockerfiles) · [PostgreSQL 연결](https://docs.railway.com/databases/postgresql) · [Pre-deploy](https://docs.railway.com/deployments/pre-deploy-command) · [Health Check](https://docs.railway.com/deployments/healthchecks) · [볼륨](https://docs.railway.com/volumes) · [Google OAuth 콜백](https://developers.google.com/identity/protocols/oauth2/web-server).
