"""WBS 4.2: 현재 사용자 Wardrobe CRUD 및 선택적 이미지 업로드."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.tools.wardrobe import get_wardrobe
from app.api.v1.auth import get_current_user, require_csrf
from app.core.database import get_db
from app.services.wardrobe_images import image_path, remove_image, store_image, validate_image

router = APIRouter(prefix="/wardrobe", tags=["Wardrobe"])
CurrentUser = Annotated[dict, Depends(get_current_user)]
Database = Annotated[Session, Depends(get_db)]
CsrfCheck = Annotated[None, Depends(require_csrf)]

Name50 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Name100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Season = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class WardrobeCreate(BaseModel):
    category: Name50
    type: Name100
    color: Name50
    fit: Name50
    seasons: list[Season] = Field(default_factory=list, max_length=4)

    model_config = {"extra": "forbid"}

    @field_validator("seasons")
    @classmethod
    def unique_seasons(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("계절은 중복 입력할 수 없습니다.")
        return value


class WardrobeUpdate(BaseModel):
    category: Name50 | None = None
    type: Name100 | None = None
    color: Name50 | None = None
    fit: Name50 | None = None
    seasons: list[Season] | None = Field(default=None, max_length=4)

    model_config = {"extra": "forbid"}

    @field_validator("seasons")
    @classmethod
    def unique_seasons(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("계절은 중복 입력할 수 없습니다.")
        return value


class WardrobeResponse(BaseModel):
    item_id: int
    category: str
    type: str
    color: str
    fit: str
    seasons: list[str]
    image_url: str | None
    created_at: datetime
    updated_at: datetime


def _row_to_response(row: dict) -> WardrobeResponse:
    raw = row["image_url"]
    image_url = None
    if raw:
        # image_url DB 컬럼은 신규 업로드의 경우 로컬 저장키, 기존 데이터는 외부 URL 가능.
        image_url = f"/api/v1/wardrobe/{row['id']}/image" if raw.startswith("wardrobe/") else raw
    return WardrobeResponse(
        item_id=row["id"],
        category=row["category"],
        type=row["item_type"],
        color=row["color"],
        fit=row["fit"],
        seasons=row["seasons"] or [],
        image_url=image_url,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _owned_item(db: Session, user_id: int, item_id: int) -> dict:
    row = db.execute(
        text("SELECT * FROM wardrobe_items WHERE id = :id AND user_id = :user_id"),
        {"id": item_id, "user_id": user_id},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="옷장 항목을 찾을 수 없습니다.")
    return dict(row)


@router.post("", response_model=WardrobeResponse, status_code=201)
def create_wardrobe_item(payload: WardrobeCreate, user: CurrentUser, db: Database, _: CsrfCheck):
    row = db.execute(
        text("""
            INSERT INTO wardrobe_items (user_id, category, item_type, color, fit, seasons)
            VALUES (:user_id, :category, :item_type, :color, :fit, :seasons)
            RETURNING *
        """),
        {"user_id": user["id"], "category": payload.category, "item_type": payload.type,
         "color": payload.color, "fit": payload.fit, "seasons": payload.seasons},
    ).mappings().one()
    db.commit()
    return _row_to_response(row)


@router.get("", response_model=list[WardrobeResponse])
def list_wardrobe_items(user: CurrentUser, db: Database):
    rows = db.execute(
        text("SELECT * FROM wardrobe_items WHERE user_id = :user_id ORDER BY id DESC"),
        {"user_id": user["id"]},
    ).mappings().all()
    return [_row_to_response(r) for r in rows]


@router.get("/agent-context")
def wardrobe_agent_context(user: CurrentUser, db: Database) -> list[dict]:
    """Agent Tool 출력 스키마를 로컬 Swagger에서 확인하기 위한 엔드포인트."""
    return get_wardrobe(db, user["id"])


@router.get("/{item_id}", response_model=WardrobeResponse)
def get_wardrobe_item(item_id: int, user: CurrentUser, db: Database):
    return _row_to_response(_owned_item(db, user["id"], item_id))


@router.patch("/{item_id}", response_model=WardrobeResponse)
def update_wardrobe_item(
    item_id: int, payload: WardrobeUpdate, user: CurrentUser, db: Database, _: CsrfCheck
):
    _owned_item(db, user["id"], item_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="수정할 항목을 올바르게 입력해 주세요.")
    if "type" in changes:
        changes["item_type"] = changes.pop("type")
    # 컬럼은 고정된 Pydantic 모델 필드에서만 선택한다.
    assignments = ", ".join(f"{key} = :{key}" for key in changes)
    params = {"id": item_id, "user_id": user["id"], **changes}
    db.execute(
        text(f"""
            UPDATE wardrobe_items SET {assignments}, updated_at = CURRENT_TIMESTAMP
            WHERE id = :id AND user_id = :user_id
        """),
        params,
    )
    db.commit()
    return _row_to_response(_owned_item(db, user["id"], item_id))


@router.delete("/{item_id}", status_code=204)
def delete_wardrobe_item(item_id: int, user: CurrentUser, db: Database, _: CsrfCheck):
    row = _owned_item(db, user["id"], item_id)
    db.execute(
        text("DELETE FROM wardrobe_items WHERE id = :id AND user_id = :user_id"),
        {"id": item_id, "user_id": user["id"]},
    )
    db.commit()
    remove_image(row["image_url"], user["id"])
    return Response(status_code=204)


@router.post("/{item_id}/image", response_model=WardrobeResponse)
async def upload_wardrobe_image(
    item_id: int,
    user: CurrentUser,
    db: Database,
    _: CsrfCheck,
    file: Annotated[UploadFile, File()],
):
    old = _owned_item(db, user["id"], item_id)["image_url"]
    data, ext = await validate_image(file)
    new_key = store_image(data, ext, user["id"])
    try:
        db.execute(
            text("""
                UPDATE wardrobe_items
                SET image_url = :image_url, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id AND user_id = :user_id
            """),
            {"image_url": new_key, "id": item_id, "user_id": user["id"]},
        )
        db.commit()
    except Exception:
        db.rollback()
        remove_image(new_key, user["id"])
        raise
    if old != new_key:
        remove_image(old, user["id"])
    return _row_to_response(_owned_item(db, user["id"], item_id))


@router.get("/{item_id}/image")
def read_wardrobe_image(item_id: int, user: CurrentUser, db: Database):
    row = _owned_item(db, user["id"], item_id)
    key = row["image_url"]
    path = image_path(key, user["id"])
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="저장된 이미지를 찾을 수 없습니다.")
    content_types = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    return FileResponse(
        path,
        media_type=content_types[path.suffix],
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/{item_id}/image", status_code=204)
def delete_wardrobe_image(item_id: int, user: CurrentUser, db: Database, _: CsrfCheck):
    row = _owned_item(db, user["id"], item_id)
    db.execute(
        text("""
            UPDATE wardrobe_items SET image_url = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = :id AND user_id = :user_id
        """),
        {"id": item_id, "user_id": user["id"]},
    )
    db.commit()
    remove_image(row["image_url"], user["id"])
    return Response(status_code=204)
