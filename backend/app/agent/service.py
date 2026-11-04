"""Inference, Router, Tool 실행, 고정 JSON 검증을 연결하는 Agent Core."""

from app.agent.contracts import (
    AgentRecommendationRequest,
    AgentRecommendationResponse,
    FashionLook,
)
from app.agent.inference import InferenceEngine
from app.agent.tool_registry import AgentRoutingError, ToolRegistry, ToolRuntime
from app.agent.validators import (
    AgentResultError as AgentResultError,
)
from app.agent.validators import (
    validate_agent_json,
    validate_wardrobe_looks,
)


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
        draft = validate_agent_json(self._inference.generate(request, tool_results))
        looks = self._validate_wardrobe_looks(draft.looks, tool_results["get_wardrobe"])
        result = AgentRecommendationResponse(
            called_tools=list(tool_results),
            context_summary=draft.context_summary,
            looks=looks,
        )
        result._look_features = draft._look_features
        return result

    @staticmethod
    def _validate_wardrobe_looks(looks: list[FashionLook], wardrobe: object) -> list[FashionLook]:
        return validate_wardrobe_looks(looks, wardrobe)
