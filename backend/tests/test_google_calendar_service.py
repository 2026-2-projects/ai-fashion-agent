from datetime import UTC, date
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet

from app.agent.tools import calendar as calendar_tool
from app.services.google_calendar import (
    CALENDAR_EVENTS_SCOPE,
    CalendarAccessTokenRejected,
    CalendarAuthorizationError,
    CalendarEvent,
    CalendarExternalError,
    CalendarRateLimitError,
    CalendarResponseError,
    GoogleOAuthConfig,
    build_authorization_url,
    decrypt_token,
    encrypt_token,
    exchange_authorization_code,
    fetch_calendar_events,
    refresh_access_token,
)


@pytest.fixture
def oauth_config() -> GoogleOAuthConfig:
    return GoogleOAuthConfig(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:8000/api/v1/calendar/oauth/callback",
        token_encryption_key=Fernet.generate_key().decode(),
    )


def test_authorization_url_uses_exact_readonly_scope_and_state(oauth_config) -> None:
    url = build_authorization_url(oauth_config, "csrf-state")
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert query["scope"] == [CALENDAR_EVENTS_SCOPE]
    assert query["state"] == ["csrf-state"]
    assert query["access_type"] == ["offline"]
    assert query["include_granted_scopes"] == ["false"]
    assert query["prompt"] == ["consent select_account"]


def test_token_exchange_and_refresh_do_not_expose_secrets(oauth_config) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        form = parse_qs(request.content.decode())
        assert request.url.path == "/token"
        assert form["client_secret"] == ["test-client-secret"]
        if form["grant_type"] == ["authorization_code"]:
            assert form["code"] == ["one-time-code"]
            return httpx.Response(
                200,
                json={
                    "access_token": "first-access",
                    "refresh_token": "refresh-secret",
                    "expires_in": 3600,
                    "scope": CALENDAR_EVENTS_SCOPE,
                    "token_type": "Bearer",
                },
            )
        assert form["refresh_token"] == ["refresh-secret"]
        return httpx.Response(
            200,
            json={
                "access_token": "second-access",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        exchanged = exchange_authorization_code(http, oauth_config, "one-time-code")
        refreshed = refresh_access_token(http, oauth_config, exchanged.refresh_token)

    assert len(requests) == 2
    assert exchanged.refresh_token == "refresh-secret"
    assert refreshed.access_token == "second-access"
    assert refreshed.refresh_token == "refresh-secret"
    assert exchanged.expires_at.tzinfo is UTC

    def denied(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant", "token": "secret-value"})

    with httpx.Client(transport=httpx.MockTransport(denied)) as http:
        with pytest.raises(CalendarAuthorizationError) as error:
            exchange_authorization_code(http, oauth_config, "secret-code")
    assert "secret" not in str(error.value).lower()


def test_tokens_are_encrypted_at_rest(oauth_config) -> None:
    encrypted = encrypt_token("access-secret", oauth_config)

    assert encrypted != "access-secret"
    assert "access-secret" not in encrypted
    assert decrypt_token(encrypted, oauth_config) == "access-secret"


def test_event_request_paginates_and_returns_minimal_fields() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer access-secret"
        assert request.url.params["timeMin"] == "2026-11-03T00:00:00+09:00"
        assert request.url.params["timeMax"] == "2026-11-04T00:00:00+09:00"
        assert request.url.params["singleEvents"] == "true"
        assert "attendees" not in request.url.params["fields"]
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "meeting-1",
                            "summary": "팀 회의",
                            "location": "전주",
                            "start": {"dateTime": "2026-11-03T10:00:00+09:00"},
                            "end": {"dateTime": "2026-11-03T11:00:00+09:00"},
                        }
                    ],
                    "nextPageToken": "page-2",
                },
            )
        assert request.url.params["pageToken"] == "page-2"
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": "cancelled", "status": "cancelled"},
                    {
                        "id": "all-day",
                        "start": {"date": "2026-11-03"},
                        "end": {"date": "2026-11-04"},
                    },
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        events = fetch_calendar_events(http, "access-secret", date(2026, 11, 3))

    assert len(calls) == 2
    assert [event.id for event in events] == ["meeting-1", "all-day"]
    assert events[0].title == "팀 회의"
    assert events[1].all_day is True


@pytest.mark.parametrize("status_code", [500, 503])
def test_event_upstream_failure_is_sanitized(status_code) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"token": "access-secret"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(CalendarExternalError) as error:
            fetch_calendar_events(http, "access-secret", date(2026, 11, 3))
    assert "access-secret" not in str(error.value)


@pytest.mark.parametrize(
    "status_code,error_type",
    [
        (401, CalendarAccessTokenRejected),
        (403, CalendarAuthorizationError),
        (429, CalendarRateLimitError),
    ],
)
def test_event_authorization_and_rate_limit_errors(status_code, error_type) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(status_code, json={}))
    ) as http:
        with pytest.raises(error_type):
            fetch_calendar_events(http, "access-secret", date(2026, 11, 3))


def test_agent_retries_once_after_access_token_401(monkeypatch) -> None:
    refresh_flags = []
    event_calls = []

    def fake_access_token(_db, _user_id, _http, *, force_refresh=False):
        refresh_flags.append(force_refresh)
        return "fresh-access" if force_refresh else "stale-access"

    def fake_events(_http, access_token, _day):
        event_calls.append(access_token)
        if access_token == "stale-access":
            raise CalendarAccessTokenRejected("safe")
        return [
            CalendarEvent(
                id="event-1",
                title="발표",
                start="2026-11-03T14:00:00+09:00",
                end="2026-11-03T15:00:00+09:00",
                all_day=False,
                location="",
            )
        ]

    monkeypatch.setattr(calendar_tool, "get_access_token", fake_access_token)
    monkeypatch.setattr(calendar_tool, "fetch_calendar_events", fake_events)

    events = calendar_tool.get_calendar_events(Mock(), 7, "2026-11-03", http=Mock())

    assert refresh_flags == [False, True]
    assert event_calls == ["stale-access", "fresh-access"]
    assert events[0]["id"] == "event-1"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"items": None},
        {"items": [{}]},
        {"items": [{"id": "bad", "start": {"dateTime": "bad"}, "end": {}}]},
        {"nextPageToken": 10},
    ],
)
def test_invalid_event_response_is_rejected(payload) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        with pytest.raises(CalendarResponseError, match="응답 형식"):
            fetch_calendar_events(http, "access-secret", date(2026, 11, 3))
