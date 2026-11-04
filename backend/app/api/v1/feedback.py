"""Authenticated LOOK feedback and saved outfit APIs."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user, require_csrf
from app.core.database import get_db
from app.services.feedback import (
    FeedbackService,
    FeedbackState,
    FeedbackWrite,
    SavedOutfit,
    SavedOutfits,
    SaveRequest,
)


def private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(tags=["Feedback & Saved Outfits"], dependencies=[Depends(private_response)])
CurrentUser = Annotated[dict, Depends(get_current_user)]
Database = Annotated[Session, Depends(get_db)]
CsrfCheck = Annotated[None, Depends(require_csrf)]
EMPTY_SAVE = SaveRequest()


@router.get("/outfits/{outfit_id}/feedback", response_model=FeedbackState)
def get_feedback(outfit_id: UUID, user: CurrentUser, db: Database):
    return FeedbackService(db).feedback(user["id"], outfit_id)


@router.put("/outfits/{outfit_id}/feedback", response_model=FeedbackState)
def put_feedback(
    outfit_id: UUID, payload: FeedbackWrite, user: CurrentUser, db: Database, _: CsrfCheck
):
    return FeedbackService(db).put_feedback(user["id"], outfit_id, payload)


@router.delete("/outfits/{outfit_id}/feedback", status_code=204)
def delete_feedback(outfit_id: UUID, user: CurrentUser, db: Database, _: CsrfCheck):
    FeedbackService(db).delete_feedback(user["id"], outfit_id)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/saved-outfits", response_model=SavedOutfits)
def list_saved_outfits(
    user: CurrentUser,
    db: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return FeedbackService(db).list_saved(user["id"], limit, offset)


@router.get("/saved-outfits/{outfit_id}", response_model=SavedOutfit)
def get_saved_outfit(outfit_id: UUID, user: CurrentUser, db: Database):
    return FeedbackService(db).saved(user["id"], outfit_id)


@router.put("/saved-outfits/{outfit_id}", response_model=SavedOutfit)
def save_outfit(
    outfit_id: UUID,
    user: CurrentUser,
    db: Database,
    _: CsrfCheck,
    payload: Annotated[SaveRequest, Body()] = EMPTY_SAVE,
):
    return FeedbackService(db).save(user["id"], outfit_id)


@router.delete("/saved-outfits/{outfit_id}", status_code=204)
def unsave_outfit(outfit_id: UUID, user: CurrentUser, db: Database, _: CsrfCheck):
    FeedbackService(db).unsave(user["id"], outfit_id)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
