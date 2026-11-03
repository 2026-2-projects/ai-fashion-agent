"""WBS 4.4: per-user Google Calendar OAuth and read-only events API."""

import time
from datetime import date, datetime
from secrets import compare_digest, token_urlsafe
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.tools.calendar import get_calendar_events
from app.api.v1.auth import get_current_user, require_csrf
from app.core.database import get_db
from app.services.google_calendar import (
    CALENDAR_EVENTS_SCOPE,
    CalendarAuthorizationError,
    CalendarConfigurationError,
    CalendarExternalError,
    CalendarInputError,
    CalendarNotConnectedError,
    CalendarRateLimitError,
    CalendarResponseError,
    CalendarRevocationIncompleteError,
    build_authorization_url,
    disconnect_calendar,
    exchange_authorization_code,
    load_connection,
    load_oauth_config,
    save_connection,
)

router = APIRouter(prefix="/calendar", tags=["Calendar"])
CurrentUser = Annotated[dict, Depends(get_current_user)]
Database = Annotated[Session, Depends(get_db)]
CsrfCheck = Annotated[None, Depends(require_csrf)]

OAUTH_STATE_SESSION_KEY = "google_calendar_oauth"
OAUTH_STATE_TTL_SECONDS = 10 * 60


class OAuthStartResponse(BaseModel):
    authorization_url: str
    expires_in_seconds: int


class OAuthCallbackResponse(BaseModel):
    connected: bool
    scope: str


class CalendarConnectionResponse(BaseModel):
    connected: bool
    scope: str | None = None
    token_expires_at: datetime | None = None


class CalendarEventResponse(BaseModel):
    id: str
    title: str
    start: str
    end: str
    all_day: bool
    location: str


def _configuration_error(exc: CalendarConfigurationError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


def _consume_oauth_state(request: Request, user_id: int, returned_state: str | None) -> None:
    stored = request.session.pop(OAUTH_STATE_SESSION_KEY, None)
    if not isinstance(stored, dict) or not isinstance(returned_state, str):
        raise HTTPException(status_code=400, detail="OAuth state가 없거나 이미 사용되었습니다.")

    expected = stored.get("state")
    stored_user_id = stored.get("user_id")
    started_at = stored.get("started_at")
    if (
        not isinstance(expected, str)
        or not compare_digest(expected, returned_state)
        or stored_user_id != user_id
        or not isinstance(started_at, int)
        or isinstance(started_at, bool)
        or time.time() - started_at > OAUTH_STATE_TTL_SECONDS
        or started_at - time.time() > 60
    ):
        raise HTTPException(status_code=400, detail="OAuth state 검증에 실패했습니다.")


@router.post("/oauth/start", response_model=OAuthStartResponse)
def start_google_oauth(
    request: Request,
    user: CurrentUser,
    _: CsrfCheck,
) -> OAuthStartResponse:
    try:
        config = load_oauth_config()
    except CalendarConfigurationError as exc:
        raise _configuration_error(exc) from exc

    state_value = token_urlsafe(32)
    request.session[OAUTH_STATE_SESSION_KEY] = {
        "state": state_value,
        "user_id": user["id"],
        "started_at": int(time.time()),
    }
    return OAuthStartResponse(
        authorization_url=build_authorization_url(config, state_value),
        expires_in_seconds=OAUTH_STATE_TTL_SECONDS,
    )


@router.get("/oauth/callback", response_model=OAuthCallbackResponse)
def google_oauth_callback(
    request: Request,
    user: CurrentUser,
    db: Database,
    state_value: Annotated[str | None, Query(alias="state", max_length=256)] = None,
    code: Annotated[str | None, Query(max_length=4096)] = None,
    error: Annotated[str | None, Query(max_length=128)] = None,
) -> OAuthCallbackResponse:
    _consume_oauth_state(request, user["id"], state_value)
    if error is not None:
        raise HTTPException(status_code=400, detail="Google Calendar 연결이 취소되었습니다.")
    if code is None:
        raise HTTPException(status_code=400, detail="Google 인증 코드가 없습니다.")

    try:
        config = load_oauth_config()
        with httpx.Client() as http:
            tokens = exchange_authorization_code(http, config, code)
        save_connection(db, user["id"], tokens, config)
    except CalendarConfigurationError as exc:
        raise _configuration_error(exc) from exc
    except CalendarAuthorizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (CalendarExternalError, CalendarResponseError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return OAuthCallbackResponse(connected=True, scope=CALENDAR_EVENTS_SCOPE)


@router.get("/connection", response_model=CalendarConnectionResponse)
def calendar_connection(user: CurrentUser, db: Database) -> CalendarConnectionResponse:
    connection = load_connection(db, user["id"])
    if connection is None:
        return CalendarConnectionResponse(connected=False)
    return CalendarConnectionResponse(
        connected=True,
        scope=CALENDAR_EVENTS_SCOPE,
        token_expires_at=connection.token_expires_at,
    )


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
def delete_calendar_connection(
    user: CurrentUser,
    db: Database,
    _: CsrfCheck,
) -> Response:
    try:
        with httpx.Client() as http:
            disconnect_calendar(db, user["id"], http)
    except CalendarRevocationIncompleteError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/events", response_model=list[CalendarEventResponse])
def read_calendar_events(
    day: Annotated[date, Query(alias="date")],
    user: CurrentUser,
    db: Database,
) -> list[dict[str, str | bool]]:
    try:
        return get_calendar_events(db, user["id"], day.isoformat())
    except CalendarInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (CalendarNotConnectedError, CalendarAuthorizationError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CalendarConfigurationError as exc:
        raise _configuration_error(exc) from exc
    except CalendarRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (CalendarExternalError, CalendarResponseError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
