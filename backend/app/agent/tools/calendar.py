"""Only date is model-controlled; db and user_id come from authenticated runtime."""

import httpx
from sqlalchemy.orm import Session

from app.services.calendar import CalendarService

CALENDAR_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_calendar_events",
        "description": "지정 날짜의 본인 Google Calendar 일정·시간·장소를 읽기 전용 조회합니다.",
        "parameters": {
            "type": "object",
            "properties": {"date": {"type": "string", "description": "YYYY-MM-DD, 한국 시간"}},
            "required": ["date"],
            "additionalProperties": False,
        },
    },
}


def get_calendar_events(
    db: Session, user_id: int, date: str, *, http: httpx.Client | None = None
) -> dict:
    """The caller must obtain user_id from its authenticated session, never from the LLM."""
    if http is not None:
        return CalendarService(db, http).events(user_id, date)
    with httpx.Client(timeout=10) as client:
        return CalendarService(db, client).events(user_id, date)
