"""Agent Core의 모델 비의존 입력·출력 계약."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ToolName = Literal[
    "get_user_context",
    "get_wardrobe",
    "get_weather",
    "get_calendar_events",
]
LookRole = Literal[
    "preference_best",
    "preference_alternative",
    "exploration",
    "wardrobe_best",
    "wardrobe_alternative",
]
ItemSlot = Literal["top", "bottom", "shoes", "outer", "accessory"]
WARDROBE_SLOTS: dict[str, ItemSlot] = {
    "top": "top",
    "상의": "top",
    "bottom": "bottom",
    "하의": "bottom",
    "shoes": "shoes",
    "신발": "shoes",
    "outer": "outer",
    "아우터": "outer",
    "accessory": "accessory",
    "액세서리": "accessory",
}


def normalize_wardrobe_slot(category: object) -> ItemSlot | None:
    return WARDROBE_SLOTS.get(str(category).strip().lower())


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class AgentRecommendationRequest(BaseModel):
    """자연어 요청과 Tool 인자에 필요한 구조화된 선택 입력."""

    model_config = ConfigDict(extra="forbid")

    message: NonEmptyText = Field(max_length=1000)
    place: NonEmptyText | None = Field(default=None, max_length=100)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")


class ToolCall(BaseModel):
    """Inference Engine이 Router에 전달하는 Tool 호출 계획."""

    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calls: list[ToolCall] = Field(default_factory=list, max_length=4)


class OutfitItem(BaseModel):
    """Gold Data의 슬롯·이름·소유 ID와 Backend 사진 URL."""

    model_config = ConfigDict(extra="forbid")

    slot: ItemSlot
    name: NonEmptyText
    item_id: int | None
    image_url: str | None = None


class FashionLook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    look_id: int = Field(ge=1, le=5)
    role: LookRole
    status: Literal["available", "unavailable"]
    style: NonEmptyText | None
    items: list[OutfitItem]
    reason: NonEmptyText

    @model_validator(mode="after")
    def validate_availability_and_source(self) -> "FashionLook":
        if self.status == "unavailable":
            if self.style is not None or self.items:
                raise ValueError("unavailable LOOK은 style=null, items=[]여야 합니다.")
            return self

        slots = [item.slot for item in self.items]
        if (
            self.style is None
            or len(slots) != len(set(slots))
            or not {"top", "bottom", "shoes"}.issubset(slots)
        ):
            raise ValueError("available LOOK은 상의·하의·신발을 각각 하나씩 포함해야 합니다.")
        for item in self.items:
            if self.look_id <= 3 and (item.item_id is not None or item.image_url is not None):
                raise ValueError("일반 LOOK 1~3에 실제 옷장 ID나 사진을 넣을 수 없습니다.")
            if self.look_id >= 4 and (item.item_id is None or item.item_id <= 0):
                raise ValueError("옷장 LOOK 4~5의 모든 아이템에는 실제 ID가 필요합니다.")
        return self


class AgentDraft(BaseModel):
    """Inference Engine이 생성하며, HTTP 메타데이터와 분리된 결과."""

    model_config = ConfigDict(extra="forbid")

    context_summary: NonEmptyText
    looks: list[FashionLook] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_fixed_look_roles(self) -> "AgentDraft":
        expected = [
            (1, "preference_best"),
            (2, "preference_alternative"),
            (3, "exploration"),
            (4, "wardrobe_best"),
            (5, "wardrobe_alternative"),
        ]
        actual = [(look.look_id, look.role) for look in self.looks]
        if actual != expected:
            raise ValueError("LOOK 1~5의 번호와 역할이 고정 순서와 일치해야 합니다.")
        if self.looks[4].status == "available" and self.looks[3].status != "available":
            raise ValueError("LOOK 5를 사용할 수 있으면 LOOK 4도 사용할 수 있어야 합니다.")
        return self


class AgentRecommendationResult(AgentDraft):
    """Agent가 생성하고 Backend 검증을 통과한 고정 5 LOOK 결과."""

    type: Literal["fashion_recommendation"] = "fashion_recommendation"
    action: Literal["generate_five_looks"] = "generate_five_looks"
    called_tools: list[ToolName]


class AgentRecommendationResponse(AgentRecommendationResult):
    """DB 저장까지 완료된 추천 API 성공 응답."""

    recommendation_id: UUID
