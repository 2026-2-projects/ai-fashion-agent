"""Read-only Google Calendar client; no credentials or events are logged."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx


class CalendarError(Exception):
    """Safe, user-facing error independent of upstream response contents."""


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    title: str
    start: str
    end: str
    all_day: bool
    location: str

    def to_dict(self) -> dict:
        return asdict(self)


def _event(item: dict) -> CalendarEvent:
    all_day = "date" in item["start"]
    field = "date" if all_day else "dateTime"
    start, end = item["start"][field], item["end"][field]
    values = [item["id"], item.get("summary", ""), start, end, item.get("location", "")]
    if not all(isinstance(value, str) for value in values):
        raise ValueError("Invalid event fields")
    if all_day:
        if date.fromisoformat(end) <= date.fromisoformat(start):
            raise ValueError("Invalid interval")
    else:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if first.tzinfo is None or last.tzinfo is None or last <= first:
            raise ValueError("Invalid interval")
    return CalendarEvent(values[0], values[1], start, end, all_day, values[4])


class GoogleCalendarClient:
    def __init__(self, http: httpx.Client, access_token: str):
        self.http = http
        self.access_token = access_token

    def get_events(self, day: date) -> list[CalendarEvent]:
        if not self.access_token.strip():
            raise CalendarError("인증 토큰이 없습니다. auth 명령으로 인증하세요.")
        start = datetime.combine(day, time.min, ZoneInfo("Asia/Seoul"))
        params = {
            "timeMin": start.isoformat(),
            "timeMax": (start + timedelta(days=1)).isoformat(),
            "timeZone": "Asia/Seoul",
            "singleEvents": "true",
            "orderBy": "startTime",
            "showDeleted": "false",
            "maxResults": "2500",
        }
        events, seen_tokens = [], set()
        while True:
            try:
                response = self.http.get(
                    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                    headers={"Authorization": f"Bearer {self.access_token}"},
                    params=params,
                    timeout=10,
                )
            except httpx.TimeoutException:
                raise CalendarError("Google Calendar 요청 시간이 초과되었습니다.") from None
            except httpx.RequestError:
                raise CalendarError("Google Calendar 네트워크 연결에 실패했습니다.") from None
            if response.status_code == 401:
                raise CalendarError("인증이 만료되거나 취소되었습니다. auth 명령으로 재인증하세요.")
            if response.status_code == 429:
                raise CalendarError("호출 한도를 초과했습니다. 잠시 후 다시 시도하세요.")
            if response.status_code == 403:
                try:
                    reasons = {
                        error.get("reason") for error in response.json()["error"].get("errors", [])
                    }
                except (ValueError, KeyError, TypeError, AttributeError):
                    reasons = set()
                if reasons & {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}:
                    raise CalendarError("호출 한도를 초과했습니다. 잠시 후 다시 시도하세요.")
                raise CalendarError("읽기 권한 또는 Google Calendar API 활성화 설정을 확인하세요.")
            if not response.is_success:
                raise CalendarError("Google Calendar 조회에 실패했습니다. 잠시 후 다시 시도하세요.")
            try:
                data = response.json()
                items = data.get("items", [])
                if not isinstance(items, list):
                    raise ValueError("Invalid items")
                for item in items:
                    if item.get("status") != "cancelled":
                        events.append(_event(item))
                token = data.get("nextPageToken")
                if token is None:
                    return events
                if not isinstance(token, str) or not token or token in seen_tokens:
                    raise ValueError("Invalid pagination")
                seen_tokens.add(token)
                params["pageToken"] = token
            except (ValueError, KeyError, TypeError, AttributeError):
                raise CalendarError("Google Calendar 응답 형식이 올바르지 않습니다.") from None
