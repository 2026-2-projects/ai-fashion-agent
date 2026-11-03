"""Authenticated, read-only Calendar integration; no event mutation endpoints."""

import secrets
from collections.abc import Iterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user, require_csrf
from app.core.database import get_db
from app.services.calendar import CalendarService
from app.services.calendar_client import CalendarError

router = APIRouter(prefix="/calendar", tags=["Calendar"])
CurrentUser = Annotated[dict, Depends(get_current_user)]


def get_calendar_service(db: Annotated[Session, Depends(get_db)]) -> Iterator[CalendarService]:
    with httpx.Client(timeout=10) as http:
        yield CalendarService(db, http)


Service = Annotated[CalendarService, Depends(get_calendar_service)]


class ConnectionStatus(BaseModel):
    connected: bool
    reconnect_required: bool = False


class CalendarEventResponse(BaseModel):
    id: str
    title: str
    start: str
    end: str
    all_day: bool
    location: str


class EventsResponse(BaseModel):
    date: str
    timezone: str
    events: list[CalendarEventResponse]


def failure(exc: CalendarError) -> HTTPException:
    return HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})


@router.post("/connect", dependencies=[Depends(require_csrf)])
def connect(request: Request, response: Response, user: CurrentUser, service: Service) -> dict:
    response.headers["Cache-Control"] = "no-store"
    browser = request.session.setdefault("calendar_browser", secrets.token_urlsafe(32))
    try:
        return {"authorization_url": service.connect(user["id"], browser)}
    except CalendarError as exc:
        raise failure(exc) from None


@router.get("/callback", response_model=ConnectionStatus)
def callback(
    request: Request,
    response: Response,
    user: CurrentUser,
    service: Service,
    state: str = "",
    code: str = "",
    error: str = "",
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    try:
        service.callback(
            user["id"], request.session.get("calendar_browser", ""), state, code, error
        )
        return {"connected": True, "reconnect_required": False}
    except CalendarError as exc:
        raise failure(exc) from None


@router.get("/connection", response_model=ConnectionStatus)
def connection(response: Response, user: CurrentUser, service: Service) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return service.status(user["id"])


@router.get("/events", response_model=EventsResponse)
def events(
    response: Response,
    user: CurrentUser,
    service: Service,
    date: Annotated[str, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")],
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return service.events(user["id"], date)
    except CalendarError as exc:
        raise failure(exc) from None
