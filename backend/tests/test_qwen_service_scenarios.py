"""Exercise the service's tool → FR prompt → validated result path with synthetic data."""

import json
from typing import cast

import httpx
import pytest
from sqlalchemy.orm import Session

from app.agent import tool_registry
from app.agent.contracts import AgentRecommendationRequest
from app.agent.errors import InferenceResponseError
from app.agent.qwen import QwenInferenceEngine
from app.agent.service import AgentResultError, AgentService
from app.agent.settings import QwenSettings
from app.agent.tool_registry import ToolRuntime, default_tool_registry

ROLES = (
    "preference_best",
    "preference_alternative",
    "exploration",
    "wardrobe_best",
    "wardrobe_alternative",
)
WARDROBE = [
    {"item_id": 71, "category": "상의", "type": "셔츠", "color": "navy", "season": ["fall"]},
    {"item_id": 72, "category": "하의", "type": "슬랙스", "color": "black", "season": ["fall"]},
    {"item_id": 73, "category": "신발", "type": "로퍼", "color": "black", "season": ["fall"]},
]
PREFERENCE = {
    "preferred_styles": ["minimal"],
    "preferred_fit": "regular",
    "preferred_colors": ["navy"],
    "disliked_colors": ["red"],
}
FEEDBACK = {"positive_styles": ["미니멀 출근룩"], "negative_styles": ["스포티"]}
WEATHER = {"temperature_c": 8, "precipitation_type": "비", "precipitation_probability": 80}
EVENT = {
    "title": "합성 발표 일정",
    "start": "2026-11-27T09:00:00+09:00",
    "end": "2026-11-27T10:00:00+09:00",
    "all_day": False,
    "location": "서울",
}


def _unavailable(look_id):
    return {
        "look_id": look_id,
        "role": ROLES[look_id - 1],
        "status": "unavailable",
        "style": None,
        "items": [],
        "reason": "이번 요청에 사용할 수 있는 조합이 없습니다.",
    }


def _available(look_id):
    return {
        "look_id": look_id,
        "role": ROLES[look_id - 1],
        "status": "available",
        "style": "미니멀 출근룩",
        "reason": "단정한 셔츠와 로퍼를 조합했습니다.",
        "items": [
            {
                "slot": slot,
                "name": piece["type"],
                "item_id": piece["item_id"] if look_id >= 4 else None,
            }
            for slot, piece in zip(("top", "bottom", "shoes"), WARDROBE, strict=True)
        ],
    }


def _recommend(monkeypatch, request, wardrobe, looks):
    monkeypatch.setattr(
        tool_registry,
        "get_user_context",
        lambda db, user_id: {"preference": PREFERENCE, "feedback_summary": FEEDBACK},
    )
    monkeypatch.setattr(tool_registry, "get_wardrobe", lambda db, user_id: wardrobe)
    monkeypatch.setattr(tool_registry, "get_weather", lambda place, date, time: WEATHER)
    monkeypatch.setattr(tool_registry, "get_calendar_events", lambda db, user_id, date: [EVENT])

    sent = []

    def complete(http_request):
        sent.append(json.loads(http_request.content)["messages"][1]["content"])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps({"looks": looks})},
                    }
                ]
            },
        )

    engine = QwenInferenceEngine(
        QwenSettings(base_url="http://127.0.0.1:8001/v1", model="synthetic-adapter"),
        transport=httpx.MockTransport(complete),
    )
    service = AgentService(engine, default_tool_registry())
    result = service.recommend(request, ToolRuntime(db=cast(Session, object()), user_id=17))
    [user_message] = sent
    return result, json.loads(user_message.rsplit("\ncontext: ", 1)[1])


def test_wardrobe_only_schedule_passes_preferences_weather_and_calendar_to_fr(monkeypatch):
    request = AgentRecommendationRequest(
        message="내 옷만 써서 날씨와 일정에 맞춰 추천해줘",
        place="서울",
        date="2026-11-27",
        time="09:00",
    )
    looks = [_unavailable(1), _unavailable(2), _unavailable(3), _available(4), _unavailable(5)]
    result, context = _recommend(monkeypatch, request, WARDROBE, looks)

    assert set(result.called_tools) == {
        "get_user_context",
        "get_wardrobe",
        "get_weather",
        "get_calendar_events",
    }
    assert context["preference"] == PREFERENCE
    assert context["feedback_summary"] == FEEDBACK
    assert context["weather"] == WEATHER
    assert context["calendar_events"] == [EVENT]
    assert context["wardrobe_only"] is True
    assert context["schedule"] == {"place": "서울", "date": "2026-11-27", "time": "09:00"}
    assert [item["category"] for item in context["wardrobe"]] == ["top", "bottom", "shoes"]
    assert context["wardrobe_examples"] == [{"top": 71, "bottom": 72, "shoes": 73}]
    assert "look4_candidate_items" not in context
    assert "wardrobe_guidance" not in context
    assert [look.status for look in result.looks] == [
        "unavailable",
        "unavailable",
        "unavailable",
        "available",
        "unavailable",
    ]
    assert [item.item_id for item in result.looks[3].items] == [71, 72, 73]


@pytest.mark.parametrize("wardrobe", [[], WARDROBE[:2]], ids=["empty", "missing-shoes"])
def test_incomplete_wardrobe_accepts_unavailable_and_rejects_invented_outfit(monkeypatch, wardrobe):
    request = AgentRecommendationRequest(message="출근 코디 추천해줘")
    looks = [_available(1), _available(2), _available(3), _unavailable(4), _unavailable(5)]
    result, context = _recommend(monkeypatch, request, wardrobe, looks)

    assert [item["item_id"] for item in context["wardrobe"]] == [
        item["item_id"] for item in wardrobe
    ]
    assert context["wardrobe_examples"] == []
    assert "wardrobe_guidance" not in context
    assert [look.status for look in result.looks[3:]] == ["unavailable", "unavailable"]
    looks[3] = _available(4)
    with pytest.raises(AgentResultError, match="등록되지 않은"):
        _recommend(monkeypatch, request, wardrobe, looks)


def test_completion_with_extra_copy_of_a_required_slot_is_rejected(monkeypatch):
    request = AgentRecommendationRequest(message="출근 코디 추천해줘")
    looks = [_available(1), _available(2), _available(3), _available(4), _unavailable(5)]
    looks[3]["items"].append(dict(looks[3]["items"][0]))

    with pytest.raises(InferenceResponseError):
        _recommend(monkeypatch, request, WARDROBE, looks)


def test_two_grounded_examples_skip_disliked_color(monkeypatch):
    request = AgentRecommendationRequest(message="출근 코디 추천해줘")
    red = {**WARDROBE[0], "item_id": 74, "color": " RED "}
    alternate = {**WARDROBE[0], "item_id": 75, "type": "니트", "color": "beige"}
    wardrobe = [red, *WARDROBE, alternate]
    looks = [_available(index) for index in range(1, 6)]
    looks[4]["items"][0] = {"slot": "top", "name": "니트", "item_id": 75}
    result, context = _recommend(monkeypatch, request, wardrobe, looks)

    assert 74 in {item["item_id"] for item in context["wardrobe"]}
    assert context["wardrobe_examples"] == [
        {"top": 71, "bottom": 72, "shoes": 73},
        {"top": 75, "bottom": 72, "shoes": 73},
    ]
    assert [look.status for look in result.looks[3:]] == ["available", "available"]


def test_optional_outer_provides_second_owned_combination(monkeypatch):
    request = AgentRecommendationRequest(message="내 옷만 써서 두 가지로 추천해줘")
    wardrobe = [*WARDROBE, {"item_id": 76, "category": "아우터", "type": "코트", "color": "navy"}]
    looks = [_unavailable(1), _unavailable(2), _unavailable(3), _available(4), _available(5)]
    looks[4]["items"].append({"slot": "outer", "name": "코트", "item_id": 76})
    result, context = _recommend(monkeypatch, request, wardrobe, looks)

    assert context["wardrobe_examples"] == [
        {"top": 71, "bottom": 72, "shoes": 73},
        {"top": 71, "bottom": 72, "shoes": 73, "outer": 76},
    ]
    assert [look.status for look in result.looks[3:]] == ["available", "available"]


@pytest.mark.parametrize("blocked", ["request", "colour", "missing-shoes"])
def test_unavailable_with_additional_constraints(monkeypatch, caplog, blocked):
    request = AgentRecommendationRequest(message="내 옷만 써줘. 흰 운동화만 신을 수 있어.")
    wardrobe = [dict(item) for item in WARDROBE]
    if blocked == "colour":
        wardrobe[-1]["color"] = "red"
    elif blocked == "missing-shoes":
        wardrobe.pop()

    looks = [_unavailable(index) for index in range(1, 6)]
    result, context = _recommend(monkeypatch, request, wardrobe, looks)
    assert all(look.status == "unavailable" for look in result.looks)
    has_candidate = blocked == "request"
    assert bool(context["wardrobe_examples"]) == has_candidate
    assert "look4_candidate_items" not in context
    assert "wardrobe_guidance" not in context
    events = [record.getMessage() for record in caplog.records if record.name == "app.agent.qwen"]
    assert events == (
        ["Qwen LOOK 4 unavailable with a colour-eligible wardrobe candidate"]
        if has_candidate
        else []
    )


@pytest.mark.parametrize(
    ("disliked", "top_id", "name"), [("네이비", 74, "빨강 니트"), ("빨강", 71, "네이비 셔츠")]
)
def test_single_wardrobe_candidate_names_the_eligible_top(monkeypatch, disliked, top_id, name):
    monkeypatch.setitem(PREFERENCE, "disliked_colors", [disliked])
    navy = {**WARDROBE[0], "color": "네이비"}
    red = {**navy, "item_id": 74, "color": "빨강", "type": "니트"}
    wardrobe = [navy, red, *WARDROBE[1:]]
    looks = [_unavailable(1), _unavailable(2), _unavailable(3), _available(4), _unavailable(5)]
    looks[3]["items"][0].update(name=name, item_id=top_id)
    _, context = _recommend(
        monkeypatch, AgentRecommendationRequest(message="내 옷만 추천해줘"), wardrobe, looks
    )
    assert context["look4_candidate_items"][0] == {"slot": "top", "item_id": top_id, "name": name}
    assert [piece["item_id"] for piece in context["look4_candidate_items"]] == [top_id, 72, 73]


@pytest.mark.parametrize(
    ("request_data", "suggest"),
    [
        ({"message": "보유한 옷만 사용해서 코디 추천해 주세요."}, True),
        ({"message": "내 옷만 추천해줘", "place": "서울"}, False),
        ({"message": "내 옷만 추천해줘. 울 소재는 입을 수 없어."}, False),
    ],
)
def test_single_candidate_suggestion_scope(monkeypatch, request_data, suggest):
    looks = [_unavailable(1), _unavailable(2), _unavailable(3), _available(4), _unavailable(5)]
    _, context = _recommend(
        monkeypatch, AgentRecommendationRequest(**request_data), WARDROBE, looks
    )
    assert ("look4_candidate_items" in context) == suggest
    assert ("wardrobe_guidance" in context) == suggest
