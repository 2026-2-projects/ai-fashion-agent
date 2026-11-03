"""Inference, Router, Tool 실행, 고정 JSON 검증을 연결하는 Agent Core."""

from app.agent.contracts import (
    AgentRecommendationRequest,
    AgentRecommendationResponse,
    FashionLook,
    normalize_wardrobe_slot,
)
from app.agent.inference import InferenceEngine
from app.agent.tool_registry import AgentRoutingError, ToolRegistry, ToolRuntime


class AgentResultError(Exception):
    """모델 결과가 실제 Tool 데이터와 맞지 않는 경우."""


class AgentService:
    def __init__(self, inference: InferenceEngine, tools: ToolRegistry):
        self._inference = inference
        self._tools = tools

    def recommend(
        self,
        request: AgentRecommendationRequest,
        runtime: ToolRuntime,
    ) -> AgentRecommendationResponse:
        plan = self._inference.plan(request)
        names = {call.name for call in plan.calls}
        if not {"get_user_context", "get_wardrobe"}.issubset(names):
            raise AgentRoutingError("5 LOOK 추천에는 사용자 Context와 옷장 조회가 필요합니다.")
        tool_results = self._tools.execute(plan, runtime)
        draft = self._inference.generate(request, tool_results)
        looks = self._validate_wardrobe_looks(draft.looks, tool_results["get_wardrobe"])
        return AgentRecommendationResponse(
            called_tools=list(tool_results),
            context_summary=draft.context_summary,
            looks=looks,
        )

    @staticmethod
    def _validate_wardrobe_looks(looks: list[FashionLook], wardrobe: object) -> list[FashionLook]:
        """모델의 옷장 ID를 검증한 후 Backend가 사진 URL을 응답에 연결한다."""
        if not isinstance(wardrobe, list):
            raise AgentResultError("옷장 Tool 결과가 올바르지 않습니다.")
        by_id = {
            item["item_id"]: item
            for item in wardrobe
            if isinstance(item, dict)
            and isinstance(item.get("item_id"), int)
            and not isinstance(item["item_id"], bool)
        }
        combinations: set[frozenset[tuple[str, int]]] = set()
        enriched_looks = list(looks[:3])
        for look in looks[3:]:
            if look.status == "unavailable":
                enriched_looks.append(look)
                continue
            combination: set[tuple[str, int]] = set()
            enriched_items = []
            for piece in look.items:
                source = by_id.get(piece.item_id)
                if source is None or normalize_wardrobe_slot(source.get("category")) != piece.slot:
                    raise AgentResultError("옷장 LOOK에 등록되지 않은 항목이 포함되었습니다.")
                if piece.image_url is not None:
                    raise AgentResultError("모델이 옷장 사진 URL을 직접 제공할 수 없습니다.")
                image = source.get("image")
                if image is not None and (not isinstance(image, str) or not image.strip()):
                    raise AgentResultError("옷장 Tool의 사진 주소가 올바르지 않습니다.")
                enriched_items.append(piece.model_copy(update={"image_url": image}))
                combination.add((piece.slot, piece.item_id))
            frozen_combination = frozenset(combination)
            if frozen_combination in combinations:
                raise AgentResultError("옷장 LOOK 4와 5는 다른 조합이어야 합니다.")
            combinations.add(frozen_combination)
            enriched_looks.append(look.model_copy(update={"items": enriched_items}))
        return enriched_looks
