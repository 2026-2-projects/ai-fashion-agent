"""WBS 4.6 추천 LOOK 평가·저장·개인화 API."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user, require_csrf
from app.core.database import get_db
from app.services.recommendation_interactions import (
    LookUnavailableError,
    RecommendationNotFoundError,
    StoredRecommendationError,
    delete_feedback,
    delete_saved_look,
    get_interactions,
    list_saved_outfits,
    save_look,
    set_feedback,
)

router = APIRouter(tags=["Recommendation Interactions"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
Database = Annotated[Session, Depends(get_db)]
CsrfCheck = Annotated[None, Depends(require_csrf)]
LookId = Annotated[int, Path(ge=1, le=5)]
FeedbackReason = Literal[
    "color",
    "fit",
    "not_my_style",
    "too_dressed_up",
    "too_plain",
]


class FeedbackUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_type: Literal["like", "dislike"]
    reason: FeedbackReason | None = None

    @model_validator(mode="after")
    def validate_reason_usage(self) -> "FeedbackUpdate":
        if self.feedback_type == "like" and self.reason is not None:
            raise ValueError("좋아요에는 싫어요 사유를 함께 보낼 수 없습니다.")
        return self


class LookInteractionState(BaseModel):
    recommendation_id: UUID
    look_id: int
    status: Literal["available", "unavailable"]
    feedback: Literal["like", "dislike"] | None
    reason: FeedbackReason | None
    saved: bool


class RecommendationInteractionsResponse(BaseModel):
    recommendation_id: UUID
    looks: list[LookInteractionState]


class SavedOutfitResponse(BaseModel):
    id: int
    recommendation_id: UUID | None
    look_id: int | None
    title: str | None
    outfit_data: dict[str, Any]
    created_at: datetime


def _raise_interaction_error(db: Session, exc: Exception) -> None:
    db.rollback()
    if isinstance(exc, RecommendationNotFoundError):
        raise HTTPException(
            status_code=404,
            detail="추천을 찾을 수 없습니다.",
        ) from exc
    if isinstance(exc, LookUnavailableError):
        raise HTTPException(
            status_code=409,
            detail="사용할 수 없는 LOOK에는 평가하거나 저장할 수 없습니다.",
        ) from exc
    if isinstance(exc, StoredRecommendationError):
        raise HTTPException(
            status_code=500,
            detail="저장된 추천 데이터가 올바르지 않습니다.",
        ) from exc
    if isinstance(exc, SQLAlchemyError):
        raise HTTPException(
            status_code=500,
            detail="추천 상태를 저장하는 중 오류가 발생했습니다.",
        ) from exc
    raise exc


def _mutate(
    db: Session,
    operation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    try:
        state = operation()
        db.commit()
        return state
    except (
        RecommendationNotFoundError,
        LookUnavailableError,
        StoredRecommendationError,
        SQLAlchemyError,
    ) as exc:
        _raise_interaction_error(db, exc)
        raise AssertionError("unreachable") from exc


@router.get(
    "/recommendations/{recommendation_id}/interactions",
    response_model=RecommendationInteractionsResponse,
)
def read_recommendation_interactions(
    recommendation_id: UUID,
    user: CurrentUser,
    db: Database,
) -> RecommendationInteractionsResponse:
    try:
        looks = get_interactions(db, user["id"], recommendation_id)
    except (RecommendationNotFoundError, StoredRecommendationError, SQLAlchemyError) as exc:
        _raise_interaction_error(db, exc)
        raise AssertionError("unreachable") from exc
    return RecommendationInteractionsResponse(
        recommendation_id=recommendation_id,
        looks=looks,
    )


@router.put(
    "/recommendations/{recommendation_id}/looks/{look_id}/feedback",
    response_model=LookInteractionState,
)
def update_look_feedback(
    recommendation_id: UUID,
    look_id: LookId,
    payload: FeedbackUpdate,
    user: CurrentUser,
    db: Database,
    _: CsrfCheck,
) -> dict[str, Any]:
    return _mutate(
        db,
        lambda: set_feedback(
            db,
            user["id"],
            recommendation_id,
            look_id,
            payload.feedback_type.upper(),
            payload.reason.upper() if payload.reason else None,
        ),
    )


@router.delete(
    "/recommendations/{recommendation_id}/looks/{look_id}/feedback",
    response_model=LookInteractionState,
)
def remove_look_feedback(
    recommendation_id: UUID,
    look_id: LookId,
    user: CurrentUser,
    db: Database,
    _: CsrfCheck,
) -> dict[str, Any]:
    return _mutate(
        db,
        lambda: delete_feedback(
            db,
            user["id"],
            recommendation_id,
            look_id,
        ),
    )


@router.put(
    "/recommendations/{recommendation_id}/looks/{look_id}/saved",
    response_model=LookInteractionState,
)
def save_recommended_look(
    recommendation_id: UUID,
    look_id: LookId,
    user: CurrentUser,
    db: Database,
    _: CsrfCheck,
) -> dict[str, Any]:
    return _mutate(
        db,
        lambda: save_look(
            db,
            user["id"],
            recommendation_id,
            look_id,
        ),
    )


@router.delete(
    "/recommendations/{recommendation_id}/looks/{look_id}/saved",
    response_model=LookInteractionState,
)
def remove_saved_look(
    recommendation_id: UUID,
    look_id: LookId,
    user: CurrentUser,
    db: Database,
    _: CsrfCheck,
) -> dict[str, Any]:
    return _mutate(
        db,
        lambda: delete_saved_look(
            db,
            user["id"],
            recommendation_id,
            look_id,
        ),
    )


@router.get("/saved-outfits", response_model=list[SavedOutfitResponse])
def read_saved_outfits(user: CurrentUser, db: Database) -> list[dict[str, Any]]:
    try:
        return list_saved_outfits(db, user["id"])
    except SQLAlchemyError as exc:
        _raise_interaction_error(db, exc)
        raise AssertionError("unreachable") from exc
