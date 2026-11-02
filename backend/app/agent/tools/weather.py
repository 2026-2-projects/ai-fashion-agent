"""Agent가 장소·날짜·시간으로 단기예보를 조회하는 Tool."""

from datetime import datetime, timedelta

from app.services.errors import WeatherInputError
from app.services.location import KakaoLocalClient
from app.services.weather import KST, KmaForecastClient, latitude_longitude_to_grid

MAX_FORECAST_DAYS = 3
PAST_TOLERANCE = timedelta(hours=1)


def _now_kst() -> datetime:
    return datetime.now(KST)


def _parse_target(date: str, time: str, now: datetime) -> datetime:
    try:
        target = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    except ValueError:
        raise WeatherInputError("날짜는 YYYY-MM-DD, 시간은 HH:MM 형식으로 입력해 주세요.") from None

    if target < now - PAST_TOLERANCE:
        raise WeatherInputError("과거 날씨는 단기예보 Tool에서 조회할 수 없습니다.")
    if target.date() > now.date() + timedelta(days=MAX_FORECAST_DAYS):
        raise WeatherInputError("요청 날짜는 단기예보 제공 범위 밖입니다.")
    return target


def get_weather(place: str, date: str, time: str) -> dict[str, int | float | str]:
    """장소를 좌표·격자로 변환한 뒤 지정 시각의 정규화된 예보를 반환한다."""
    now = _now_kst()
    target = _parse_target(date, time, now)
    resolved = KakaoLocalClient().resolve_place(place)
    grid = latitude_longitude_to_grid(resolved.latitude, resolved.longitude)
    forecast = KmaForecastClient().get_forecast(grid, target, now=now)
    return forecast.as_dict()
