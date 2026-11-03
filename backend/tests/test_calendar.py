from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from app.agent.tools.calendar import CALENDAR_TOOL_SCHEMA, get_calendar_events
from app.core import config
from app.services.calendar import SCOPE, digest, now, parse_date
from app.services.calendar_client import CalendarError, GoogleCalendarClient


def login(client, email="first@example.com"):
    assert (
        client.post(
            "/api/v1/auth/signup", json={"email": email, "password": "TestPassword123!"}
        ).status_code
        == 201
    )
    result = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "TestPassword123!"}
    )
    assert result.status_code == 200
    return result.json(), {"X-CSRF-Token": result.json()["csrf_token"]}


def token(refresh=True):
    result = {
        "access_token": "secret-access",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": SCOPE,
    }
    if refresh:
        result["refresh_token"] = "secret-refresh"
    return httpx.Response(200, json=result)


def connect(client, headers):
    result = client.post("/api/v1/calendar/connect", headers=headers)
    assert result.status_code == 200
    query = parse_qs(urlparse(result.json()["authorization_url"]).query)
    assert query["scope"] == [SCOPE]
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"]
    return query


def finish(client, query):
    return client.get(
        "/api/v1/calendar/callback", params={"state": query["state"][0], "code": "one-use-code"}
    )


def test_auth_and_csrf(client):
    assert client.get("/api/v1/calendar/connection").status_code == 401
    user, headers = login(client)
    assert client.post("/api/v1/calendar/connect").status_code == 403
    assert client.get("/api/v1/auth/me").json()["id"] == user["id"]
    assert (
        client.post(
            "/api/v1/auth/signup",
            json={"email": "first@example.com", "password": "TestPassword123!"},
        ).status_code
        == 409
    )
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_oauth_encryption_replay_and_isolation(client, db, upstream):
    user, headers = login(client)
    query = connect(client, headers)
    upstream[2].append(token())
    assert finish(client, query).json()["connected"] is True
    row = db.execute(text("SELECT * FROM google_calendar_connections")).mappings().one()
    assert "secret-access" not in row["access_token_encrypted"]
    assert "secret-refresh" not in row["refresh_token_encrypted"]
    cipher = Fernet(config.GOOGLE_TOKEN_ENCRYPTION_KEY.encode())
    assert cipher.decrypt(row["refresh_token_encrypted"].encode()) == b"secret-refresh"
    posted = parse_qs(upstream[1][0].content.decode())
    assert digest(posted["code_verifier"][0])
    assert finish(client, query).status_code == 400
    login(client, "second@example.com")
    assert client.get("/api/v1/calendar/connection").json()["connected"] is False
    assert client.get("/api/v1/calendar/events?date=2026-11-03").status_code == 409
    assert len(upstream[1]) == 1


@pytest.mark.parametrize("kind", ["wrong", "expired", "denied", "other_user", "other_session"])
def test_invalid_oauth(client, db, upstream, kind):
    _, headers = login(client)
    query = connect(client, headers)
    state = query["state"][0]
    if kind == "wrong":
        state = "wrong"
    elif kind == "expired":
        db.execute(
            text("UPDATE google_calendar_oauth_states SET expires_at = :expiry"),
            {"expiry": now() - timedelta(seconds=1)},
        )
        db.commit()
    elif kind == "other_user":
        login(client, "other@example.com")
    elif kind == "other_session":
        client.post(
            "/api/v1/auth/login",
            json={"email": "first@example.com", "password": "TestPassword123!"},
        )
    result = client.get(
        "/api/v1/calendar/callback",
        params={
            "state": state,
            "code": "code",
            "error": "access_denied" if kind == "denied" else "",
        },
    )
    assert result.status_code == 400
    assert not upstream[1]


def test_refresh_and_tool(client, db, upstream):
    user, headers = login(client)
    upstream[2].append(token())
    assert finish(client, connect(client, headers)).status_code == 200
    db.execute(
        text("UPDATE google_calendar_connections SET expires_at = :expiry"),
        {"expiry": now() - timedelta(seconds=1)},
    )
    db.commit()
    upstream[2].extend([token(refresh=False), httpx.Response(200, json={"items": []})])
    result = get_calendar_events(db, user["id"], "2026-11-03", http=upstream[0])
    assert result == {"date": "2026-11-03", "timezone": "Asia/Seoul", "events": []}
    assert parse_qs(upstream[1][-2].content.decode())["refresh_token"] == ["secret-refresh"]
    assert set(CALENDAR_TOOL_SCHEMA["function"]["parameters"]["properties"]) == {"date"}


def test_revoked_and_api_failure(client, db, upstream):
    _, headers = login(client)
    upstream[2].append(token())
    assert finish(client, connect(client, headers)).status_code == 200
    upstream[2].extend([httpx.Response(401), httpx.Response(400, json={"error": "invalid_grant"})])
    result = client.get("/api/v1/calendar/events?date=2026-11-03")
    assert result.status_code == 409
    assert client.get("/api/v1/calendar/connection").json() == {
        "connected": False,
        "reconnect_required": True,
    }


def test_failed_reconnect_preserves_credentials(client, db, upstream):
    _, headers = login(client)
    upstream[2].append(token())
    assert finish(client, connect(client, headers)).status_code == 200
    before = db.execute(
        text("SELECT access_token_encrypted FROM google_calendar_connections")
    ).scalar()
    upstream[2].append(token(refresh=False))
    assert finish(client, connect(client, headers)).status_code == 409
    after = db.execute(
        text("SELECT access_token_encrypted FROM google_calendar_connections")
    ).scalar()
    assert before == after


def test_config_date_and_no_event_mutation(client, monkeypatch):
    _, headers = login(client)
    assert client.get("/api/v1/calendar/events?date=2026-02-30").status_code == 422
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "")
    assert client.post("/api/v1/calendar/connect", headers=headers).status_code == 503
    for method in (client.post, client.patch, client.delete):
        assert method("/api/v1/calendar/events").status_code == 405


def test_fk_cascade(client, db, upstream):
    user, headers = login(client)
    upstream[2].append(token())
    assert finish(client, connect(client, headers)).status_code == 200
    connect(client, headers)
    db.execute(text("DELETE FROM users WHERE id = :id"), {"id": user["id"]})
    db.commit()
    for table in ("google_calendar_connections", "google_calendar_oauth_states"):
        assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0


@pytest.mark.parametrize(
    "value", ["2026-02-30", "20261103", "2026-W45-2", "tomorrow", "9999-12-31"]
)
def test_date_validation(value):
    with pytest.raises(CalendarError) as exc:
        parse_date(value)
    assert exc.value.status_code == 422


def test_event_normalization_pagination(upstream):
    from datetime import date

    http, requests, responses = upstream
    responses.extend(
        [
            httpx.Response(
                200,
                json={
                    "nextPageToken": "page2",
                    "items": [
                        {
                            "id": "all-day",
                            "start": {"date": "2026-11-03"},
                            "end": {"date": "2026-11-04"},
                        },
                        {"id": "cancelled", "status": "cancelled"},
                    ],
                },
            ),
            httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "recurring",
                            "summary": "약속",
                            "location": "전주",
                            "start": {"dateTime": "2026-11-02T23:00:00+09:00"},
                            "end": {"dateTime": "2026-11-03T02:00:00+09:00"},
                        },
                    ]
                },
            ),
        ]
    )
    events = GoogleCalendarClient(http, "access").get_events(date(2026, 11, 3))
    assert events[0].all_day and events[0].location == "" and events[0].title == ""
    assert events[0].end == "2026-11-04"
    assert events[1].title == "약속" and events[1].location == "전주"
    assert requests[0].url.params["timeMin"] == "2026-11-03T00:00:00+09:00"
    assert requests[0].url.params["timeMax"] == "2026-11-04T00:00:00+09:00"
    assert requests[0].url.params["singleEvents"] == "true"
    assert requests[1].url.params["pageToken"] == "page2"
    assert all(request.method == "GET" for request in requests)


@pytest.mark.parametrize(
    "response, status",
    [
        (httpx.Response(429), 429),
        (httpx.Response(500), 502),
        (httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}}), 429),
        (httpx.Response(403, json={}), 403),
        (httpx.Response(200, json={"items": "bad"}), 502),
        (httpx.ReadTimeout("secret upstream content"), 504),
    ],
)
def test_google_errors(upstream, response, status):
    from datetime import date

    http, _, responses = upstream
    responses.append(response)
    with pytest.raises(CalendarError) as exc:
        GoogleCalendarClient(http, "access").get_events(date(2026, 11, 3))
    assert exc.value.status_code == status
    assert "secret" not in str(exc.value)


def test_api_success_and_401_retry(client, upstream):
    _, headers = login(client)
    upstream[2].append(token())
    query = connect(client, headers)
    assert finish(client, query).status_code == 200
    import base64
    import hashlib

    posted = parse_qs(upstream[1][0].content.decode())
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(posted["code_verifier"][0].encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert query["code_challenge"] == [challenge]
    upstream[2].extend(
        [
            httpx.Response(401),
            token(refresh=False),
            httpx.Response(200, json={"items": []}),
        ]
    )
    result = client.get("/api/v1/calendar/events?date=2026-11-03")
    assert result.status_code == 200 and result.json()["events"] == []
    assert result.headers["cache-control"] == "no-store"
    assert len(upstream[1]) == 4


def test_refresh_rotation_and_event_details(client, db, upstream):
    user, headers = login(client)
    upstream[2].append(token())
    assert finish(client, connect(client, headers)).status_code == 200
    db.execute(
        text("UPDATE google_calendar_connections SET expires_at = :expiry"),
        {"expiry": now() - timedelta(seconds=1)},
    )
    db.commit()
    renewed = token().json() | {
        "access_token": "renewed-access",
        "refresh_token": "rotated-refresh",
    }
    upstream[2].extend(
        [
            httpx.Response(200, json=renewed),
            httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "dinner",
                            "summary": "저녁 약속",
                            "start": {"dateTime": "2026-11-03T19:00:00+09:00"},
                            "end": {"dateTime": "2026-11-03T20:00:00+09:00"},
                            "location": "전주 한옥마을",
                            "description": "추천에 불필요한 비공개 설명",
                            "attendees": [{"email": "private@example.com"}],
                        }
                    ]
                },
            ),
        ]
    )
    result = client.get("/api/v1/calendar/events?date=2026-11-03")
    assert result.status_code == 200
    assert result.json() == {
        "date": "2026-11-03",
        "timezone": "Asia/Seoul",
        "events": [
            {
                "id": "dinner",
                "title": "저녁 약속",
                "start": "2026-11-03T19:00:00+09:00",
                "end": "2026-11-03T20:00:00+09:00",
                "all_day": False,
                "location": "전주 한옥마을",
            }
        ],
    }
    assert upstream[1][-1].headers["authorization"] == "Bearer renewed-access"
    assert "renewed-access" not in result.text and "rotated-refresh" not in result.text

    # A later Tool call must reload the rotated refresh token from persistent storage.
    db.execute(
        text("UPDATE google_calendar_connections SET expires_at = :expiry"),
        {"expiry": now() - timedelta(seconds=1)},
    )
    db.commit()
    upstream[2].extend([token(refresh=False), httpx.Response(200, json={"items": []})])
    assert get_calendar_events(db, user["id"], "2026-11-03", http=upstream[0])["events"] == []
    assert parse_qs(upstream[1][-2].content.decode())["refresh_token"] == ["rotated-refresh"]


def test_write_scope_rejected_without_replacing_connection(client, db, upstream):
    _, headers = login(client)
    upstream[2].append(token())
    assert finish(client, connect(client, headers)).status_code == 200
    before = db.execute(
        text("SELECT access_token_encrypted FROM google_calendar_connections")
    ).scalar_one()
    broader_token = token().json() | {"scope": SCOPE + " https://www.googleapis.com/auth/calendar"}
    upstream[2].append(httpx.Response(200, json=broader_token))
    query = connect(client, headers)
    result = finish(client, query)
    assert result.status_code == 403
    assert result.json()["detail"]["code"] == "scope_denied"
    assert client.get("/api/v1/calendar/connection").json()["connected"] is True
    assert before == db.execute(
        text("SELECT access_token_encrypted FROM google_calendar_connections")
    ).scalar_one()
    assert finish(client, query).status_code == 400


def test_repeated_unauthorized_stops_and_requires_reconnect(client, upstream):
    _, headers = login(client)
    upstream[2].append(token())
    assert finish(client, connect(client, headers)).status_code == 200
    upstream[2].extend([httpx.Response(401), token(refresh=False), httpx.Response(401)])
    assert client.get("/api/v1/calendar/events?date=2026-11-03").status_code == 409
    assert client.get("/api/v1/calendar/connection").json() == {
        "connected": False,
        "reconnect_required": True,
    }
    assert len(upstream[1]) == 4


def test_repeated_page_token_is_rejected(upstream):
    from datetime import date

    http, requests, responses = upstream
    responses.extend(
        httpx.Response(200, json={"items": [], "nextPageToken": "same-page"}) for _ in range(2)
    )
    with pytest.raises(CalendarError) as exc:
        GoogleCalendarClient(http, "access").get_events(date(2026, 11, 3))
    assert exc.value.status_code == 502
    assert len(requests) == 2


@pytest.mark.parametrize(
    "response, expected",
    [
        (httpx.Response(200, json={"access_token": "bad"}), 502),
        (httpx.Response(429, json={}), 429),
        (httpx.ReadTimeout("sensitive provider message"), 504),
        (
            httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "unrelated",
                },
            ),
            403,
        ),
    ],
)
def test_oauth_failure_sanitized_and_consumes_state(client, upstream, response, expected):
    _, headers = login(client)
    query = connect(client, headers)
    upstream[2].append(response)
    result = finish(client, query)
    assert result.status_code == expected
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["referrer-policy"] == "no-referrer"
    assert "sensitive" not in result.text
    assert finish(client, query).status_code == 400
    assert client.get("/api/v1/calendar/connection").json()["connected"] is False


def test_callback_privacy_middleware():
    import asyncio

    from app.core.calendar_privacy import CalendarPrivacyMiddleware

    scope = {
        "type": "http",
        "path": "/api/v1/calendar/callback",
        "query_string": b"code=secret-code&state=secret-state",
    }
    messages = []

    async def endpoint(scope, receive, send):
        assert b"secret-code" in scope["query_string"]
        await send({"type": "http.response.start", "status": 400, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        assert scope["query_string"] == b""  # Uvicorn logs here.
        messages.append(message)

    asyncio.run(CalendarPrivacyMiddleware(endpoint)(scope, receive, send))
    assert (b"cache-control", b"no-store") in messages[0]["headers"]
