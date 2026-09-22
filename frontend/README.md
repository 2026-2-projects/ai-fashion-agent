# Frontend · Web Geolocation 연동 준비 (WBS 2.5)

별도 패키지 설치 없는 HTML·CSS·JavaScript 검증 페이지입니다.
실제 서비스 UI, 장소 검색, Backend/기상청 연결은 이번 범위에 포함하지 않습니다.

## 실행

프로젝트 루트에서:

```sh
python3 -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

브라우저에서 <http://localhost:5500>에 접속합니다. 종료는 터미널에서 Ctrl+C입니다.
ES module을 사용하므로 파일을 직접 열지 말고 HTTP 서버를 사용하세요.
배포 시 HTTPS가 필요하며 localhost는 로컬 개발용으로 사용할 수 있습니다.
휴대폰에서 PC의 일반 HTTP LAN 주소로 접속하는 것은 localhost와 다릅니다.

## 인증·요청 방식

API 키나 OAuth 없이 **브라우저/운영체제의 위치 접근 권한**을 사용합니다.
사용자가 동의 버튼을 누른 경우에만 `navigator.geolocation.getCurrentPosition()`을 호출합니다.
권한이 이미 허용/거부된 경우 새 권한 창이 나타나지 않을 수 있습니다.
Permissions API에 의존하지 않고 실제 조회 콜백으로 성공·거부·조회 불가·시간 초과를 처리합니다.

- `enableHighAccuracy: false`: 기상 조회에 불필요한 고정밀 요청을 기본으로 하지 않음.
- `maximumAge: 0`: 브라우저의 기존 위치 캐시를 사용하지 않도록 요청.
- `timeout: 10000`: 위치 획득 제한 10초. 권한 승인 대기는 별도이므로 전체 대기가 더 길 수 있음.
- 위치 요청을 반복 추적하는 `watchPosition`은 사용하지 않음.
- 권한 거부에는 사이트 Permissions Policy 차단도 포함될 수 있음.
  배포 시 `Permissions-Policy: geolocation=(self)` 헤더를 서버에서 설정하는 것을 권장.
  다른 출처 iframe은 별도 정책/allow 설정이 필요하므로 우선 최상위 페이지에서 검증.

## 데이터와 후속 연동

`js/geolocation.js`의 `getCurrentLocation()`이 다음 객체를 Promise로 반환합니다.

```js
{ latitude: 37.5, longitude: 127, accuracy: 50, capturedAt: "2023-11-14T22:13:20.000Z" }
```

위 값은 설명용 가상 데이터입니다. `accuracy`는 미터, `capturedAt`은 위치 측정 시각(UTC)입니다.
위도·경도는 십진도이며 좌표 및 시각의 유효성을 검사합니다. 고도·속도 등은 전달하지 않습니다.
GPS 센서뿐 아니라 기기/브라우저 위치 서비스에 따라 좌표가 결정되므로 정확도를 보장하지 않습니다.

후속 Backend 연결에서는 `latitude`, `longitude`를 서버로 전달해 기상청 격자로 변환할 수 있습니다.
Kakao Local 좌표는 `x=longitude`, `y=latitude`로 매핑합니다.
현재 페이지에는 네트워크 전송 코드가 없으며 CSP `connect-src 'none'`으로 앱의 연결을 제한합니다.
실제 연동 시 전송 목적·동의 안내, Backend 계약과 CSP를 함께 변경해야 합니다.
정확한 좌표를 AI에 직접 전달하지 않는 프로젝트 원칙을 유지하세요.

## 개인정보와 대기 종료

좌표를 console, URL, 쿠키, localStorage, sessionStorage, DB에 남기지 않습니다.
화면에 표시한 좌표는 지우기·재조회·페이지 이탈 때 제거합니다.
브라우저/운영체제가 내부 위치 제공자와 통신하는 것까지 이 앱이 통제하지는 않습니다.
스크린샷에는 개인 위치가 포함될 수 있으니 공유하지 마세요.

`getCurrentPosition()`에는 취소 API가 없습니다. **대기 종료는 늦은 결과를 무시하는 동작**이며
브라우저 자체 조회나 권한 창을 취소하거나 권한을 철회하지 않습니다.
권한 철회는 브라우저 사이트 설정에서 직접 수행해야 합니다.

## 자동 모의 테스트

서버 실행 후 <http://localhost:5500/tests/>에 접속합니다.
브라우저 모듈과 DOM을 사용하는 무의존성 테스트이며 결과가 `PASS`인지 확인합니다.
실제 위치 API 대신 주입한 가상 응답만 사용하므로 위치 권한을 요청하지 않습니다.
성공·환경 제한·미지원·권한 거부·시간 초과·잘못된 좌표·중복 요청·늦은 콜백·삭제를 검증합니다.

2026-09-22 로컬 Safari에서 모의 테스트 **23/23 통과** 및 초기 화면 렌더링을 확인했습니다.
실제 위치 권한 요청은 실행하지 않았습니다.

## 실제 기기 수동 검증 (아직 미검증)

- [ ] 페이지 최초 진입 시 위치 권한 창이 뜨지 않는지 확인
- [ ] 동의 버튼 → 권한 허용 → 좌표·정확도 표시 확인
- [ ] 권한 거부 시 안내 및 재시도 가능 여부 확인
- [ ] OS 위치 서비스 비활성화 시 조회 불가/시간 초과 안내 확인
- [ ] 지우기 및 조회 중 대기 종료 후 좌표가 다시 나타나지 않는지 확인
- [ ] HTTPS 배포 환경과 모바일 브라우저에서 검증
- [ ] 앱 요청에 좌표가 전송되지 않고 브라우저 저장소에 남지 않는지 확인
- [ ] 검증 브라우저·OS·일시·성공 여부를 개인 좌표 없이 기록

모의 테스트 통과는 실제 권한 인증·위치 수신이나 기상청 종단 간 연동 성공을 의미하지 않습니다.

공식 참고: [MDN getCurrentPosition](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation/getCurrentPosition),
[W3C Geolocation](https://www.w3.org/TR/geolocation/),
[Permissions Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Permissions-Policy/geolocation).
