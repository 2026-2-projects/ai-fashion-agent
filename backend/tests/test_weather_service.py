from datetime import datetime

import httpx
import pytest

from app.services.errors import ExternalServiceError, ForecastUnavailableError
from app.services.weather import (
    KST,
    GridPoint,
    KmaForecastClient,
    latest_available_base,
    latitude_longitude_to_grid,
)


def _forecast_payload(date: str, time: str) -> dict:
    values = {
        "TMP": "7",
        "POP": "0",
        "PTY": "0",
        "WSD": "0.2",
        "REH": "80",
        "SKY": "1",
    }
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
            "body": {
                "items": {
                    "item": [
                        {
                            "fcstDate": date,
                            "fcstTime": time,
                            "category": category,
                            "fcstValue": value,
                        }
                        for category, value in values.items()
                    ]
                }
            },
        }
    }


def test_jeonju_university_grid_conversion() -> None:
    grid = latitude_longitude_to_grid(35.81411422757866, 127.08988123196553)
    assert grid == GridPoint(nx=62, ny=89)


def test_latest_base_time_respects_publication_delay() -> None:
    assert latest_available_base(datetime(2026, 11, 2, 2, 24, tzinfo=KST)) == datetime(
        2026, 11, 1, 23, 0, tzinfo=KST
    )
    assert latest_available_base(datetime(2026, 11, 2, 2, 25, tzinfo=KST)) == datetime(
        2026, 11, 2, 2, 0, tzinfo=KST
    )


def test_kma_response_is_normalized_and_nearest_hour_is_selected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["nx"] == "62"
        assert request.url.params["ny"] == "89"
        assert request.url.params["serviceKey"] == "encoded+key"
        return httpx.Response(200, json=_forecast_payload("20261103", "1500"))

    client = KmaForecastClient(
        service_key="encoded%2Bkey",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.get_forecast(
        GridPoint(62, 89),
        datetime(2026, 11, 3, 15, 10, tzinfo=KST),
        now=datetime(2026, 11, 2, 22, 0, tzinfo=KST),
    )

    assert result.as_dict() == {
        "temperature_c": 7,
        "precipitation_probability": 0,
        "precipitation_type": "none",
        "wind_mps": 0.2,
        "humidity_percent": 80,
        "sky": "clear",
    }


def test_missing_target_date_is_reported_as_unavailable() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=_forecast_payload("20261103", "1500"))
    )
    client = KmaForecastClient(
        service_key="test-key",
        http_client=httpx.Client(transport=transport),
    )
    with pytest.raises(ForecastUnavailableError):
        client.get_forecast(
            GridPoint(62, 89),
            datetime(2026, 11, 5, 15, 0, tzinfo=KST),
            now=datetime(2026, 11, 2, 22, 0, tzinfo=KST),
        )


def test_kma_upstream_error_is_sanitized() -> None:
    service_key = "not-a-real-secret-service-key"
    transport = httpx.MockTransport(lambda request: httpx.Response(401))
    client = KmaForecastClient(
        service_key=service_key,
        http_client=httpx.Client(transport=transport),
    )

    with pytest.raises(ExternalServiceError) as exc_info:
        client.get_forecast(
            GridPoint(62, 89),
            datetime(2026, 11, 3, 15, 0, tzinfo=KST),
            now=datetime(2026, 11, 2, 22, 0, tzinfo=KST),
        )
    assert service_key not in str(exc_info.value)
