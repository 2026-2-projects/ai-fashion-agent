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

## Kakao Local API 연동 준비 (WBS 2.5)

장소 키워드를 검색해 기상청 연동에 사용할 위도·경도 후보를 반환합니다.
공식 규격: [카카오맵 REST API](https://developers.kakao.com/docs/ko/kakaomap/rest-api).

1. Kakao Developers에서 앱을 생성하고 REST API 키와 카카오맵 사용 권한을 확인합니다.
2. `backend/.env.example`을 참고해 `backend/.env`를 만들고
   `KAKAO_REST_API_KEY`에 실제 REST API 키를 입력합니다. JavaScript 키가 아닙니다.
3. `backend` 디렉터리에서 `uvicorn app.main:app --reload --env-file .env`로 실행합니다.
   `.env`는 자동 로드되지 않으며 위 옵션 또는 서버 환경변수 설정이 필요합니다.
   `.env`는 기존 ignore 규칙에 포함되어 있습니다. 키는 브라우저에 전달하지 않습니다.
4. Swagger `/docs` 또는 아래 요청으로 실제 응답을 확인합니다.

```bash
curl --get 'http://localhost:8000/api/v1/places/search' --data-urlencode 'query=서울역'
```

요청: `query` 필수(공백 불가), `page` 1~45(기본 1), `size` 1~15(기본 5).
Kakao의 `GET /v2/local/search/keyword.json`에 `Authorization: KakaoAK <REST API 키>`로
인증합니다. 사용자 OAuth 로그인은 사용하지 않습니다.

응답은 `places` 목록과 `meta`(total_count, pageable_count, is_end)입니다.
각 장소에는 id, place_name, address_name, road_address_name, place_url,
longitude(경도, Kakao x), latitude(위도, Kakao y)가 포함됩니다.
좌표는 숫자로 변환됩니다. 첫 후보를 자동 선택하지 않으며 결과가 없으면 빈 목록입니다.
주소 전용 검색과 기상청 격자 변환은 이번 구현에 포함하지 않습니다.

오류: 입력 오류 422, 키 누락/외부 인증·권한 오류/쿼터 초과 503,
외부 연결·응답 오류 502, 10초 타임아웃 504. 외부 오류 본문은 전달하지 않습니다.
현재 검증용 엔드포인트이므로 공개 배포 전 사용자 인증과 호출 제한을 연결해야 합니다.

### 검증 범위

- 자동 테스트는 MockTransport로 요청 헤더·파라미터, 좌표 변환, 빈 결과,
  인증/쿼터/네트워크 오류, 잘못된 응답 및 HTTP 입력 검증을 확인합니다.
- 실제 키를 이용한 인증·권한·쿼터와 실데이터 조회는 별도 확인이 필요합니다.
  위 요청으로 장소 후보와 좌표를 확인한 뒤 검증 날짜·HTTP 상태·성공 여부를 기록하세요.
  키나 인증 헤더는 기록하지 마세요.
