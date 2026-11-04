"""Agent Tool for a service user's read-only Google Calendar events."""

import re
from datetime import date

import httpx
from sqlalchemy.orm import Session

from app.services.google_calendar import (
    CalendarAccessTokenRejected,
    CalendarInputError,
    fetch_calendar_events,
    get_access_token,
)

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_calendar_events(
    db: Session,
    user_id: int,
    date_value: str,
    *,
    http: httpx.Client | None = None,
) -> list[dict[str, str | bool]]:
    """Return one KST day's events for exactly one authenticated service user."""
    if not ISO_DATE.fullmatch(date_value):
        raise CalendarInputError("날짜는 YYYY-MM-DD 형식으로 입력해 주세요.")
    try:
        day = date.fromisoformat(date_value)
    except ValueError:
        raise CalendarInputError("존재하는 날짜를 입력해 주세요.") from None

    owns_http = http is None
    client = http or httpx.Client()
    try:
        access_token = get_access_token(db, user_id, client)
        try:
            events = fetch_calendar_events(client, access_token, day)
        except CalendarAccessTokenRejected:
            access_token = get_access_token(db, user_id, client, force_refresh=True)
            events = fetch_calendar_events(client, access_token, day)
        return [event.to_dict() for event in events]
    finally:
        if owns_http:
            client.close()
