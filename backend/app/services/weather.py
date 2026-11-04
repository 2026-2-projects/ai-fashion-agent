"""기상청 격자 변환과 단기예보 조회/정규화."""

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx

from app.core.config import KMA_SERVICE_KEY
from app.services.errors import (
    ExternalServiceError,
    ForecastUnavailableError,
    ServiceConfigurationError,
    WeatherInputError,
)

KST = ZoneInfo("Asia/Seoul")
KMA_FORECAST_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
BASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)
PUBLICATION_DELAY = timedelta(minutes=25)

SKY_CODES = {"1": "clear", "3": "mostly_cloudy", "4": "cloudy"}
PRECIPITATION_CODES = {
    "0": "none",
    "1": "rain",
    "2": "rain_snow",
    "3": "snow",
    "4": "shower",
    "5": "drizzle",
    "6": "drizzle_snow",
    "7": "snow_flurry",
}
REQUIRED_CATEGORIES = {"TMP", "POP", "PTY", "WSD", "REH", "SKY"}


@dataclass(frozen=True)
class GridPoint:
    nx: int
    ny: int


@dataclass(frozen=True)
class WeatherForecast:
    temperature_c: int | float
    precipitation_probability: int
    precipitation_type: str
    wind_mps: float
    humidity_percent: int
    sky: str

    def as_dict(self) -> dict[str, int | float | str]:
        return asdict(self)


def latitude_longitude_to_grid(latitude: float, longitude: float) -> GridPoint:
    """기상청 DFS Lambert Conformal Conic 격자로 변환한다."""
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        raise WeatherInputError("위도 또는 경도 범위가 올바르지 않습니다.")

    radius = 6371.00877 / 5.0
    radians = math.pi / 180.0
    standard_parallel_1 = 30.0 * radians
    standard_parallel_2 = 60.0 * radians
    origin_longitude = 126.0 * radians
    origin_latitude = 38.0 * radians

    sn = math.log(math.cos(standard_parallel_1) / math.cos(standard_parallel_2))
    sn /= math.log(
        math.tan(math.pi * 0.25 + standard_parallel_2 * 0.5)
        / math.tan(math.pi * 0.25 + standard_parallel_1 * 0.5)
    )
    sf = math.tan(math.pi * 0.25 + standard_parallel_1 * 0.5) ** sn
    sf *= math.cos(standard_parallel_1) / sn
    ro = radius * sf / math.tan(math.pi * 0.25 + origin_latitude * 0.5) ** sn
    ra = radius * sf / math.tan(math.pi * 0.25 + latitude * radians * 0.5) ** sn
    theta = longitude * radians - origin_longitude
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn

    return GridPoint(
        nx=int(ra * math.sin(theta) + 43.5),
        ny=int(ro - ra * math.cos(theta) + 136.5),
    )


def latest_available_base(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise WeatherInputError("현재 시각에는 시간대 정보가 필요합니다.")
    safe_now = now.astimezone(KST) - PUBLICATION_DELAY
    available_hours = [hour for hour in BASE_HOURS if hour <= safe_now.hour]
    if available_hours:
        return safe_now.replace(hour=available_hours[-1], minute=0, second=0, microsecond=0)
    previous_day = safe_now - timedelta(days=1)
    return previous_day.replace(hour=23, minute=0, second=0, microsecond=0)


class KmaForecastClient:
    def __init__(
        self,
        service_key: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        raw_key = service_key if service_key is not None else KMA_SERVICE_KEY
        self.service_key = unquote(raw_key.strip()) if raw_key else ""
        self.http_client = http_client

    def get_forecast(
        self,
        grid: GridPoint,
        target: datetime,
        *,
        now: datetime | None = None,
    ) -> WeatherForecast:
        if not self.service_key:
            raise ServiceConfigurationError("기상청 단기예보 API 설정이 필요합니다.")
        if target.tzinfo is None:
            raise WeatherInputError("예보 시각에는 시간대 정보가 필요합니다.")

        current = now.astimezone(KST) if now is not None else datetime.now(KST)
        base = latest_available_base(current)
        params = {
            "serviceKey": self.service_key,
            "pageNo": 1,
            "numOfRows": 1000,
            "dataType": "JSON",
            "base_date": base.strftime("%Y%m%d"),
            "base_time": base.strftime("%H%M"),
            "nx": grid.nx,
            "ny": grid.ny,
        }

        try:
            if self.http_client is None:
                with httpx.Client(timeout=20.0) as client:
                    response = client.get(KMA_FORECAST_URL, params=params)
            else:
                response = self.http_client.get(KMA_FORECAST_URL, params=params)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            # serviceKey가 URL query에 포함되므로 원본 예외/URL을 노출하지 않는다.
            raise ExternalServiceError("기상청 단기예보 응답을 확인할 수 없습니다.") from None

        items = self._extract_items(payload)
        values = self._nearest_values(items, target.astimezone(KST))
        return self._normalize(values)

    @staticmethod
    def _extract_items(payload: Any) -> list[dict[str, Any]]:
        try:
            response = payload["response"]
            header = response["header"]
            result_code = str(header["resultCode"])
            if result_code.zfill(2) != "00":
                raise ExternalServiceError("기상청에서 예보 요청을 처리하지 못했습니다.")
            items = response["body"]["items"]["item"]
        except ExternalServiceError:
            raise
        except (KeyError, TypeError):
            raise ExternalServiceError("기상청 단기예보 응답 형식이 올바르지 않습니다.") from None
        if not isinstance(items, list):
            raise ExternalServiceError("기상청 단기예보 응답 형식이 올바르지 않습니다.")
        return items

    @staticmethod
    def _nearest_values(items: list[dict[str, Any]], target: datetime) -> dict[str, str]:
        grouped: dict[datetime, dict[str, str]] = {}
        for item in items:
            try:
                forecast_at = datetime.strptime(
                    f"{item['fcstDate']}{item['fcstTime']}", "%Y%m%d%H%M"
                ).replace(tzinfo=KST)
                category = str(item["category"])
                value = str(item["fcstValue"])
            except (KeyError, TypeError, ValueError):
                continue
            grouped.setdefault(forecast_at, {})[category] = value

        same_date = [forecast_at for forecast_at in grouped if forecast_at.date() == target.date()]
        if not same_date:
            raise ForecastUnavailableError("요청 날짜는 단기예보 제공 범위 밖입니다.")
        nearest = min(same_date, key=lambda forecast_at: abs(forecast_at - target))
        values = grouped[nearest]
        if not REQUIRED_CATEGORIES.issubset(values):
            raise ForecastUnavailableError("요청 시각의 필수 예보 항목이 부족합니다.")
        return values

    @staticmethod
    def _normalize(values: dict[str, str]) -> WeatherForecast:
        try:
            temperature = float(values["TMP"])
            precipitation_probability = int(float(values["POP"]))
            wind = float(values["WSD"])
            humidity = int(float(values["REH"]))
            precipitation_type = PRECIPITATION_CODES[values["PTY"]]
            sky = SKY_CODES[values["SKY"]]
        except (KeyError, TypeError, ValueError):
            raise ForecastUnavailableError("예보 값을 정규화할 수 없습니다.") from None
        normalized_temperature: int | float = (
            int(temperature) if temperature.is_integer() else temperature
        )
        return WeatherForecast(
            temperature_c=normalized_temperature,
            precipitation_probability=precipitation_probability,
            precipitation_type=precipitation_type,
            wind_mps=wind,
            humidity_percent=humidity,
            sky=sky,
        )
