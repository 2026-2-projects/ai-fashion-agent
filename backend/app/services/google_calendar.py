"""Google Calendar OAuth, encrypted token storage, and read-only event access."""

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import config as settings

CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
REQUIRED_SCOPES = frozenset({CALENDAR_EVENTS_SCOPE})
AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOCATION_ENDPOINT = "https://oauth2.googleapis.com/revoke"
EVENTS_ENDPOINT = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
KST = ZoneInfo("Asia/Seoul")
REFRESH_EARLY = timedelta(minutes=1)
MAX_EVENT_PAGES = 10
MAX_EVENTS = 1000


class CalendarServiceError(Exception):
    """Base class for safe errors that do not contain tokens or upstream payloads."""


class CalendarConfigurationError(CalendarServiceError):
    """Required local OAuth configuration is missing or invalid."""


class CalendarNotConnectedError(CalendarServiceError):
    """The current service user has no Google Calendar connection."""


class CalendarAuthorizationError(CalendarServiceError):
    """Google authorization is missing, denied, expired, or revoked."""


class CalendarExternalError(CalendarServiceError):
    """Google could not be reached or returned a server-side failure."""


class CalendarRateLimitError(CalendarServiceError):
    """Google rejected the request because of a quota or rate limit."""


class CalendarResponseError(CalendarServiceError):
    """Google returned an unexpected response shape."""


class CalendarInputError(CalendarServiceError):
    """An Agent Tool input is invalid."""


class CalendarRevocationIncompleteError(CalendarServiceError):
    """Local tokens were deleted but Google revocation was not confirmed."""


class CalendarAccessTokenRejected(CalendarAuthorizationError):
    """Internal signal used to force exactly one refresh-and-retry."""


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    token_encryption_key: str


@dataclass(frozen=True)
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scopes: frozenset[str]


@dataclass(frozen=True)
class CalendarConnection:
    user_id: int
    access_token_encrypted: str
    refresh_token_encrypted: str | None
    token_expires_at: datetime
    scope: str


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    title: str
    start: str
    end: str
    all_day: bool
    location: str

    def to_dict(self) -> dict[str, str | bool]:
        return asdict(self)


def load_oauth_config() -> GoogleOAuthConfig:
    values = {
        "GOOGLE_CLIENT_ID": settings.GOOGLE_CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": settings.GOOGLE_CLIENT_SECRET,
        "GOOGLE_REDIRECT_URI": settings.GOOGLE_REDIRECT_URI,
        "GOOGLE_TOKEN_ENCRYPTION_KEY": settings.GOOGLE_TOKEN_ENCRYPTION_KEY,
    }
    missing = [
        name for name, value in values.items() if (not isinstance(value, str) or not value.strip())
    ]
    if missing:
        raise CalendarConfigurationError(
            "Google Calendar 환경변수가 준비되지 않았습니다: " + ", ".join(missing)
        )

    redirect = urlsplit(values["GOOGLE_REDIRECT_URI"])
    is_local_http = redirect.scheme == "http" and redirect.hostname in {"localhost", "127.0.0.1"}
    if redirect.scheme != "https" and not is_local_http:
        raise CalendarConfigurationError(
            "GOOGLE_REDIRECT_URI는 HTTPS 또는 로컬 개발용 localhost 주소여야 합니다."
        )

    config = GoogleOAuthConfig(
        client_id=values["GOOGLE_CLIENT_ID"].strip(),
        client_secret=values["GOOGLE_CLIENT_SECRET"].strip(),
        redirect_uri=values["GOOGLE_REDIRECT_URI"].strip(),
        token_encryption_key=values["GOOGLE_TOKEN_ENCRYPTION_KEY"].strip(),
    )
    _token_cipher(config)
    return config


def _token_cipher(config: GoogleOAuthConfig) -> Fernet:
    try:
        return Fernet(config.token_encryption_key.encode("ascii"))
    except (TypeError, ValueError, UnicodeEncodeError):
        raise CalendarConfigurationError(
            "GOOGLE_TOKEN_ENCRYPTION_KEY는 Fernet 형식의 유효한 키여야 합니다."
        ) from None


def encrypt_token(token: str, config: GoogleOAuthConfig) -> str:
    if not isinstance(token, str) or not token:
        raise CalendarAuthorizationError("저장할 Google 인증 토큰이 없습니다.")
    return _token_cipher(config).encrypt(token.encode()).decode("ascii")


def decrypt_token(token_encrypted: str, config: GoogleOAuthConfig) -> str:
    try:
        token = _token_cipher(config).decrypt(token_encrypted.encode("ascii")).decode()
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError, AttributeError):
        raise CalendarAuthorizationError(
            "저장된 Google 인증정보를 읽을 수 없습니다. Calendar를 다시 연결해 주세요."
        ) from None
    if not token:
        raise CalendarAuthorizationError(
            "저장된 Google 인증정보가 비어 있습니다. Calendar를 다시 연결해 주세요."
        )
    return token


def build_authorization_url(config: GoogleOAuthConfig, state: str) -> str:
    if not state:
        raise CalendarAuthorizationError("OAuth state를 생성하지 못했습니다.")
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": CALENDAR_EVENTS_SCOPE,
        "access_type": "offline",
        "include_granted_scopes": "false",
        "prompt": "consent select_account",
        "state": state,
    }
    return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


def _post_token(http: httpx.Client, data: dict[str, str], error_message: str) -> dict:
    try:
        response = http.post(TOKEN_ENDPOINT, data=data, timeout=10)
    except httpx.TimeoutException:
        raise CalendarExternalError("Google 인증 요청 시간이 초과되었습니다.") from None
    except httpx.RequestError:
        raise CalendarExternalError("Google 인증 서버에 연결하지 못했습니다.") from None

    if response.status_code in {400, 401}:
        raise CalendarAuthorizationError(error_message)
    if not response.is_success:
        raise CalendarExternalError("Google 인증 서버가 요청을 처리하지 못했습니다.")
    try:
        payload = response.json()
    except ValueError:
        raise CalendarResponseError("Google 인증 응답 형식이 올바르지 않습니다.") from None
    if not isinstance(payload, dict):
        raise CalendarResponseError("Google 인증 응답 형식이 올바르지 않습니다.")
    return payload


def _parse_token_response(payload: dict, existing_refresh_token: str | None = None) -> OAuthTokens:
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token", existing_refresh_token)
    expires_in = payload.get("expires_in")
    token_type = payload.get("token_type")
    scope = payload.get("scope")

    if not isinstance(access_token, str) or not access_token:
        raise CalendarResponseError("Google 인증 응답에 Access Token이 없습니다.")
    if not isinstance(expires_in, int) or isinstance(expires_in, bool) or expires_in <= 0:
        raise CalendarResponseError("Google 인증 응답의 만료 시간이 올바르지 않습니다.")
    if not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise CalendarResponseError("Google 인증 응답의 Token 유형이 올바르지 않습니다.")
    if refresh_token is not None and (not isinstance(refresh_token, str) or not refresh_token):
        raise CalendarResponseError("Google 인증 응답의 Refresh Token이 올바르지 않습니다.")

    if scope is None:
        scopes = REQUIRED_SCOPES
    elif isinstance(scope, str):
        scopes = frozenset(scope.split())
    else:
        raise CalendarResponseError("Google 인증 응답의 권한 범위가 올바르지 않습니다.")
    if not REQUIRED_SCOPES.issubset(scopes):
        raise CalendarAuthorizationError(
            "일정 읽기 권한이 승인되지 않았습니다. Calendar를 다시 연결해 주세요."
        )

    return OAuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        scopes=scopes,
    )


def exchange_authorization_code(
    http: httpx.Client,
    config: GoogleOAuthConfig,
    code: str,
) -> OAuthTokens:
    if not code:
        raise CalendarAuthorizationError("Google 인증 코드가 없습니다.")
    payload = _post_token(
        http,
        {
            "code": code,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "redirect_uri": config.redirect_uri,
            "grant_type": "authorization_code",
        },
        "Google 인증 코드가 만료되었거나 이미 사용되었습니다. 다시 연결해 주세요.",
    )
    return _parse_token_response(payload)


def refresh_access_token(
    http: httpx.Client,
    config: GoogleOAuthConfig,
    refresh_token: str,
) -> OAuthTokens:
    payload = _post_token(
        http,
        {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        "Google 인증이 만료되거나 취소되었습니다. Calendar를 다시 연결해 주세요.",
    )
    return _parse_token_response(payload, existing_refresh_token=refresh_token)


def load_connection(db: Session, user_id: int) -> CalendarConnection | None:
    row = (
        db.execute(
            text("""
                SELECT user_id, access_token_encrypted, refresh_token_encrypted,
                       token_expires_at, scope
                FROM google_calendar_connections
                WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    values = dict(row)
    if (
        not isinstance(values["access_token_encrypted"], str)
        or not isinstance(values["token_expires_at"], datetime)
        or not isinstance(values["scope"], str)
    ):
        raise CalendarAuthorizationError(
            "저장된 Google 인증정보가 올바르지 않습니다. Calendar를 다시 연결해 주세요."
        )
    return CalendarConnection(**values)


def save_connection(
    db: Session,
    user_id: int,
    tokens: OAuthTokens,
    config: GoogleOAuthConfig,
) -> None:
    refresh_token = tokens.refresh_token
    if refresh_token is None:
        existing = load_connection(db, user_id)
        if existing is not None and existing.refresh_token_encrypted:
            refresh_token = decrypt_token(existing.refresh_token_encrypted, config)
    if refresh_token is None:
        raise CalendarAuthorizationError(
            "Refresh Token을 받지 못했습니다. Google 계정 권한을 확인한 뒤 다시 연결해 주세요."
        )

    params = {
        "user_id": user_id,
        "access_token_encrypted": encrypt_token(tokens.access_token, config),
        "refresh_token_encrypted": encrypt_token(refresh_token, config),
        "token_expires_at": tokens.expires_at,
        "scope": " ".join(sorted(tokens.scopes)),
    }
    try:
        db.execute(
            text("""
                INSERT INTO google_calendar_connections (
                    user_id, google_account_email, access_token_encrypted,
                    refresh_token_encrypted, token_expires_at, scope
                )
                VALUES (
                    :user_id, NULL, :access_token_encrypted,
                    :refresh_token_encrypted, :token_expires_at, :scope
                )
                ON CONFLICT (user_id) DO UPDATE SET
                    google_account_email = NULL,
                    access_token_encrypted = EXCLUDED.access_token_encrypted,
                    refresh_token_encrypted = EXCLUDED.refresh_token_encrypted,
                    token_expires_at = EXCLUDED.token_expires_at,
                    scope = EXCLUDED.scope,
                    updated_at = CURRENT_TIMESTAMP
            """),
            params,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def get_access_token(
    db: Session,
    user_id: int,
    http: httpx.Client,
    *,
    force_refresh: bool = False,
) -> str:
    config = load_oauth_config()
    connection = load_connection(db, user_id)
    if connection is None:
        raise CalendarNotConnectedError("Google Calendar가 연결되지 않았습니다.")

    access_token = decrypt_token(connection.access_token_encrypted, config)
    now = datetime.now(UTC)
    if not force_refresh and _as_utc(connection.token_expires_at) > now + REFRESH_EARLY:
        return access_token

    if not connection.refresh_token_encrypted:
        raise CalendarAuthorizationError(
            "Google 인증을 갱신할 수 없습니다. Calendar를 다시 연결해 주세요."
        )
    refresh_token = decrypt_token(connection.refresh_token_encrypted, config)
    refreshed = refresh_access_token(http, config, refresh_token)
    save_connection(db, user_id, refreshed, config)
    return refreshed.access_token


def _parse_event(item: dict) -> CalendarEvent:
    if not isinstance(item, dict):
        raise ValueError("event is not an object")
    event_id = item.get("id")
    title = item.get("summary", "")
    location = item.get("location", "")
    start_data = item.get("start")
    end_data = item.get("end")
    if (
        not isinstance(event_id, str)
        or not event_id
        or not isinstance(title, str)
        or not isinstance(location, str)
        or not isinstance(start_data, dict)
        or not isinstance(end_data, dict)
    ):
        raise ValueError("invalid event fields")

    all_day = "date" in start_data or "date" in end_data
    field = "date" if all_day else "dateTime"
    start = start_data.get(field)
    end = end_data.get(field)
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("invalid event interval")
    if all_day:
        if date.fromisoformat(end) <= date.fromisoformat(start):
            raise ValueError("invalid all-day interval")
    else:
        first = datetime.fromisoformat(start.replace("Z", "+00:00"))
        last = datetime.fromisoformat(end.replace("Z", "+00:00"))
        if first.tzinfo is None or last.tzinfo is None or last <= first:
            raise ValueError("invalid timed interval")
    return CalendarEvent(event_id, title, start, end, all_day, location)


def fetch_calendar_events(
    http: httpx.Client,
    access_token: str,
    day: date,
) -> list[CalendarEvent]:
    start = datetime.combine(day, time.min, KST)
    params = {
        "timeMin": start.isoformat(),
        "timeMax": (start + timedelta(days=1)).isoformat(),
        "timeZone": "Asia/Seoul",
        "singleEvents": "true",
        "orderBy": "startTime",
        "showDeleted": "false",
        "maxResults": "250",
        "fields": (
            "nextPageToken,items(id,summary,location,status,"
            "start(date,dateTime),end(date,dateTime))"
        ),
    }
    events: list[CalendarEvent] = []
    seen_page_tokens: set[str] = set()

    for _ in range(MAX_EVENT_PAGES):
        try:
            response = http.get(
                EVENTS_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
                timeout=10,
            )
        except httpx.TimeoutException:
            raise CalendarExternalError("Google Calendar 요청 시간이 초과되었습니다.") from None
        except httpx.RequestError:
            raise CalendarExternalError("Google Calendar에 연결하지 못했습니다.") from None

        if response.status_code == 401:
            raise CalendarAccessTokenRejected(
                "Google 인증이 만료되거나 취소되었습니다. Calendar를 다시 연결해 주세요."
            )
        if response.status_code == 429:
            raise CalendarRateLimitError("Google Calendar 호출 한도를 초과했습니다.")
        if response.status_code == 403:
            try:
                reasons = {
                    error.get("reason")
                    for error in response.json().get("error", {}).get("errors", [])
                    if isinstance(error, dict)
                }
            except (ValueError, AttributeError):
                reasons = set()
            if reasons & {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}:
                raise CalendarRateLimitError("Google Calendar 호출 한도를 초과했습니다.")
            raise CalendarAuthorizationError(
                "Google Calendar 읽기 권한이 없거나 취소되었습니다. 다시 연결해 주세요."
            )
        if not response.is_success:
            raise CalendarExternalError("Google Calendar 조회에 실패했습니다.")

        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("payload is not an object")
            items = payload.get("items", [])
            if not isinstance(items, list):
                raise ValueError("items is not a list")
            for item in items:
                if isinstance(item, dict) and item.get("status") == "cancelled":
                    continue
                events.append(_parse_event(item))
                if len(events) > MAX_EVENTS:
                    raise ValueError("too many events")
            page_token = payload.get("nextPageToken")
            if page_token is None:
                return events
            if not isinstance(page_token, str) or not page_token or page_token in seen_page_tokens:
                raise ValueError("invalid page token")
            seen_page_tokens.add(page_token)
            params["pageToken"] = page_token
        except (ValueError, TypeError, KeyError, AttributeError):
            raise CalendarResponseError("Google Calendar 응답 형식이 올바르지 않습니다.") from None

    raise CalendarResponseError("Google Calendar 일정 페이지가 너무 많습니다.")


def revoke_token(http: httpx.Client, token: str) -> None:
    try:
        response = http.post(
            REVOCATION_ENDPOINT,
            data={"token": token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
    except httpx.TimeoutException:
        raise CalendarExternalError("Google 권한 철회 요청 시간이 초과되었습니다.") from None
    except httpx.RequestError:
        raise CalendarExternalError("Google 권한 철회 서버에 연결하지 못했습니다.") from None
    # 400은 이미 만료·철회된 토큰에서도 반환될 수 있으므로 로컬 연결 해제를 막지 않는다.
    if response.status_code not in {200, 400}:
        raise CalendarExternalError("Google 권한 철회를 확인하지 못했습니다.")


def disconnect_calendar(db: Session, user_id: int, http: httpx.Client) -> bool:
    connection = load_connection(db, user_id)
    if connection is None:
        return False

    revoke_failed = False
    try:
        config = load_oauth_config()
        encrypted = connection.refresh_token_encrypted or connection.access_token_encrypted
        revoke_token(http, decrypt_token(encrypted, config))
    except CalendarServiceError:
        revoke_failed = True

    try:
        db.execute(
            text("DELETE FROM google_calendar_connections WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    if revoke_failed:
        raise CalendarRevocationIncompleteError(
            "로컬 연결은 해제했지만 Google 권한 철회를 확인하지 못했습니다. "
            "Google 계정의 보안 설정에서 앱 권한을 확인해 주세요."
        )
    return True
