"""저장된 추천 LOOK에 화면용 이미지를 별도로 연결하는 읽기 API."""

from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.contracts import FashionLook, ItemSlot, OutfitItem
from app.api.v1.auth import get_current_user
from app.core.config import (
    SERPAPI_API_KEY,
    SERPAPI_IMAGE_SEARCH_ENABLED,
    SERPAPI_TIMEOUT_SECONDS,
)
from app.core.database import get_db
from app.services.recommendation_interactions import (
    RecommendationNotFoundError,
    StoredRecommendationError,
    load_owned_looks,
)
from app.services.shopping_images import ShoppingImageResult, ShoppingImageService

router = APIRouter(tags=["Recommendation Images"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
Database = Annotated[Session, Depends(get_db)]
LookId = Annotated[int, Path(ge=1, le=5)]
ItemImageStatus = Literal[
    "found",
    "not_found",
    "provider_unavailable",
    "provider_disabled",
]


class StrictResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResolvedImage(StrictResponseModel):
    url: str
    title: str
    source_name: str | None
    source_url: str | None
    provider: str
    rights_status: Literal["unverified", "user_provided"]


class ResolvedItemImage(StrictResponseModel):
    slot: ItemSlot
    name: str
    origin: Literal["google_shopping", "wardrobe"]
    status: ItemImageStatus
    image: ResolvedImage | None


class RecommendationLookImagesResponse(StrictResponseModel):
    recommendation_id: UUID
    look_id: int
    look_status: Literal["available", "unavailable"]
    resolution_status: Literal["complete", "partial", "not_applicable"]
    items: list[ResolvedItemImage]


_shopping_image_service = ShoppingImageService(
    api_key=SERPAPI_API_KEY,
    enabled=SERPAPI_IMAGE_SEARCH_ENABLED,
    timeout_seconds=SERPAPI_TIMEOUT_SECONDS,
)


def get_shopping_image_service() -> ShoppingImageService:
    """테스트와 향후 캐시 구현 교체를 위한 의존성 경계."""
    return _shopping_image_service


ShoppingImages = Annotated[ShoppingImageService, Depends(get_shopping_image_service)]


def _external_item(item: OutfitItem, result: ShoppingImageResult) -> ResolvedItemImage:
    image = None
    status: ItemImageStatus = result.status
    if result.status == "found" and result.url is not None:
        image = ResolvedImage(
            url=result.url,
            title=result.title or item.name,
            source_name=result.source_name,
            source_url=result.source_url,
            provider=result.provider,
            rights_status="unverified",
        )
    elif result.status == "found":
        status = "provider_unavailable"
    return ResolvedItemImage(
        slot=item.slot,
        name=item.name,
        origin="google_shopping",
        status=status,
        image=image,
    )


def _wardrobe_item(item: OutfitItem) -> ResolvedItemImage:
    image = None
    status: ItemImageStatus = "not_found"
    if item.image_url is not None:
        status = "found"
        image = ResolvedImage(
            url=item.image_url,
            title=item.name,
            source_name="사용자 옷장",
            source_url=None,
            provider="user_wardrobe",
            rights_status="user_provided",
        )
    return ResolvedItemImage(
        slot=item.slot,
        name=item.name,
        origin="wardrobe",
        status=status,
        image=image,
    )


def _resolution_status(items: list[ResolvedItemImage]) -> Literal["complete", "partial"]:
    return "complete" if all(item.status == "found" for item in items) else "partial"


def _find_look(looks: list[FashionLook], look_id: int) -> FashionLook:
    look = next((candidate for candidate in looks if candidate.look_id == look_id), None)
    if look is None:
        raise StoredRecommendationError
    return look


def _resolve_external_items(
    items: list[OutfitItem],
    service: ShoppingImageService,
) -> list[ResolvedItemImage]:
    """한 요청의 외부 호출을 3개로 제한하고 저장된 아이템 순서를 유지한다."""
    if not items:
        return []

    def resolve(item: OutfitItem) -> ResolvedItemImage:
        return _external_item(item, service.resolve(item.name, item.slot))

    with ThreadPoolExecutor(max_workers=min(3, len(items))) as executor:
        return list(executor.map(resolve, items))


@router.get(
    "/recommendations/{recommendation_id}/looks/{look_id}/images",
    response_model=RecommendationLookImagesResponse,
)
def read_recommendation_look_images(
    recommendation_id: UUID,
    look_id: LookId,
    user: CurrentUser,
    db: Database,
    service: ShoppingImages,
) -> RecommendationLookImagesResponse:
    try:
        look = _find_look(
            load_owned_looks(db, user["id"], recommendation_id),
            look_id,
        )
        # 이후에는 DB를 사용하지 않으므로 외부 호출 전에 연결을 반환한다.
        db.close()
    except RecommendationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="추천을 찾을 수 없습니다.") from exc
    except (StoredRecommendationError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=500,
            detail="저장된 추천 데이터를 읽는 중 오류가 발생했습니다.",
        ) from exc

    if look.status == "unavailable":
        return RecommendationLookImagesResponse(
            recommendation_id=recommendation_id,
            look_id=look.look_id,
            look_status=look.status,
            resolution_status="not_applicable",
            items=[],
        )

    if look.look_id <= 3:
        items = _resolve_external_items(look.items, service)
    else:
        items = [_wardrobe_item(item) for item in look.items]

    return RecommendationLookImagesResponse(
        recommendation_id=recommendation_id,
        look_id=look.look_id,
        look_status=look.status,
        resolution_status=_resolution_status(items),
        items=items,
    )
