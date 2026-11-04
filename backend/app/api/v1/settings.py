from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.personalization import PreferenceTag, sanitize_preferences
from app.api.v1.auth import get_current_user, require_csrf
from app.core.database import get_db

router = APIRouter(tags=["User Settings"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
Database = Annotated[Session, Depends(get_db)]
CsrfCheck = Annotated[None, Depends(require_csrf)]


class ProfileUpdate(BaseModel):
    gender: str | None = Field(default=None, max_length=30)
    age_group: str | None = Field(default=None, max_length=30)
    height_cm: int | None = Field(default=None, gt=0, le=300)
    body_type: str | None = Field(default=None, max_length=50)


class ProfileResponse(ProfileUpdate):
    user_id: int


class PreferencesUpdate(BaseModel):
    preferred_styles: list[PreferenceTag] = Field(default_factory=list)
    preferred_colors: list[PreferenceTag] = Field(default_factory=list)
    disliked_colors: list[PreferenceTag] = Field(default_factory=list)
    preferred_fit: str | None = Field(default=None, max_length=50)


class PreferencesResponse(PreferencesUpdate):
    user_id: int


ALLOWED_FIELDS = {
    "user_profiles": {"gender", "age_group", "height_cm", "body_type"},
    "user_preferences": {
        "preferred_styles",
        "preferred_colors",
        "disliked_colors",
        "preferred_fit",
    },
}


def read_settings(db: Session, table: str, user_id: int) -> dict:
    if table not in ALLOWED_FIELDS:
        raise ValueError("허용되지 않은 테이블")

    row = (
        db.execute(
            text(f"SELECT * FROM {table} WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        .mappings()
        .first()
    )

    settings = dict(row) if row else {"user_id": user_id}
    return sanitize_preferences(settings) if table == "user_preferences" else settings


def save_settings(
    db: Session,
    table: Literal["user_profiles", "user_preferences"],
    user_id: int,
    changes: dict,
) -> None:
    if not changes:
        raise HTTPException(422, "수정할 항목이 없습니다.")

    if not set(changes).issubset(ALLOWED_FIELDS[table]):
        raise ValueError("허용되지 않은 필드")

    columns = ["user_id", *changes.keys()]
    col_sql = ", ".join(columns)
    val_sql = ", ".join(f":{col}" for col in columns)

    update_sql = ", ".join(f"{col} = EXCLUDED.{col}" for col in changes)

    query = text(f"""
        INSERT INTO {table} ({col_sql})
        VALUES ({val_sql})
        ON CONFLICT (user_id)
        DO UPDATE SET
            {update_sql},
            updated_at = CURRENT_TIMESTAMP
    """)

    db.execute(query, {"user_id": user_id, **changes})
    db.commit()


@router.get("/profile/me", response_model=ProfileResponse)
def get_profile(user: CurrentUser, db: Database):
    return read_settings(db, "user_profiles", user["id"])


@router.patch("/profile/me", response_model=ProfileResponse)
def update_profile(
    payload: ProfileUpdate,
    user: CurrentUser,
    db: Database,
    _: CsrfCheck,
):
    save_settings(
        db,
        "user_profiles",
        user["id"],
        payload.model_dump(exclude_unset=True),
    )
    return read_settings(db, "user_profiles", user["id"])


@router.get(
    "/preferences/me",
    response_model=PreferencesResponse,
)
def get_preferences(user: CurrentUser, db: Database):
    return read_settings(db, "user_preferences", user["id"])


@router.patch(
    "/preferences/me",
    response_model=PreferencesResponse,
)
def update_preferences(
    payload: PreferencesUpdate,
    user: CurrentUser,
    db: Database,
    _: CsrfCheck,
):
    save_settings(
        db,
        "user_preferences",
        user["id"],
        payload.model_dump(exclude_unset=True),
    )
    return read_settings(db, "user_preferences", user["id"])
