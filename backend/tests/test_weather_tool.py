from datetime import datetime

import pytest

from app.agent.tools import weather as weather_tool
from app.services.errors import AmbiguousPlaceError, WeatherInputError
from app.services.location import Place
from app.services.weather import KST, WeatherForecast


class FakeLocationClient:
    def resolve_place(self, query: str) -> Place:
        assert query == "전주대학교"
        return Place("1", query, "전북 전주시", "", 35.81411422757866, 127.08988123196553)


class FakeForecastClient:
    def get_forecast(self, grid, target, *, now):
        assert (grid.nx, grid.ny) == (62, 89)
        assert target == datetime(2026, 11, 3, 15, 10, tzinfo=KST)
        return WeatherForecast(12, 20, "none", 2.5, 65, "cloudy")


def test_get_weather_orchestrates_location_grid_and_forecast(monkeypatch) -> None:
    monkeypatch.setattr(weather_tool, "KakaoLocalClient", FakeLocationClient)
    monkeypatch.setattr(weather_tool, "KmaForecastClient", FakeForecastClient)
    monkeypatch.setattr(
        weather_tool,
        "_now_kst",
        lambda: datetime(2026, 11, 2, 22, 0, tzinfo=KST),
    )

    assert weather_tool.get_weather("전주대학교", "2026-11-03", "15:10") == {
        "temperature_c": 12,
        "precipitation_probability": 20,
        "precipitation_type": "none",
        "wind_mps": 2.5,
        "humidity_percent": 65,
        "sky": "cloudy",
    }


@pytest.mark.parametrize(
    ("date", "time"),
    [
        ("2026/11/03", "15:10"),
        ("2026-11-03", "25:00"),
        ("2026-11-01", "15:00"),
        ("2026-11-06", "15:00"),
    ],
)
def test_get_weather_rejects_invalid_or_unsupported_datetime(
    monkeypatch, date: str, time: str
) -> None:
    monkeypatch.setattr(
        weather_tool,
        "_now_kst",
        lambda: datetime(2026, 11, 2, 22, 0, tzinfo=KST),
    )
    with pytest.raises(WeatherInputError):
        weather_tool.get_weather("전주대학교", date, time)


def test_ambiguous_place_is_propagated_for_agent_clarification(monkeypatch) -> None:
    class AmbiguousClient:
        def resolve_place(self, query: str):
            raise AmbiguousPlaceError(
                [
                    {"name": "중앙공원", "address": "전북 전주시"},
                    {"name": "중앙공원", "address": "경기 성남시"},
                ]
            )

    monkeypatch.setattr(weather_tool, "KakaoLocalClient", AmbiguousClient)
    monkeypatch.setattr(
        weather_tool,
        "_now_kst",
        lambda: datetime(2026, 11, 2, 22, 0, tzinfo=KST),
    )
    with pytest.raises(AmbiguousPlaceError):
        weather_tool.get_weather("중앙공원", "2026-11-03", "15:00")
