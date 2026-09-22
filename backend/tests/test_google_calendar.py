from datetime import date
from unittest.mock import Mock

import httpx
import pytest
from google.auth.exceptions import RefreshError

from app import calendar_cli
from app.services import google_calendar_auth as auth
from app.services.google_calendar import CalendarError, GoogleCalendarClient

DAY = date(2026, 9, 22)
EVENT = {
    "id": "one",
    "summary": "회의",
    "location": "서울",
    "start": {"dateTime": "2026-09-22T10:00:00+09:00"},
    "end": {"dateTime": "2026-09-22T11:00:00+09:00"},
    "recurringEventId": "series",
}


def fetch(handler):
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        return GoogleCalendarClient(http, "secret-token").get_events(DAY)


def test_request_and_pagination():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/calendar/v3/calendars/primary/events"
        assert request.headers["Authorization"] == "Bearer secret-token"
        assert request.url.params["timeMin"] == "2026-09-22T00:00:00+09:00"
        assert request.url.params["timeMax"] == "2026-09-23T00:00:00+09:00"
        assert request.url.params["singleEvents"] == "true"
        assert request.url.params["showDeleted"] == "false"
        assert request.url.params["orderBy"] == "startTime"
        if len(requests) == 1:
            return httpx.Response(200, json={"items": [EVENT], "nextPageToken": "next"})
        assert request.url.params["pageToken"] == "next"
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": "cancelled", "status": "cancelled"},
                    {"id": "day", "start": {"date": "2026-09-21"}, "end": {"date": "2026-09-23"}},
                ]
            },
        )

    result = fetch(handler)
    assert len(requests) == 2
    assert result[0].to_dict() == {
        "id": "one",
        "title": "회의",
        "location": "서울",
        "all_day": False,
        "start": "2026-09-22T10:00:00+09:00",
        "end": "2026-09-22T11:00:00+09:00",
    }
    assert result[1].all_day
    assert result[1].end == "2026-09-23"
    assert result[1].title == ""


def test_empty():
    assert fetch(lambda _: httpx.Response(200, json={"items": []})) == []


@pytest.mark.parametrize(
    "status,match",
    [
        (401, "재인증"),
        (403, "권한"),
        (429, "한도"),
        (500, "조회에 실패"),
    ],
)
def test_http_errors(status, match):
    with pytest.raises(CalendarError, match=match) as error:
        fetch(lambda _: httpx.Response(status, json={"secret": "secret-token"}))
    assert "secret-token" not in str(error.value)


def test_403_quota():
    with pytest.raises(CalendarError, match="한도"):
        fetch(
            lambda _: httpx.Response(
                403,
                json={
                    "error": {"errors": [{"reason": "userRateLimitExceeded"}]},
                },
            )
        )


@pytest.mark.parametrize(
    "exception,match",
    [
        (httpx.ReadTimeout, "시간"),
        (httpx.ConnectError, "네트워크"),
    ],
)
def test_network_errors(exception, match):
    def handler(request):
        raise exception("secret-token", request=request)

    with pytest.raises(CalendarError, match=match):
        fetch(handler)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"items": None},
        {"items": [{}]},
        {"items": [None]},
        {"nextPageToken": 12},
        {"items": [{**EVENT, "start": {"dateTime": "bad"}}]},
    ],
)
def test_invalid_response(payload):
    with pytest.raises(CalendarError, match="응답 형식"):
        fetch(lambda _: httpx.Response(200, json=payload))


def test_invalid_json():
    with pytest.raises(CalendarError, match="응답 형식"):
        fetch(lambda _: httpx.Response(200, text="not-json"))


def test_repeated_page():
    with pytest.raises(CalendarError, match="응답 형식"):
        fetch(lambda _: httpx.Response(200, json={"nextPageToken": "same"}))


def test_missing_token():
    http = Mock()
    with pytest.raises(CalendarError, match="토큰이 없습니다"):
        GoogleCalendarClient(http, " ").get_events(DAY)
    http.get.assert_not_called()


def test_missing_credentials(tmp_path):
    with pytest.raises(CalendarError, match="먼저 auth"):
        auth.get_credentials(token_file=tmp_path / "missing.json")


def test_refresh_and_secure_save(tmp_path, monkeypatch):
    token_file = tmp_path / "token.json"
    token_file.touch()
    credentials = Mock(valid=False, scopes=auth.SCOPES, refresh_token="refresh")
    credentials.to_json.return_value = '{"token":"new"}'
    monkeypatch.setattr(
        auth.Credentials, "from_authorized_user_file", Mock(return_value=credentials)
    )
    assert auth.get_credentials(token_file=token_file) is credentials
    credentials.refresh.assert_called_once()
    assert token_file.read_text() == '{"token":"new"}'
    assert token_file.stat().st_mode & 0o777 == 0o600


def test_refresh_failure(tmp_path, monkeypatch):
    token_file = tmp_path / "token.json"
    token_file.touch()
    credentials = Mock(valid=False, scopes=auth.SCOPES, refresh_token="refresh")
    credentials.refresh.side_effect = RefreshError("secret-token")
    monkeypatch.setattr(
        auth.Credentials, "from_authorized_user_file", Mock(return_value=credentials)
    )
    with pytest.raises(CalendarError, match="재인증") as error:
        auth.get_credentials(token_file=token_file)
    assert "secret-token" not in str(error.value)
    assert token_file.read_text() == ""


def test_valid_credentials_no_refresh(tmp_path, monkeypatch):
    path = tmp_path / "token.json"
    path.touch()
    credentials = Mock(valid=True, scopes=auth.SCOPES)
    monkeypatch.setattr(
        auth.Credentials, "from_authorized_user_file", Mock(return_value=credentials)
    )
    auth.get_credentials(token_file=path)
    credentials.refresh.assert_not_called()


def test_desktop_auth(tmp_path, monkeypatch):
    credentials = Mock()
    credentials.to_json.return_value = "{}"
    flow = Mock()
    flow.run_local_server.return_value = credentials
    factory = Mock(return_value=flow)
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_secrets_file", factory)
    auth.get_credentials(
        authorize=True, client_file=tmp_path / "client.json", token_file=tmp_path / "token.json"
    )
    assert factory.call_args.args[1] == auth.SCOPES
    assert flow.run_local_server.call_args.kwargs["host"] == "127.0.0.1"
    assert (tmp_path / "token.json").exists()


def test_cli_error(monkeypatch, capsys):
    monkeypatch.setattr(calendar_cli, "get_credentials", Mock(side_effect=CalendarError("재인증")))
    assert calendar_cli.main(["events", "2026-09-22"]) == 1
    assert capsys.readouterr().err.strip() == "재인증"


def test_cli_invalid_date():
    with pytest.raises(SystemExit) as error:
        calendar_cli.main(["events", "bad"])
    assert error.value.code == 2


@pytest.mark.parametrize(
    "scopes,refresh_token,match",
    [
        (["https://www.googleapis.com/auth/calendar"], "refresh", "권한이 다릅니다"),
        (auth.SCOPES, None, "갱신 토큰"),
    ],
)
def test_unusable_credentials(tmp_path, monkeypatch, scopes, refresh_token, match):
    path = tmp_path / "token.json"
    path.touch()
    credentials = Mock(valid=False, scopes=scopes, refresh_token=refresh_token)
    monkeypatch.setattr(
        auth.Credentials, "from_authorized_user_file", Mock(return_value=credentials)
    )
    with pytest.raises(CalendarError, match=match):
        auth.get_credentials(token_file=path)
    credentials.refresh.assert_not_called()


def test_auth_timeout(tmp_path, monkeypatch):
    flow = Mock()
    flow.run_local_server.side_effect = AttributeError("timeout-sensitive-data")
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_secrets_file", Mock(return_value=flow))
    with pytest.raises(CalendarError, match="인증에 실패"):
        auth.get_credentials(authorize=True, token_file=tmp_path / "token.json")
    assert not (tmp_path / "token.json").exists()


def test_cli_success(monkeypatch, capsys):
    monkeypatch.setattr(calendar_cli, "get_credentials", Mock(return_value=Mock(token="secret")))
    monkeypatch.setattr(calendar_cli.GoogleCalendarClient, "get_events", Mock(return_value=[]))
    assert calendar_cli.main(["events", "2026-09-22"]) == 0
    assert '"events": []' in capsys.readouterr().out
