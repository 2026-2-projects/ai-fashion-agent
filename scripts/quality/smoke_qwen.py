"""배포 전 합성 요청 7건을 Qwen 서버와 실제 AgentService로 검사한다.

백엔드 가상환경을 활성화한 뒤 셸에서 AGENT_INFERENCE_PROVIDER=qwen,
QWEN_BASE_URL, QWEN_MODEL 및 필요한 QWEN_API_KEY를 설정한다.
저장소 루트에서 PYTHONPATH=backend python scripts/quality/smoke_qwen.py 로 실행한다.
"""

import sys
from dataclasses import dataclass
from time import perf_counter

from pydantic import BaseModel
from sqlalchemy.orm import Session

# isort: split

from app.agent.contracts import AgentRecommendationRequest
from app.agent.errors import (
    InferenceConfigurationError,
    InferenceInputError,
    InferenceResponseError,
    InferenceTimeoutError,
    InferenceUnavailableError,
)
from app.agent.qwen import QwenInferenceEngine
from app.agent.service import AgentResultError, AgentService
from app.agent.settings import load_qwen_settings
from app.agent.tool_registry import (
    CalendarArguments,
    NoArguments,
    ToolDefinition,
    ToolRegistry,
    ToolRuntime,
    WeatherArguments,
)


def wardrobe_item(item_id: int, category: str, shape: str, color: str) -> dict:
    return {
        "item_id": item_id,
        "category": category,
        "type": shape,
        "color": color,
        "fit": "regular",
        "season": ["겨울"],
    }


WARDROBE = [
    wardrobe_item(771, "상의", "니트", "아이보리"),
    wardrobe_item(772, "상의", "셔츠", "하늘색"),
    wardrobe_item(773, "하의", "슬랙스", "네이비"),
    wardrobe_item(774, "신발", "로퍼", "검정"),
]
PRESENTATION = AgentRecommendationRequest(
    message="날씨와 일정에 맞춰 발표회에 입을 차분한 코디를 추천해줘. 빨강은 피하고 싶어.",
    place="전주",
    date="2026-11-26",
    time="15:00",
)
WARDROBE_ONLY = AgentRecommendationRequest(message="내 옷만 써서 입을 수 있는 코디를 추천해줘.")
COLOR_WARDROBE = [
    {**WARDROBE[0], "color": "네이비"},
    {**WARDROBE[1], "color": "빨강"},
    {**WARDROBE[2], "color": "차콜"},
    WARDROBE[3],
]


@dataclass(frozen=True)
class Scenario:
    name: str
    request: AgentRecommendationRequest
    wardrobe: list[dict]
    expected: list[str]
    disliked: str | None = None
    expected_top: int | None = None


ONE_OWNED = ["unavailable"] * 3 + ["available", "unavailable"]
CASES = (
    Scenario("normal", PRESENTATION, WARDROBE, ["available"] * 5),
    Scenario("empty-only", WARDROBE_ONLY, [], ["unavailable"] * 5),
    Scenario("only-stocked", WARDROBE_ONLY, WARDROBE, ["unavailable"] * 3 + ["available"] * 2),
    Scenario(
        "one-combination",
        PRESENTATION,
        [WARDROBE[0], *WARDROBE[2:]],
        ["available"] * 4 + ["unavailable"],
    ),
    Scenario("missing-shoes", PRESENTATION, WARDROBE[:3], ["available"] * 3 + ["unavailable"] * 2),
    Scenario("avoid-red", WARDROBE_ONLY, COLOR_WARDROBE, ONE_OWNED, "빨강", 771),
    Scenario("avoid-navy", WARDROBE_ONLY, COLOR_WARDROBE, ONE_OWNED, "네이비", 772),
)


def fixed_tool(model: type[BaseModel], result: object) -> ToolDefinition:
    return ToolDefinition(model, lambda _runtime, _args: result)


def synthetic_tools(wardrobe: list[dict], disliked: str | None) -> ToolRegistry:
    context = {
        "profile": {"gender": "male", "age_group": "20s"},
        "preference": {
            "preferred_styles": ["미니멀"],
            "preferred_colors": ["아이보리" if disliked else "네이비"],
            "disliked_colors": [disliked or "빨강"],
            "preferred_fit": "regular",
        },
        "feedback_summary": {"positive_styles": ["클래식"], "negative_styles": ["스트리트"]},
    }
    weather = {
        "temperature_c": 5,
        "precipitation_probability": 80,
        "precipitation_type": "비",
        "wind_mps": 4,
        "sky": "흐림",
    }
    events = [
        {
            "title": "실내 발표회",
            "start": "2026-11-26T15:00:00+09:00",
            "end": "2026-11-26T16:00:00+09:00",
            "all_day": False,
            "location": "전주",
        }
    ]
    return ToolRegistry(
        {
            "get_user_context": fixed_tool(NoArguments, context),
            "get_wardrobe": fixed_tool(NoArguments, wardrobe),
            "get_weather": fixed_tool(WeatherArguments, weather),
            "get_calendar_events": fixed_tool(CalendarArguments, events),
        }
    )


def main() -> int:
    try:
        settings = load_qwen_settings()
    except InferenceConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if settings is None:
        print("실모델 검사에는 AGENT_INFERENCE_PROVIDER=qwen 설정이 필요합니다.", file=sys.stderr)
        return 2

    engine = QwenInferenceEngine(settings)
    passed = 0
    with Session() as db:  # DB 엔진과 연결하지 않은 세션. 모든 Tool은 합성 값을 반환한다.
        runtime = ToolRuntime(db=db, user_id=1)
        for case in CASES:
            start = perf_counter()
            try:
                service = AgentService(engine, synthetic_tools(case.wardrobe, case.disliked))
                result = service.recommend(case.request, runtime)
            except (
                AgentResultError,
                InferenceConfigurationError,
                InferenceInputError,
                InferenceResponseError,
                InferenceTimeoutError,
                InferenceUnavailableError,
            ) as exc:
                print(
                    f"[실패] {case.name} ({perf_counter() - start:.1f}초) {type(exc).__name__}",
                    flush=True,
                )
                continue
            statuses = [look.status for look in result.looks]
            owned_tops = [item.item_id for item in result.looks[3].items if item.slot == "top"]
            matched = statuses == case.expected
            if case.expected_top is not None:
                matched = matched and owned_tops == [case.expected_top]
                print(f"  {case.disliked} 비선호, 기대 상의 {case.expected_top}, 실제 {owned_tops}")
            passed += int(matched)
            label = "통과" if matched else "실패"
            elapsed = perf_counter() - start
            print(f"[{label}] {case.name} ({elapsed:.1f}초), Tool {result.called_tools}")
            print(f"  기대 {case.expected} / 실제 {statuses}")
            for look in result.looks:
                items = [(item.name, item.item_id) for item in look.items]
                print(f"  LOOK {look.look_id} {look.style!r}, {items!r}, 근거 {look.reason!r}")
            sys.stdout.flush()

    print(f"자동 검사 {passed}/{len(CASES)}건 통과")
    print("이유와 아이템에서 비·5도·실내 발표회·빨강 비선호·선호 스타일 반영을 검토하세요.")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
