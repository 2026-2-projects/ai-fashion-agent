"""Run from backend: python -m app.calendar_cli auth|events YYYY-MM-DD."""

import argparse
import json
import sys
from datetime import date

import httpx

from app.services.google_calendar import CalendarError, GoogleCalendarClient
from app.services.google_calendar_auth import get_credentials


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="로컬 Google Calendar 읽기 전용 검증")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("auth", help="브라우저에서 인증 또는 재인증")
    events = commands.add_parser("events", help="한국 시간 기준 날짜별 일정 조회")
    events.add_argument("date", type=date.fromisoformat)
    args = parser.parse_args(argv)
    try:
        credentials = get_credentials(authorize=args.command == "auth")
        if args.command == "auth":
            print("로컬 인증정보가 저장되었습니다. 일정 조회는 events 명령으로 확인하세요.")
        else:
            with httpx.Client() as http:
                result = GoogleCalendarClient(http, credentials.token).get_events(args.date)
            print(
                json.dumps(
                    {"events": [event.to_dict() for event in result]}, ensure_ascii=False, indent=2
                )
            )
        return 0
    except CalendarError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
