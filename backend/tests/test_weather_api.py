from fastapi.testclient import TestClient

from app.api.v1 import weather as weather_api
from app.api.v1.auth import get_current_user
from app.main import app
from app.services.errors import AmbiguousPlaceError, ExternalServiceError


def test_weather_route_returns_normalized_tool_response(monkeypatch) -> None:
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "email": "test@example.com"}
    monkeypatch.setattr(
        weather_api,
        "get_weather",
        lambda place, date, time: {
            "temperature_c": 7,
            "precipitation_probability": 0,
            "precipitation_type": "none",
            "wind_mps": 0.2,
            "humidity_percent": 80,
            "sky": "clear",
        },
    )
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/weather",
                params={"place": "전주대학교", "date": "2026-11-03", "time": "15:10"},
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    assert response.json()["temperature_c"] == 7
    assert set(response.json()) == {
        "temperature_c",
        "precipitation_probability",
        "precipitation_type",
        "wind_mps",
        "humidity_percent",
        "sky",
    }


def test_weather_route_maps_ambiguity_and_upstream_failure(monkeypatch) -> None:
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "email": "test@example.com"}
    try:
        with TestClient(app) as client:
            monkeypatch.setattr(
                weather_api,
                "get_weather",
                lambda *args: (_ for _ in ()).throw(
                    AmbiguousPlaceError([{"name": "중앙공원", "address": "전북 전주시"}])
                ),
            )
            ambiguous = client.get(
                "/api/v1/weather",
                params={"place": "중앙공원", "date": "2026-11-03", "time": "15:00"},
            )
            assert ambiguous.status_code == 409
            assert ambiguous.json()["detail"]["candidates"][0]["address"] == "전북 전주시"

            monkeypatch.setattr(
                weather_api,
                "get_weather",
                lambda *args: (_ for _ in ()).throw(ExternalServiceError("외부 서비스 오류")),
            )
            failed = client.get(
                "/api/v1/weather",
                params={"place": "전주대학교", "date": "2026-11-03", "time": "15:00"},
            )
            assert failed.status_code == 502
    finally:
        app.dependency_overrides.pop(get_current_user, None)
