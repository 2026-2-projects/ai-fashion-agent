"""Authenticated, scoped deletion of user-held fashion data (WBS 5.5).

Account deletion is handled separately by /auth/account. This endpoint never deletes users
or OAuth connection tokens. It requires both a valid cookie/CSRF pair and a fresh password.
"""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user, password_hash, require_csrf
from app.core.database import get_db
from app.services.recommendation_interactions import rebuild_feedback_summary
from app.services.wardrobe_images import remove_image

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/account/data", tags=["Account Data"])
CurrentUser = Annotated[dict, Depends(get_current_user)]
Database = Annotated[Session, Depends(get_db)]
CsrfCheck = Annotated[None, Depends(require_csrf)]
DataScope = Literal["profile", "preferences", "wardrobe", "feedback", "saved", "history"]

# This is a fixed allowlist: no client-provided SQL identifiers are executed.
COUNT_TABLES = {
    "profile": "user_profiles",
    "preferences": "user_preferences",
    "wardrobe": "wardrobe_items",
    "feedback": "feedback",
    "saved": "saved_outfits",
    "recommendations": "recommendation_runs",
}


class DataSummary(BaseModel):
    profile: int
    preferences: int
    wardrobe: int
    feedback: int
    saved: int
    recommendations: int


class DataDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: DataScope
    password: str = Field(min_length=1, max_length=128)


class DataDeleteResponse(BaseModel):
    scope: DataScope
    removed_records: int
    image_cleanup_failed: int = 0
    summary: DataSummary


def _count(db: Session, user_id: int) -> DataSummary:
    values = {}
    for kind, table in COUNT_TABLES.items():
        # `table` only originates from the server-owned constant COUNT_TABLES.
        values[kind] = db.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).scalar_one()
    return DataSummary(**values)


def _delete_rows(db: Session, table: str, user_id: int) -> int:
    if table not in COUNT_TABLES.values():
        raise ValueError("Unsupported deletion table")
    result = db.execute(
        text(f"DELETE FROM {table} WHERE user_id = :user_id"),
        {"user_id": user_id},
    )
    return max(0, result.rowcount or 0)


@router.get("/summary", response_model=DataSummary)
def read_my_data_summary(user: CurrentUser, db: Database) -> DataSummary:
    return _count(db, user["id"])


@router.delete("", response_model=DataDeleteResponse)
def delete_my_data(
    payload: DataDeleteRequest,
    user: CurrentUser,
    db: Database,
    _: CsrfCheck,
) -> DataDeleteResponse:
    user_id = user["id"]
    image_keys: list[str] = []
    try:
        # Serialize destructive operations with the account row; a stale cookie
        # and another user's user_id can never choose the deletion target.
        digest = db.execute(
            text("SELECT password_hash FROM users WHERE id = :user_id FOR UPDATE"),
            {"user_id": user_id},
        ).scalar_one_or_none()
        if not isinstance(digest, str):
            raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
        if not password_hash.verify(payload.password, digest):
            raise HTTPException(status_code=403, detail="현재 계정의 비밀번호가 올바르지 않습니다.")

        scope = payload.scope
        removed = 0
        if scope == "wardrobe":
            rows = db.execute(
                text("SELECT image_url FROM wardrobe_items WHERE user_id = :user_id"),
                {"user_id": user_id},
            ).all()
            image_keys = [row[0] for row in rows if isinstance(row[0], str)]
            removed = _delete_rows(db, "wardrobe_items", user_id)
        elif scope == "history":
            # FK children must be deleted before recommendation_runs.  Legacy
            # feedback/saved entries (without recommendation_id) are included.
            removed += _delete_rows(db, "feedback", user_id)
            removed += _delete_rows(db, "saved_outfits", user_id)
            removed += _delete_rows(db, "recommendation_runs", user_id)
            rebuild_feedback_summary(db, user_id)
        else:
            removed = _delete_rows(db, COUNT_TABLES[scope], user_id)
            if scope in ("feedback", "saved"):
                # Recompute personalization to avoid a stale feedback_summary.
                rebuild_feedback_summary(db, user_id)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Data deletion failed for user_id=%s scope=%s", user_id, payload.scope)
        raise HTTPException(status_code=500, detail="데이터 삭제 중 오류가 발생했습니다.") from exc
    except Exception:
        db.rollback()
        raise

    # Filesystem changes are made only after the DB transaction commits. If a
    # file cannot be removed, surface the discrepancy rather than report success.
    failed = 0
    for key in image_keys:
        try:
            remove_image(key, user_id)
        except OSError:
            failed += 1
            logger.exception("Image cleanup failed for user_id=%s", user_id)

    try:
        summary = _count(db, user_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="삭제는 처리됐지만 결과 조회에 실패했습니다. 새로고침해 확인해 주세요.") from exc
    return DataDeleteResponse(
        scope=payload.scope,
        removed_records=removed,
        image_cleanup_failed=failed,
        summary=summary,
    )
