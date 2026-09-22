"""Read-only data.go.kr village forecast integration (no persistence)."""

import math
from datetime import date, datetime, timedelta
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx

KST = ZoneInfo("Asia/Seoul")
URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
FIELDS = {
    "TMP": "temperature_c",
    "POP": "precipitation_probability_pct",
    "PTY": "precipitation_type_code",
    "WSD": "wind_speed_m_s",
    "REH": "humidity_pct",
    "SKY": "sky_code",
    "PCP": "precipitation",
}


class WeatherError(Exception):
    """Safe message: never include request URLs, keys or upstream error bodies."""


def to_grid(latitude: float, longitude: float) -> tuple[int, int]:
    """KMA 5 km Lambert conformal grid; reject coordinates outside its domain."""
    if not (-90 < latitude < 90 and -180 <= longitude <= 180):
        raise WeatherError("유효한 위도·경도를 입력하세요.")
    # Broad envelope of the grid, also avoiding singularities near the poles.
    if not (31 <= latitude <= 44 and 122 <= longitude <= 134):
        raise WeatherError("기상청 단기예보 격자 범위 밖의 위치입니다.")
    rad = math.pi / 180
    slat1, slat2 = 30 * rad, 60 * rad
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi / 4 + slat2 / 2) / math.tan(math.pi / 4 + slat1 / 2)
    )
    sf = math.tan(math.pi / 4 + slat1 / 2) ** sn * math.cos(slat1) / sn
    ro = (6371.00877 / 5) * sf / math.tan(math.pi / 4 + 38 * rad / 2) ** sn
    ra = (6371.00877 / 5) * sf / math.tan(math.pi / 4 + latitude * rad / 2) ** sn
    theta = ((longitude - 126 + 180) % 360 - 180) * rad * sn
    nx = math.floor(ra * math.sin(theta) + 43 + 0.5)
    ny = math.floor(ro - ra * math.cos(theta) + 136 + 0.5)
    if not (1 <= nx <= 149 and 1 <= ny <= 253):
        raise WeatherError("기상청 단기예보 격자 범위 밖의 위치입니다.")
    return nx, ny


def latest_base(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise WeatherError("현재 시각에는 시간대 정보가 필요합니다.")
    # Conservative local policy: allow an hour for publication, not an API SLA.
    available = now.astimezone(KST) - timedelta(hours=1)
    candidate = available.replace(minute=0, second=0, microsecond=0)
    while candidate.hour not in range(2, 24, 3):
        candidate -= timedelta(hours=1)
    return candidate


def _check_code(code: str) -> None:
    if code == "00":
        return
    if code in {"20", "30", "31", "32"}:
        raise WeatherError("기상청 인증키와 서비스 활용신청·승인 상태를 확인하세요.")
    if code in {"22", "23"}:
        raise WeatherError("기상청 API 호출 한도를 초과했습니다. 잠시 후 다시 시도하세요.")
    if code == "03":
        raise WeatherError("해당 발표시각의 예보 자료가 없습니다. 잠시 후 다시 시도하세요.")
    raise WeatherError("기상청 API가 오류를 반환했습니다. 요청 조건과 서비스 상태를 확인하세요.")


def _payload(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        # The gateway can return XML errors even when JSON was requested.
        try:
            root = ElementTree.fromstring(response.text)
            code = root.findtext(".//returnReasonCode") or root.findtext(".//resultCode")
        except ElementTree.ParseError:
            code = None
        if code:
            _check_code(code)
        raise WeatherError("기상청 응답 형식이 올바르지 않습니다.") from None
    try:
        envelope = data["response"]
        _check_code(envelope["header"]["resultCode"])
        body = envelope["body"]
        if not isinstance(body, dict):
            raise TypeError
        return body
    except (KeyError, TypeError):
        raise WeatherError("기상청 응답 형식이 올바르지 않습니다.") from None


class KmaWeatherClient:
    def __init__(self, http: httpx.Client, service_key: str):
        self.http = http
        self._service_key = service_key.strip()

    def get_forecast(
        self, latitude: float, longitude: float, day: date, *, now: datetime | None = None
    ) -> dict:
        """Return available forecast slots for day, not historical observations."""
        nx, ny = to_grid(latitude, longitude)
        current = now if now is not None else datetime.now(KST)
        base = latest_base(current)
        if day < current.astimezone(KST).date():
            raise WeatherError("과거 날짜는 조회할 수 없습니다. 이 기능은 단기예보 조회입니다.")
        if not self._service_key:
            raise WeatherError(
                "KMA_SERVICE_KEY 환경변수에 공공데이터포털 Decoding 키를 설정하세요."
            )
        if "%" in self._service_key:
            raise WeatherError("Encoding 키가 아닌 Decoding 키를 사용하세요.")
        records: dict[str, dict[str, str]] = {}
        seen: set[tuple[str, str]] = set()
        expected_total = None
        received = 0
        for page in range(1, 21):
            try:
                response = self.http.get(
                    URL,
                    params={
                        "serviceKey": self._service_key,
                        "dataType": "JSON",
                        "pageNo": page,
                        "numOfRows": 1000,
                        "base_date": base.strftime("%Y%m%d"),
                        "base_time": base.strftime("%H%M"),
                        "nx": nx,
                        "ny": ny,
                    },
                    timeout=10,
                    follow_redirects=False,
                )
            except httpx.TimeoutException:
                raise WeatherError("기상청 API 응답 시간이 초과되었습니다.") from None
            except httpx.RequestError:
                raise WeatherError("기상청 API에 연결할 수 없습니다.") from None
            if response.status_code in {401, 403}:
                _check_code("30")
            if response.status_code == 429:
                _check_code("22")
            if not response.is_success:
                raise WeatherError("기상청 API HTTP 요청에 실패했습니다.")
            body = _payload(response)
            try:
                total = int(body["totalCount"])
                if total < 0 or total > 20000 or int(body["pageNo"]) != page:
                    raise ValueError
                if expected_total is not None and expected_total != total:
                    raise ValueError
                expected_total = total
                items = body["items"]["item"] if total else []
                if not isinstance(items, list) or (total and not items):
                    raise ValueError
                received += len(items)
                if received > total:
                    raise ValueError
                for item in items:
                    if (
                        item["baseDate"] != base.strftime("%Y%m%d")
                        or item["baseTime"] != base.strftime("%H%M")
                        or int(item["nx"]) != nx
                        or int(item["ny"]) != ny
                    ):
                        raise ValueError
                    stamp = item["fcstDate"] + item["fcstTime"]
                    if not isinstance(stamp, str) or len(stamp) != 12 or not stamp.isdigit():
                        raise ValueError
                    timestamp = datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=KST)
                    category, value = item["category"], item["fcstValue"]
                    if not isinstance(category, str) or not isinstance(value, str):
                        raise ValueError
                    identity = (stamp, category)
                    if identity in seen:
                        raise ValueError
                    seen.add(identity)
                    if timestamp.date() == day and category in FIELDS:
                        records.setdefault(timestamp.isoformat(), {})[category] = value
            except (KeyError, TypeError, ValueError, OverflowError):
                raise WeatherError(
                    "기상청 예보 데이터 또는 페이지 정보가 올바르지 않습니다."
                ) from None
            if received == total:
                break
        else:
            raise WeatherError("기상청 응답 페이지가 너무 많습니다.")
        if not records:
            raise WeatherError("요청 날짜의 예보가 없습니다. 제공 기간 또는 발표시각을 확인하세요.")
        forecasts = []
        for timestamp, values in sorted(records.items()):
            slot = {"forecast_at": timestamp}
            for code, field in FIELDS.items():
                value = values.get(code)
                if value is None or value in {"-999", "-999.0"}:
                    slot[field] = None
                elif code == "PCP":
                    slot[field] = value  # Preserve ranges/qualitative precipitation text.
                else:
                    try:
                        number = float(value)
                        if not math.isfinite(number):
                            raise ValueError
                        if code in {"POP", "REH"} and not 0 <= number <= 100:
                            raise ValueError
                        if code == "WSD" and number < 0:
                            raise ValueError
                        if code == "SKY" and number not in {1, 3, 4}:
                            raise ValueError
                        if code == "PTY" and number not in {0, 1, 2, 3, 4}:
                            raise ValueError
                        slot[field] = number
                    except ValueError:
                        raise WeatherError("기상청 예보 값의 형식이 올바르지 않습니다.") from None
            forecasts.append(slot)
        return {
            "source": "기상청",
            "base_at": base.isoformat(),
            "date": day.isoformat(),
            "forecasts": forecasts,
        }
