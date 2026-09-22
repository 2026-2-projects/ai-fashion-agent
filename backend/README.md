# Backend

FastAPI 기반 Backend 기본 프로젝트입니다.

## 실행

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

서버 실행 후 다음 주소를 사용할 수 있습니다.

- API: <http://localhost:8000>
- Health Check: <http://localhost:8000/api/v1/health>
- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>

## 테스트

```bash
pytest
ruff check .
```

## Google Calendar 연동 검증 (WBS 2.5)

로컬 개발자 1인의 기본 캘린더를 읽는 검증 도구입니다. 웹 연결 화면,
사용자별 토큰 DB 저장, 공개 HTTP 엔드포인트는 제공하지 않습니다.
일정 생성·수정·삭제 및 일정 DB 복제는 하지 않습니다.

### Google 설정 (직접 진행)

1. Google Cloud 프로젝트에서 **Google Calendar API**를 활성화합니다.
2. Google Auth platform에서 Branding·Audience·Data Access를 설정합니다.
   개인 Google 계정은 External/Testing으로 설정하고 본인 계정을 테스트 사용자로 추가합니다.
3. 요청 권한은 `https://www.googleapis.com/auth/calendar.events.readonly`입니다.
4. Clients에서 **Desktop app** 유형 OAuth 클라이언트를 만들고 JSON을 다운로드합니다.
5. 파일을 `backend/.secrets/google-calendar/credentials.json`에 배치합니다.
   `.secrets/`는 backend의 `.gitignore`에 등록되어 있습니다.
   다운로드 원본도 공개 저장소나 채팅에 올리지 마세요.

참고: [Google Python quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python),
[읽기 권한](https://developers.google.com/workspace/calendar/api/auth),
[일정 조회 규격](https://developers.google.com/workspace/calendar/api/v3/reference/events/list).

### 인증 및 조회

위 실행 안내대로 가상환경을 활성화하고 의존성을 설치한 뒤, `backend`에서 실행합니다.

```bash
python -m app.calendar_cli auth
python -m app.calendar_cli events 2026-09-22
```

`auth`는 로컬 브라우저에서 로그인과 읽기 권한 동의를 받습니다.
루프백 주소의 임시 포트에서 최대 180초 동안 콜백을 기다립니다.
토큰은 `.secrets/google-calendar/token.json`에 소유자만 읽고 쓸 수 있는 권한으로 저장됩니다.
암호화 저장은 아니므로 로컬 개발용으로만 사용하세요.
조회 시 만료 토큰은 자동 갱신하며, 갱신 실패·동의 철회 시 `auth`를 다시 실행합니다.
재인증하면 기존 로컬 토큰이 교체됩니다. 테스트 앱 정책 등에 따라 재인증이 필요할 수 있습니다.

조회 범위는 해당 날짜의 한국 시간 00:00부터 다음 날 00:00까지이며,
그 기간과 겹치는 일정도 포함합니다. 반복 일정은 개별 일정으로 조회하고 모든 페이지를 읽습니다.
취소 일정은 제외합니다. 종일 일정의 `end`는 마지막 날의 **다음 날짜(배타적 종료)**입니다.
응답은 `events` 배열이며 각 항목은 `id`, `title`, `start`, `end`, `all_day`, `location`입니다.
제목·장소가 없으면 빈 문자열로 반환합니다. 설명·참석자 등은 출력하지 않습니다.

조회 결과는 검증을 위해 터미널에만 JSON으로 출력합니다. 개인 일정이 포함되므로
화면 캡처·터미널 공유·출력 리다이렉션에 주의하세요. 앱은 일정과 인증정보를 로그로 남기지 않습니다.
오류는 인증/권한/API 설정, 호출 제한, 타임아웃, 네트워크, 응답 형식으로 구분합니다.

### 실제 검증 체크리스트

- [ ] 본인 계정으로 OAuth 동의 및 로컬 토큰 저장 성공
- [ ] 알려진 일정의 제목·시간·장소가 Google Calendar와 일치
- [ ] 종일·반복 일정 및 일정이 없는 날짜의 결과 확인
- [ ] 이후 실행에서 저장된 인증으로 조회 성공

자동 테스트는 외부 요청과 OAuth를 모의 처리합니다. **모의 테스트 통과는 실제 인증 성공의 증거가 아닙니다.**
현재 실제 계정 인증·데이터 조회는 미검증이며 위 체크리스트는 직접 실행한 뒤 기록합니다.
