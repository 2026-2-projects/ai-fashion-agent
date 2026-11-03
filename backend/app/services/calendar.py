"""User-bound web OAuth and encrypted Calendar credentials; never stores events."""

import base64
import hashlib
import secrets
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import config
from app.services.calendar_client import CalendarError, GoogleCalendarClient

SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def now() -> datetime:
    return datetime.now(UTC)


def parse_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value or parsed == date.max:
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        raise CalendarError("날짜는 YYYY-MM-DD 형식이어야 합니다.", "invalid_date", 422) from None


class CalendarService:
    def __init__(self, db: Session, http: httpx.Client):
        self.db = db
        self.http = http

    def cipher(self) -> Fernet:
        try:
            return Fernet(config.GOOGLE_TOKEN_ENCRYPTION_KEY.encode())
        except (ValueError, TypeError):
            raise CalendarError(
                "Google 토큰 암호화 키를 설정하세요.", "configuration", 503
            ) from None

    def configuration(self) -> None:
        uri = urlparse(config.GOOGLE_REDIRECT_URI)
        if (
            not config.GOOGLE_CLIENT_ID
            or not config.GOOGLE_CLIENT_SECRET
            or (
                uri.scheme != "https"
                and not (uri.scheme == "http" and uri.hostname in {"localhost", "127.0.0.1"})
            )
            or not uri.netloc
            or uri.fragment
            or uri.query
        ):
            raise CalendarError("Google 웹 OAuth 환경변수를 확인하세요.", "configuration", 503)
        self.cipher()

    def decrypt(self, value: str) -> str:
        try:
            return self.cipher().decrypt(value.encode()).decode()
        except (InvalidToken, UnicodeError):
            raise CalendarError(
                "저장된 인증정보를 읽을 수 없습니다.", "configuration", 503
            ) from None

    def connect(self, user_id: int, browser: str) -> str:
        self.configuration()
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        cipher = self.cipher()
        self.db.execute(
            text("DELETE FROM google_calendar_oauth_states WHERE expires_at <= :now"),
            {"now": now()},
        )
        self.db.execute(
            text("""
            INSERT INTO google_calendar_oauth_states
                (state_hash, user_id, browser_hash, verifier_encrypted, expires_at)
            VALUES (:state, :user_id, :browser, :verifier, :expiry)
        """),
            {
                "state": digest(state),
                "user_id": user_id,
                "browser": digest(browser),
                "verifier": cipher.encrypt(verifier.encode()).decode(),
                "expiry": now() + timedelta(minutes=10),
            },
        )
        self.db.commit()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        return (
            AUTH_URL
            + "?"
            + urlencode(
                {
                    "client_id": config.GOOGLE_CLIENT_ID,
                    "redirect_uri": config.GOOGLE_REDIRECT_URI,
                    "response_type": "code",
                    "scope": SCOPE,
                    "access_type": "offline",
                    "prompt": "consent",
                    "state": state,
                    "code_challenge": challenge.decode().rstrip("="),
                    "code_challenge_method": "S256",
                }
            )
        )

    def exchange(self, data: dict[str, str]) -> dict:
        try:
            response = self.http.post(
                TOKEN_URL,
                data={
                    **data,
                    "client_id": config.GOOGLE_CLIENT_ID,
                    "client_secret": config.GOOGLE_CLIENT_SECRET,
                },
                timeout=10,
            )
            payload = response.json()
        except httpx.TimeoutException:
            raise CalendarError("Google 인증 요청 시간이 초과되었습니다.", "timeout", 504) from None
        except (httpx.RequestError, ValueError):
            raise CalendarError("Google 인증 서버 연결에 실패했습니다.", "upstream", 502) from None
        if not isinstance(payload, dict):
            raise CalendarError("Google 인증 응답이 올바르지 않습니다.")
        if response.status_code == 429:
            raise CalendarError("Google 호출 한도를 초과했습니다.", "rate_limit", 429)
        if not response.is_success:
            if payload.get("error") == "invalid_grant":
                raise CalendarError("Google Calendar를 다시 연결하세요.", "reconnect_required", 409)
            raise CalendarError("Google 인증에 실패했습니다.", "oauth_failed", 502)
        token, lifetime = payload.get("access_token"), payload.get("expires_in")
        if (
            not isinstance(token, str)
            or not token
            or (type(lifetime) is not int or not 0 < lifetime <= 86400)
            or str(payload.get("token_type", "")).lower() != "bearer"
        ):
            raise CalendarError("Google 인증 응답이 올바르지 않습니다.")
        if "scope" in payload and (
            not isinstance(payload["scope"], str) or set(payload["scope"].split()) != {SCOPE}
        ):
            raise CalendarError("일정 읽기 전용 권한만 허용됩니다.", "scope_denied", 403)
        return payload

    def callback(self, user_id: int, browser: str, state: str, code: str, error: str) -> None:
        self.configuration()
        row = (
            self.db.execute(
                text("""
            DELETE FROM google_calendar_oauth_states
            WHERE state_hash = :state AND user_id = :user_id AND browser_hash = :browser
                AND expires_at > :now
            RETURNING verifier_encrypted
        """),
                {
                    "state": digest(state),
                    "user_id": user_id,
                    "browser": digest(browser),
                    "now": now(),
                },
            )
            .mappings()
            .first()
        )
        # Commit consumption before any network call, including failed/denied authorizations.
        self.db.commit()
        if row is None:
            raise CalendarError("인증 요청이 만료되었거나 유효하지 않습니다.", "invalid_state", 400)
        if error or not code:
            raise CalendarError("Google 연결 동의가 완료되지 않았습니다.", "consent_denied", 400)
        payload = self.exchange(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.GOOGLE_REDIRECT_URI,
                "code_verifier": self.decrypt(row["verifier_encrypted"]),
            }
        )
        # Never pair a new account's access token with a previous account's refresh token.
        refresh = payload.get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            raise CalendarError("Google 연결에 다시 동의하세요.", "reconnect_required", 409)
        self.save(user_id, payload, refresh)

    def save(self, user_id: int, payload: dict, refresh: str) -> None:
        cipher = self.cipher()
        self.db.execute(
            text("""
            INSERT INTO google_calendar_connections
                (user_id, access_token_encrypted, refresh_token_encrypted, expires_at, scope)
            VALUES (:user_id, :access, :refresh, :expiry, :scope)
            ON CONFLICT (user_id) DO UPDATE SET
                access_token_encrypted = EXCLUDED.access_token_encrypted,
                refresh_token_encrypted = EXCLUDED.refresh_token_encrypted,
                expires_at = EXCLUDED.expires_at, scope = EXCLUDED.scope,
                reconnect_required = FALSE, updated_at = CURRENT_TIMESTAMP
        """),
            {
                "user_id": user_id,
                "access": cipher.encrypt(payload["access_token"].encode()).decode(),
                "refresh": cipher.encrypt(refresh.encode()).decode(),
                "expiry": now() + timedelta(seconds=payload["expires_in"]),
                "scope": SCOPE,
            },
        )
        self.db.commit()

    def status(self, user_id: int) -> dict[str, bool]:
        row = (
            self.db.execute(
                text("""
            SELECT reconnect_required FROM google_calendar_connections WHERE user_id = :user_id
        """),
                {"user_id": user_id},
            )
            .mappings()
            .first()
        )
        reconnect = bool(row and row["reconnect_required"])
        return {"connected": row is not None and not reconnect, "reconnect_required": reconnect}

    def refresh(self, user_id: int) -> str:
        # Reload under lock: another request may have rotated the refresh token.
        row = (
            self.db.execute(
                text("""
            SELECT refresh_token_encrypted, reconnect_required
            FROM google_calendar_connections WHERE user_id = :user_id FOR UPDATE
        """),
                {"user_id": user_id},
            )
            .mappings()
            .first()
        )
        if row is None or row["reconnect_required"]:
            self.db.rollback()
            raise CalendarError("Google Calendar를 다시 연결하세요.", "reconnect_required", 409)
        refresh = self.decrypt(row["refresh_token_encrypted"])
        try:
            payload = self.exchange({"grant_type": "refresh_token", "refresh_token": refresh})
        except CalendarError as exc:
            if exc.code in {"reconnect_required", "scope_denied"}:
                self.db.execute(
                    text("""
                    UPDATE google_calendar_connections SET reconnect_required = TRUE
                    WHERE user_id = :user_id
                """),
                    {"user_id": user_id},
                )
                self.db.commit()
            raise
        rotated = payload.get("refresh_token", refresh)
        if not isinstance(rotated, str) or not rotated:
            raise CalendarError("Google 인증 응답이 올바르지 않습니다.")
        self.save(user_id, payload, rotated)
        return payload["access_token"]

    def events(self, user_id: int, target: str) -> dict:
        day = parse_date(target)
        self.configuration()
        row = (
            self.db.execute(
                text("""
            SELECT * FROM google_calendar_connections WHERE user_id = :user_id FOR UPDATE
        """),
                {"user_id": user_id},
            )
            .mappings()
            .first()
        )
        if row is None or row["reconnect_required"]:
            self.db.rollback()
            raise CalendarError("Google Calendar를 연결하세요.", "reconnect_required", 409)
        access = self.decrypt(row["access_token_encrypted"])
        refreshed = row["expires_at"] <= now() + timedelta(seconds=60)
        if refreshed:
            access = self.refresh(user_id)
        else:
            self.db.commit()
        try:
            events = GoogleCalendarClient(self.http, access).get_events(day)
        except CalendarError as exc:
            if exc.code != "reconnect_required":
                raise
            if not refreshed:
                access = self.refresh(user_id)
                try:
                    events = GoogleCalendarClient(self.http, access).get_events(day)
                except CalendarError as retry:
                    if retry.code == "reconnect_required":
                        self.mark_reconnect(user_id)
                    raise
            else:
                self.mark_reconnect(user_id)
                raise
        return {
            "date": target,
            "timezone": "Asia/Seoul",
            "events": [event.to_dict() for event in events],
        }

    def mark_reconnect(self, user_id: int) -> None:
        self.db.execute(
            text("""
            UPDATE google_calendar_connections SET reconnect_required = TRUE
            WHERE user_id = :user_id
        """),
            {"user_id": user_id},
        )
        self.db.commit()
