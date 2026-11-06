from typing import cast

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agent.contracts import (
    AgentDraft,
    AgentPlan,
    AgentRecommendationRequest,
    FashionLook,
    OutfitItem,
    ToolCall,
)
from app.agent.inference import MockInferenceEngine
from app.agent.service import AgentResultError, AgentService
from app.agent.tool_registry import (
    AgentRoutingError,
    NoArguments,
    ToolArgumentError,
    ToolDefinition,
    ToolRegistry,
    ToolRuntime,
    WeatherArguments,
    default_tool_registry,
)


def test_mock_router_calls_only_requested_tools():
    request = AgentRecommendationRequest(
        message="내 옷으로 비 오는 날 출근 코디를 추천해줘",
        place="서울역",
        date="2026-11-04",
        time="08:30",
    )

    plan = MockInferenceEngine().plan(request)

    assert [call.name for call in plan.calls] == [
        "get_user_context",
        "get_wardrobe",
        "get_weather",
    ]
    validated = default_tool_registry().validate_plan(plan)
    assert validated[-1].arguments.model_dump() == {
        "date": "2026-11-04",
        "place": "서울역",
        "time": "08:30",
    }


def test_five_look_request_always_fetches_wardrobe_even_without_keyword():
    plan = MockInferenceEngine().plan(AgentRecommendationRequest(message="출근 코디 추천해줘"))
    assert [call.name for call in plan.calls] == ["get_user_context", "get_wardrobe"]


def test_mock_router_respects_explicit_weather_no_call_request():
    request = AgentRecommendationRequest(
        message="지금 31도야. 날씨 다시 조회하지 말고 내 옷으로 여름 코디 추천해줘"
    )

    plan = MockInferenceEngine().plan(request)

    assert [call.name for call in plan.calls] == ["get_user_context", "get_wardrobe"]


def test_router_validates_all_arguments_before_any_tool_runs():
    executed: list[str] = []

    def handler(runtime, arguments):
        del runtime, arguments
        executed.append("called")
        return {}

    registry = ToolRegistry(
        {
            "get_user_context": ToolDefinition(NoArguments, handler),
            "get_wardrobe": ToolDefinition(NoArguments, handler),
            "get_weather": ToolDefinition(WeatherArguments, handler),
        }
    )
    request = AgentRecommendationRequest(
        message="내일 날씨에 맞춰 추천해줘",
        date="2026-11-04",
        time="08:30",
    )
    plan = MockInferenceEngine().plan(request)

    with pytest.raises(ToolArgumentError, match="get_weather"):
        registry.execute(plan, ToolRuntime(db=cast(Session, object()), user_id=1))
    assert executed == []


@pytest.mark.parametrize(
    "plan, message",
    [
        (AgentPlan(calls=[ToolCall(name="delete_calendar")]), "허용되지 않은 Tool"),
        (
            AgentPlan(calls=[ToolCall(name="get_user_context"), ToolCall(name="get_user_context")]),
            "중복 Tool",
        ),
    ],
)
def test_router_rejects_unknown_or_duplicate_tools(plan, message):
    with pytest.raises(AgentRoutingError, match=message):
        default_tool_registry().validate_plan(plan)


def test_default_registry_connects_all_four_real_tool_adapters(monkeypatch):
    import app.agent.tool_registry as registry_module

    calls: list[tuple] = []
    fake_db = cast(Session, object())
    monkeypatch.setattr(
        registry_module,
        "get_user_context",
        lambda db, user_id: calls.append(("context", db, user_id)) or {"profile": {}},
    )
    monkeypatch.setattr(
        registry_module,
        "get_wardrobe",
        lambda db, user_id: calls.append(("wardrobe", db, user_id)) or [],
    )
    monkeypatch.setattr(
        registry_module,
        "get_weather",
        lambda place, date, time: calls.append(("weather", place, date, time)) or {},
    )
    monkeypatch.setattr(
        registry_module,
        "get_calendar_events",
        lambda db, user_id, date: calls.append(("calendar", db, user_id, date)) or [],
    )
    plan = AgentPlan(
        calls=[
            ToolCall(name="get_user_context"),
            ToolCall(name="get_wardrobe"),
            ToolCall(
                name="get_weather",
                arguments={"place": "서울역", "date": "2026-11-04", "time": "08:30"},
            ),
            ToolCall(name="get_calendar_events", arguments={"date": "2026-11-04"}),
        ]
    )

    result = default_tool_registry().execute(plan, ToolRuntime(db=fake_db, user_id=7))

    assert list(result) == [
        "get_user_context",
        "get_wardrobe",
        "get_weather",
        "get_calendar_events",
    ]
    assert calls == [
        ("context", fake_db, 7),
        ("wardrobe", fake_db, 7),
        ("weather", "서울역", "2026-11-04", "08:30"),
        ("calendar", fake_db, 7, "2026-11-04"),
    ]


def test_agent_service_returns_five_looks_and_marks_missing_second_wardrobe_look():
    context = {
        "profile": {},
        "preference": {
            "preferred_styles": ["minimal"],
            "preferred_colors": ["navy"],
            "disliked_colors": [],
            "preferred_fit": "regular",
        },
    }
    wardrobe = [
        {
            "item_id": 11,
            "category": "top",
            "type": "shirt",
            "color": "white",
            "fit": "regular",
            "image": "/api/v1/wardrobe/11/image",
        },
        {
            "item_id": 12,
            "category": "bottom",
            "type": "slacks",
            "color": "black",
            "fit": "regular",
            "image": None,
        },
        {
            "item_id": 13,
            "category": "shoes",
            "type": "sneakers",
            "color": "white",
            "fit": "regular",
            "image": None,
        },
    ]
    registry = ToolRegistry(
        {
            "get_user_context": ToolDefinition(NoArguments, lambda runtime, args: context),
            "get_wardrobe": ToolDefinition(NoArguments, lambda runtime, args: wardrobe),
        }
    )
    service = AgentService(MockInferenceEngine(), registry)
    draft = MockInferenceEngine().generate(
        AgentRecommendationRequest(message="내 옷으로 코디 추천해줘"),
        {"get_user_context": context, "get_wardrobe": wardrobe},
    )
    assert all(item.image_url is None for look in draft.looks for item in look.items)

    result = service.recommend(
        AgentRecommendationRequest(message="내 옷으로 코디 추천해줘"),
        ToolRuntime(db=cast(Session, object()), user_id=7),
    )

    assert result.called_tools == ["get_user_context", "get_wardrobe"]
    assert result.action == "generate_five_looks"
    assert [(look.look_id, look.role) for look in result.looks] == [
        (1, "preference_best"),
        (2, "preference_alternative"),
        (3, "exploration"),
        (4, "wardrobe_best"),
        (5, "wardrobe_alternative"),
    ]
    assert all(item.item_id is None for look in result.looks[:3] for item in look.items)
    assert {item.item_id for item in result.looks[3].items} == {11, 12, 13}
    assert result.looks[3].items[0].image_url == "/api/v1/wardrobe/11/image"
    assert all(item.image_url is None for item in result.looks[3].items[1:])
    assert result.looks[4].status == "unavailable"
    assert result.looks[4].style is None
    assert result.looks[4].items == []


def test_mock_prioritizes_positive_feedback_and_excludes_negative_style_candidates():
    context = {
        "preference": {
            "preferred_styles": ["minimal", "casual"],
            "preferred_colors": ["navy"],
            "disliked_colors": [],
            "preferred_fit": "regular",
        },
        "feedback_summary": {
            "positive_styles": ["고프코어", "미니멀 데일리"],
            "negative_styles": ["minimal"],
            "style_scores": [
                {"style": "고프코어", "score": 3},
                {"style": "미니멀 데일리", "score": 1},
                {"style": "minimal", "score": -1},
            ],
        },
    }
    preferences = MockInferenceEngine._preferences(context)

    draft = MockInferenceEngine().generate(
        AgentRecommendationRequest(message="코디 추천해줘"),
        {"get_user_context": context, "get_wardrobe": []},
    )

    assert preferences["preferred_styles"] == ["고프코어", "미니멀 데일리", "casual"]
    assert [look.style for look in draft.looks[:2]] == ["고프코어", "미니멀 데일리"]
    assert all(look.style != "minimal" for look in draft.looks if look.style is not None)


def test_mock_keeps_existing_style_behavior_without_feedback_summary():
    context = {
        "preference": {
            "preferred_styles": ["minimal", "casual"],
            "preferred_colors": [],
            "disliked_colors": [],
            "preferred_fit": "regular",
        }
    }

    draft = MockInferenceEngine().generate(
        AgentRecommendationRequest(message="코디 추천해줘"),
        {"get_user_context": context, "get_wardrobe": []},
    )

    assert [look.style for look in draft.looks[:2]] == [
        "minimal 데일리",
        "casual 레이어드",
    ]


def test_mock_excludes_negative_style_after_final_concept_is_built():
    context = {
        "preference": {
            "preferred_styles": ["미니멀", "캐주얼"],
            "preferred_colors": [],
            "disliked_colors": [],
            "preferred_fit": "regular",
        },
        "feedback_summary": {
            "positive_styles": [],
            "negative_styles": ["미니멀 데일리"],
            "style_scores": [{"style": "미니멀 데일리", "score": -1}],
        },
    }

    draft = MockInferenceEngine().generate(
        AgentRecommendationRequest(message="코디 추천해줘"),
        {"get_user_context": context, "get_wardrobe": []},
    )

    assert draft.looks[0].style == "캐주얼 레이어드"
    assert "미니멀 데일리" not in [look.style for look in draft.looks]


def test_mock_excludes_negative_exact_style_from_available_wardrobe_looks():
    wardrobe = [
        {"item_id": 11, "category": "top", "type": "shirt", "color": "white"},
        {"item_id": 12, "category": "top", "type": "knit", "color": "navy"},
        {"item_id": 13, "category": "bottom", "type": "slacks", "color": "black"},
        {"item_id": 14, "category": "shoes", "type": "sneakers", "color": "white"},
    ]
    context = {
        "preference": {},
        "feedback_summary": {
            "positive_styles": [],
            "negative_styles": ["보유 의류 기본 조합"],
            "style_scores": [{"style": "보유 의류 기본 조합", "score": -1}],
        },
    }

    draft = MockInferenceEngine().generate(
        AgentRecommendationRequest(message="내 옷으로 코디 추천해줘"),
        {"get_user_context": context, "get_wardrobe": wardrobe},
    )

    assert [look.status for look in draft.looks[3:]] == ["available", "available"]
    assert [look.style for look in draft.looks[3:]] == [
        "보유 의류 추천 조합",
        "보유 의류 대안 조합",
    ]
    assert "보유 의류 기본 조합" not in [look.style for look in draft.looks[3:]]


def test_mock_returns_two_distinct_owned_looks_and_respects_wardrobe_only_request():
    wardrobe = [
        {"item_id": 11, "category": "top", "type": "shirt", "color": "white"},
        {"item_id": 12, "category": "top", "type": "knit", "color": "navy"},
        {"item_id": 13, "category": "bottom", "type": "slacks", "color": "black"},
        {"item_id": 14, "category": "shoes", "type": "sneakers", "color": "white"},
    ]
    request = AgentRecommendationRequest(message="내 옷만으로 코디 추천해줘")
    draft = MockInferenceEngine().generate(
        request,
        {"get_user_context": {"preference": {}}, "get_wardrobe": wardrobe},
    )

    assert len(draft.looks) == 5
    assert all(look.status == "unavailable" for look in draft.looks[:3])
    assert all(look.style is None and look.items == [] for look in draft.looks[:3])
    assert [look.status for look in draft.looks[3:]] == ["available", "available"]
    assert draft.looks[3].items[0].item_id != draft.looks[4].items[0].item_id
    AgentService._validate_wardrobe_looks(draft.looks, wardrobe)


def test_mock_keeps_five_slots_when_wardrobe_is_empty():
    draft = MockInferenceEngine().generate(
        AgentRecommendationRequest(message="코디 추천해줘"),
        {"get_user_context": {"preference": {}}, "get_wardrobe": []},
    )

    assert [look.status for look in draft.looks] == [
        "available",
        "available",
        "available",
        "unavailable",
        "unavailable",
    ]


def test_owned_look_rejects_unknown_item_id():
    wardrobe = [
        {"item_id": 11, "category": "top", "type": "shirt", "color": "white"},
        {"item_id": 12, "category": "bottom", "type": "slacks", "color": "black"},
        {"item_id": 13, "category": "shoes", "type": "sneakers", "color": "white"},
    ]
    draft = MockInferenceEngine().generate(
        AgentRecommendationRequest(message="코디 추천해줘"),
        {"get_user_context": {"preference": {}}, "get_wardrobe": wardrobe},
    )
    draft.looks[3].items[0].item_id = 999

    with pytest.raises(AgentResultError, match="등록되지 않은"):
        AgentService._validate_wardrobe_looks(draft.looks, wardrobe)


def test_owned_look_rejects_model_supplied_image_url():
    wardrobe = [
        {"item_id": 11, "category": "top", "type": "shirt", "color": "white", "image": None},
        {"item_id": 12, "category": "bottom", "type": "slacks", "color": "black"},
        {"item_id": 13, "category": "shoes", "type": "sneakers", "color": "white"},
    ]
    draft = MockInferenceEngine().generate(
        AgentRecommendationRequest(message="코디 추천해줘"),
        {"get_user_context": {"preference": {}}, "get_wardrobe": wardrobe},
    )
    draft.looks[3].items[0].image_url = "https://example.com/unverified.png"

    with pytest.raises(AgentResultError, match="직접 제공"):
        AgentService._validate_wardrobe_looks(draft.looks, wardrobe)


def test_owned_looks_reject_duplicate_combination_in_different_item_order():
    wardrobe = [
        {"item_id": 11, "category": "top", "type": "shirt", "color": "white"},
        {"item_id": 12, "category": "top", "type": "knit", "color": "navy"},
        {"item_id": 13, "category": "bottom", "type": "slacks", "color": "black"},
        {"item_id": 14, "category": "shoes", "type": "sneakers", "color": "white"},
    ]
    draft = MockInferenceEngine().generate(
        AgentRecommendationRequest(message="코디 추천해줘"),
        {"get_user_context": {"preference": {}}, "get_wardrobe": wardrobe},
    )
    draft.looks[4].items = list(reversed(draft.looks[3].items))

    with pytest.raises(AgentResultError, match="다른 조합"):
        AgentService._validate_wardrobe_looks(draft.looks, wardrobe)


def test_fixed_look_contract_rejects_wrong_role_order():
    looks = [
        FashionLook(
            look_id=index,
            role="preference_best",
            status="unavailable",
            style=None,
            items=[],
            reason="reason",
        )
        for index in (1, 2, 3, 4, 5)
    ]

    with pytest.raises(ValidationError, match="고정 순서"):
        AgentDraft(context_summary="summary", looks=looks)


def test_fixed_look_contract_requires_first_wardrobe_look_before_second():
    def unavailable(index, role):
        return FashionLook(
            look_id=index,
            role=role,
            status="unavailable",
            style=None,
            items=[],
            reason="등록된 의류가 부족합니다.",
        )

    looks = [
        unavailable(1, "preference_best"),
        unavailable(2, "preference_alternative"),
        unavailable(3, "exploration"),
        unavailable(4, "wardrobe_best"),
        FashionLook(
            look_id=5,
            role="wardrobe_alternative",
            status="available",
            style="캐주얼",
            items=[
                OutfitItem(slot=slot, name="의류", item_id=item_id)
                for slot, item_id in (("top", 11), ("bottom", 12), ("shoes", 13))
            ],
            reason="등록된 의류를 조합했습니다.",
        ),
    ]

    with pytest.raises(ValidationError, match="LOOK 4도"):
        AgentDraft(context_summary="summary", looks=looks)


def test_fixed_look_contract_rejects_incomplete_or_invented_wardrobe_items():
    with pytest.raises(ValidationError, match="상의·하의·신발"):
        FashionLook(
            look_id=4,
            role="wardrobe_best",
            status="available",
            style="캐주얼",
            items=[OutfitItem(slot="top", name="셔츠", item_id=11)],
            reason="reason",
        )

    with pytest.raises(ValidationError, match="실제 ID"):
        FashionLook(
            look_id=4,
            role="wardrobe_best",
            status="available",
            style="캐주얼",
            items=[
                OutfitItem(slot=slot, name="의류", item_id=None)
                for slot in ("top", "bottom", "shoes")
            ],
            reason="reason",
        )
