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

## 기상청 API 연동 준비 (WBS 2.5)

공공데이터포털의 **기상청_단기예보 조회서비스**를 사용하는 로컬 검증용 CLI와
재사용 가능한 `KmaWeatherClient`를 제공합니다. HTTP 라우트·DB 저장·Agent 연결은
이번 범위에 포함하지 않습니다. 실제 키 인증 및 데이터 조회는 수동 검증이 필요합니다.

### 인증 및 실행

1. [공공데이터포털 서비스 페이지](https://www.data.go.kr/data/15084084/openapi.do)에서
   활용신청 후 승인 상태와 인증키를 확인합니다.
2. **일반 인증키(Decoding)**를 `KMA_SERVICE_KEY` 환경변수로 설정합니다.
   API허브의 `authKey`가 아니라 공공데이터포털 인증키가 필요합니다.
   아래는 zsh에서 키를 화면·명령 기록에 남기지 않고 입력하는 예입니다.
3. 위의 의존성 설치 후 `backend` 디렉터리에서 실행합니다.

```zsh
read -rs 'KMA_SERVICE_KEY?기상청 Decoding 키: '
export KMA_SERVICE_KEY
python -m app.weather_cli YYYY-MM-DD --lat 37.5665 --lon 126.9780
unset KMA_SERVICE_KEY
```

`YYYY-MM-DD`는 오늘 또는 가까운 미래 날짜(예: 내일)로 바꿉니다.
`.env` 파일은 자동 로드하지 않습니다. 키를 코드·문서·명령행 인자로 넣지 마세요.
CLI 종료 코드는 성공 0, 조회 실패 1, 인자 오류 2입니다.

### 요청 및 데이터 처리

- HTTPS GET `https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst`
- `serviceKey` 쿼리 인증. `httpx`가 인코딩하므로 Decoding 키를 그대로 전달합니다.
- `base_date`, `base_time`, `nx`, `ny`, `dataType=JSON`, `pageNo`, `numOfRows=1000` 사용.
- KST 기준 02·05·08·11·14·17·20·23시 발표 중 **발표 후 1시간이 지난 회차**를 선택합니다.
  1시간은 배포 지연을 고려한 이 도구의 보수적 정책이며, 공식 제공 시각 보장은 아닙니다.
  자정에는 전날 발표가 선택될 수 있습니다. 실패 시 과거 회차로 자동 대체하지 않습니다.
- 위·경도를 Lambert 5km 격자로 변환합니다. 격자 내라도 육상 예보 제공을 보장하지 않습니다.
  Kakao 좌표는 **y=위도, x=경도**, Geolocation은 `latitude`, `longitude`를 전달합니다.
- 전체 페이지를 받은 뒤 요청 날짜만 반환합니다. 잘못된 페이지·중복 자료는 오류 처리합니다.
- 과거 날짜는 지원하지 않습니다. 제공 기간 밖 날짜·자료 미생성은 명시적 오류입니다.
  오늘 조회는 남아 있는 예보 시각만 포함할 수 있으며, 하루 전체 관측값이 아닙니다.
- 응답은 `source`, `base_at`, `date`, `forecasts`이며 시각은 `+09:00` ISO 형식입니다.
  정확한 GPS나 격자 좌표는 결과에 포함하지 않습니다.

각 예보 시각의 필드:

| 필드 | 기상청 항목 | 의미 |
|---|---|---|
| `temperature_c` | TMP | 기온 °C |
| `precipitation_probability_pct` | POP | 강수확률 % |
| `precipitation_type_code` | PTY | 0 없음, 1 비, 2 비/눈, 3 눈, 4 소나기 |
| `wind_speed_m_s` | WSD | 풍속 m/s |
| `humidity_pct` | REH | 습도 % |
| `sky_code` | SKY | 1 맑음, 3 구름많음, 4 흐림 |
| `precipitation` | PCP | 강수량 원문(예: 강수없음, 1.0mm 미만) |

누락·`-999` 값은 `null`로 보존하며 맑음·0으로 추정하지 않습니다.
강수량은 범위/문자열 정보를 잃지 않도록 원문을 유지합니다.
아직 장소명 검색이나 사용자 동의 UI를 연결하지 않았으므로 좌표를 직접 입력해야 합니다.

### 오류와 보안

키 누락, 인증/승인 오류, 호출 한도, 타임아웃, 네트워크 오류, HTTP 오류,
JSON 요청에 대한 XML 게이트웨이 오류, 비정상 응답을 구분하여 안전한 메시지를 표시합니다.
키가 포함된 요청 URL과 외부 오류 본문은 출력하지 않으며 리다이렉트를 따르지 않습니다.
HTTP 디버그 로그나 외부 프록시 로그에는 쿼리 키가 남을 수 있으니 활성화하지 마세요.
조회 좌표는 기상청에 전송되며 CLI 인자에도 남으므로 검증에는 공개 장소 좌표를 사용하세요.

### 실제 연동 수동 검증 체크리스트

- [ ] 활용신청 승인 후 Decoding 키로 인증 성공
- [ ] 서울 등 알려진 장소의 오늘/내일 예보 조회 성공
- [ ] 선택된 발표시각·격자·예보시각을 포털의 같은 회차 결과와 비교
- [ ] 기온·강수확률·풍속·습도·하늘 상태와 단위 확인
- [ ] 제공 기간 밖 날짜 및 잘못된 키의 오류 메시지 확인
- [ ] 키·정확한 개인 위치를 제외한 검증 일시/결과 기록

자동 테스트는 `httpx.MockTransport`를 사용하며 **실제 인증·조회 성공을 증명하지 않습니다**.
연동 구조는 `Kakao/Geolocation 좌표 → get_forecast(latitude, longitude, day)`로
연결할 수 있지만 종단 간 통합은 후속 작업입니다.

공식 참고 자료:

- [공공데이터포털: 인증·서비스·오류 코드](https://www.data.go.kr/data/15084084/openapi.do)
- [기상청 API허브: 단기예보 요청/응답 및 발표 주기](https://apihub.kma.go.kr/apiList.do?seqApi=10)
  (명세 참고용이며 이 구현은 API허브 인증을 사용하지 않음)
- [기상청: 동네예보 격자영역 정보](https://apihub.kma.go.kr/getAttachFile.do?fileName=%2820240305%29%EB%8F%99%EB%84%A4%EC%98%88%EB%B3%B4+%EA%B2%A9%EC%9E%90%EC%98%81%EC%97%AD+%EC%A0%95%EB%B3%B4.pdf)
