from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.tools.calendar import get_calendar_events
from app.api.v1 import calendar as calendar_api
from app.core import config as settings
from app.core.database import engine, get_db
from app.main import app
from app.services.google_calendar import (
    CALENDAR_EVENTS_SCOPE,
    CalendarNotConnectedError,
    CalendarRevocationIncompleteError,
    OAuthTokens,
    disconnect_calendar,
    load_oauth_config,
    save_connection,
)


@pytest.fixture
def calendar_environment(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(
        settings,
        "GOOGLE_REDIRECT_URI",
        "http://localhost:8000/api/v1/calendar/oauth/callback",
    )
    monkeypatch.setattr(settings, "GOOGLE_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

    with engine.connect() as connection:
        transaction = connection.begin()

        def override_db():
            with Session(
                bind=connection,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        try:
            with TestClient(app) as client:
                yield client, connection
        finally:
            app.dependency_overrides.pop(get_db, None)
            transaction.rollback()


def signup_and_login(client: TestClient) -> dict:
    email = f"calendar-{uuid4().hex}@example.com"
    password = "TestPassword123!"
    assert (
        client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": password},
        ).status_code
        == 201
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return {
        "id": response.json()["id"],
        "email": email,
        "password": password,
        "headers": {"X-CSRF-Token": response.json()["csrf_token"]},
    }


def test_oauth_state_encrypted_storage_and_user_isolation(
    calendar_environment,
    monkeypatch,
) -> None:
    client, connection = calendar_environment
    assert client.get("/api/v1/calendar/connection").status_code == 401

    first = signup_and_login(client)
    assert client.post("/api/v1/calendar/oauth/start").status_code == 403

    start = client.post("/api/v1/calendar/oauth/start", headers=first["headers"])
    assert start.status_code == 200
    state_value = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]

    wrong_state = client.get(
        "/api/v1/calendar/oauth/callback",
        params={"state": "wrong", "code": "one-time-code"},
    )
    assert wrong_state.status_code == 400

    start = client.post("/api/v1/calendar/oauth/start", headers=first["headers"])
    state_value = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]
    tokens = OAuthTokens(
        access_token="access-secret",
        refresh_token="refresh-secret",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=frozenset({CALENDAR_EVENTS_SCOPE}),
    )
    monkeypatch.setattr(calendar_api, "exchange_authorization_code", lambda *args: tokens)

    callback = client.get(
        "/api/v1/calendar/oauth/callback",
        params={"state": state_value, "code": "one-time-code"},
    )
    assert callback.status_code == 200
    assert callback.json() == {"connected": True, "scope": CALENDAR_EVENTS_SCOPE}

    stored = (
        connection.execute(
            text("""
            SELECT access_token_encrypted, refresh_token_encrypted
            FROM google_calendar_connections WHERE user_id = :user_id
        """),
            {"user_id": first["id"]},
        )
        .mappings()
        .one()
    )
    assert stored["access_token_encrypted"] != "access-secret"
    assert stored["refresh_token_encrypted"] != "refresh-secret"
    assert "access-secret" not in stored["access_token_encrypted"]
    assert client.get("/api/v1/calendar/connection").json()["connected"] is True

    second = signup_and_login(client)
    assert second["id"] != first["id"]
    assert client.get("/api/v1/calendar/connection").json() == {
        "connected": False,
        "scope": None,
        "token_expires_at": None,
    }
    unconnected = client.get("/api/v1/calendar/events", params={"date": "2026-11-03"})
    assert unconnected.status_code == 409


def test_oauth_denial_consumes_state(calendar_environment) -> None:
    client, _ = calendar_environment
    account = signup_and_login(client)
    start = client.post("/api/v1/calendar/oauth/start", headers=account["headers"])
    state_value = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]

    denied = client.get(
        "/api/v1/calendar/oauth/callback",
        params={"state": state_value, "error": "access_denied"},
    )
    assert denied.status_code == 400
    assert denied.json()["detail"] == "Google Calendar 연결이 취소되었습니다."

    replayed = client.get(
        "/api/v1/calendar/oauth/callback",
        params={"state": state_value, "code": "one-time-code"},
    )
    assert replayed.status_code == 400


def test_expired_token_refreshes_before_event_read_and_disconnects(
    calendar_environment,
) -> None:
    client, connection = calendar_environment
    account = signup_and_login(client)
    config = load_oauth_config()

    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        save_connection(
            db,
            account["id"],
            OAuthTokens(
                access_token="expired-access",
                refresh_token="refresh-secret",
                expires_at=datetime.now(UTC) - timedelta(minutes=5),
                scopes=frozenset({CALENDAR_EVENTS_SCOPE}),
            ),
            config,
        )
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path == "/token":
                form = parse_qs(request.content.decode())
                assert form["refresh_token"] == ["refresh-secret"]
                return httpx.Response(
                    200,
                    json={
                        "access_token": "fresh-access",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                    },
                )
            assert request.headers["Authorization"] == "Bearer fresh-access"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "event-1",
                            "summary": "발표",
                            "start": {"dateTime": "2026-11-03T14:00:00+09:00"},
                            "end": {"dateTime": "2026-11-03T15:00:00+09:00"},
                        }
                    ]
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            events = get_calendar_events(db, account["id"], "2026-11-03", http=http)

        assert [request.url.path for request in calls] == [
            "/token",
            "/calendar/v3/calendars/primary/events",
        ]
        assert events[0]["title"] == "발표"

        other = signup_and_login(client)
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(CalendarNotConnectedError):
                get_calendar_events(db, other["id"], "2026-11-03", http=http)

        def revoke(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/revoke"
            assert parse_qs(request.content.decode())["token"] == ["refresh-secret"]
            return httpx.Response(200)

        with httpx.Client(transport=httpx.MockTransport(revoke)) as http:
            assert disconnect_calendar(db, account["id"], http) is True
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM google_calendar_connections WHERE user_id = :user_id"),
                {"user_id": account["id"]},
            ).scalar_one()
            == 0
        )


def test_disconnect_deletes_local_tokens_when_google_is_unreachable(calendar_environment) -> None:
    client, connection = calendar_environment
    account = signup_and_login(client)
    config = load_oauth_config()

    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        save_connection(
            db,
            account["id"],
            OAuthTokens(
                access_token="access-secret",
                refresh_token="refresh-secret",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                scopes=frozenset({CALENDAR_EVENTS_SCOPE}),
            ),
            config,
        )

        def unreachable(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("sensitive upstream detail", request=request)

        with httpx.Client(transport=httpx.MockTransport(unreachable)) as http:
            with pytest.raises(CalendarRevocationIncompleteError) as error:
                disconnect_calendar(db, account["id"], http)

        assert "sensitive" not in str(error.value)
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM google_calendar_connections WHERE user_id = :user_id"),
                {"user_id": account["id"]},
            ).scalar_one()
            == 0
        )
