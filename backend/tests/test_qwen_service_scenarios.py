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
    assert context["wardrobe_examples"] == []
    assert "look4_candidate_items" not in context
    assert context["owned_item_constraints"] == [
        {"slot": "shoes", "kind": "스니커즈", "color": "흰색", "excluded": False}
    ]


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
    assert ("look4_candidate_items" in context and "wardrobe_guidance" in context) == suggest


def test_grounded_reasons_preserve_model_choices_and_ignore_unobserved_claims(monkeypatch):
    monkeypatch.setitem(PREFERENCE, "preferred_colors", ["연보라"])
    wardrobe = [
        {**WARDROBE[0], "color": "청록", "type": "가디건"},
        {**WARDROBE[1], "color": "회색", "type": "치노"},
        {**WARDROBE[2], "color": "밤색", "type": "더비화"},
    ]
    looks = [_available(index) for index in range(1, 5)] + [_unavailable(5)]
    for look in looks[:4]:
        for piece, source in zip(look["items"], wardrobe, strict=True):
            piece["name"] = f"{source['color']} {source['type']}"
        look["reason"] = (
            "선호색인 청록에 맞췄습니다. 내일 17℃의 야외 연주회에 어울리며 "
            "신발이 방수와 미끄럼 방지 기능을 보장합니다."
        )

    result, context = _recommend(
        monkeypatch, AgentRecommendationRequest(message="코디를 추천해줘"), wardrobe, looks
    )

    assert set(result.called_tools) == {"get_user_context", "get_wardrobe"}
    assert "weather" not in context and "calendar_events" not in context
    for raw, final in zip(looks, result.looks, strict=True):
        expected = {key: value for key, value in raw.items() if key != "reason"}
        assert final.model_dump(exclude={"reason": True, "items": {"__all__": {"image_url"}}}) == (
            expected
        )
        assert all(
            claim not in final.reason
            for claim in ("17℃", "연주회", "방수", "미끄럼", "선호색인 청록")
        )
    owned_reason = result.looks[3].reason
    assert all(word in owned_reason for word in ("청록", "가디건", "더비화"))
    assert "연보라" not in owned_reason


def test_unavailable_reason_distinguishes_required_type_from_missing_slot(monkeypatch):
    request = AgentRecommendationRequest(
        message="내 옷만 추천해줘. 합성식별표 R29-SYN-07. 보라색 부츠만 신을 수 있어."
    )
    looks = [_unavailable(index) for index in range(1, 6)]
    for look in looks[3:]:
        look["reason"] = "옷장에 상의·하의·신발이 모두 빠져 있습니다."

    full, _ = _recommend(monkeypatch, request, WARDROBE, looks)
    missing, _ = _recommend(monkeypatch, request, WARDROBE[:2], looks)

    for full_look, missing_look in zip(full.looks[3:], missing.looks[3:], strict=True):
        assert full_look.status == missing_look.status == "unavailable"
        assert full_look.items == missing_look.items == []
        assert "로퍼" in full_look.reason and "1개" in full_look.reason
        assert "R29-SYN-07" not in full_look.reason and "R29-SYN-07" not in missing_look.reason
        assert "신발" in missing_look.reason and "로퍼" not in missing_look.reason
        assert full_look.reason != missing_look.reason


def test_no_second_suggestion_does_not_claim_inventory_has_only_one_combination(monkeypatch):
    wardrobe = [*WARDROBE, {**WARDROBE[0], "item_id": 76, "type": "블라우스"}]
    request = AgentRecommendationRequest(message="내 옷만 써서 격식 있는 만찬에 맞춰 추천해줘")
    looks = [_unavailable(1), _unavailable(2), _unavailable(3), _available(4), _unavailable(5)]
    looks[4]["reason"] = "실제 옷장에 등록된 상의가 딱 하나뿐이라 추가로 조합할 수 없습니다."

    result, context = _recommend(monkeypatch, request, wardrobe, looks)

    assert len(context["wardrobe_examples"]) == 2
    assert result.looks[3].status == "available"
    assert result.looks[4].status == "unavailable" and result.looks[4].items == []
    assert result.looks[4].reason != looks[4]["reason"]
    assert "하나뿐" not in result.looks[4].reason and "유일" not in result.looks[4].reason


def test_generic_names_alone_do_not_prove_a_different_item(monkeypatch):
    request = AgentRecommendationRequest(message="코디 추천해줘")
    looks = [_available(index) for index in range(1, 5)] + [_unavailable(5)]
    looks[0]["items"][2]["name"] = "검정 로퍼"
    looks[1]["items"][2]["name"] = "블랙 로퍼"
    looks[1]["reason"] = "첫 번째 제안과 다른 신발로 교체했습니다."

    result, _ = _recommend(monkeypatch, request, WARDROBE, looks)

    assert result.looks[0].items[2].name == "검정 로퍼"
    assert result.looks[1].items[2].name == "블랙 로퍼"
    assert all(word not in result.looks[1].reason for word in ("교체", "바꾼", "다른 신발"))


def test_owned_reason_acknowledges_an_explicit_matching_preference(monkeypatch):
    request = AgentRecommendationRequest(message="내 옷만 추천해줘")
    looks = [_unavailable(1), _unavailable(2), _unavailable(3), _available(4), _unavailable(5)]
    selected = {**WARDROBE[0], "color": "청록"}
    unused = {**selected, "item_id": 77, "color": "호박색"}
    wardrobe = [selected, *WARDROBE[1:], unused]
    monkeypatch.setitem(PREFERENCE, "preferred_colors", ["호박색", "청록"])

    result, _ = _recommend(monkeypatch, request, wardrobe, looks)

    reason = result.looks[3].reason
    assert "청록" in reason and "선호" in reason
    assert "호박색" not in reason
    assert [item.item_id for item in result.looks[3].items] == [71, 72, 73]


def _piece(slot, iid, color, kind):
    return {"item_id": iid, "category": slot, "color": color, "type": kind}


def _selection(looks):
    return [dict((p.slot, p.item_id) for p in look.items) for look in looks[3:]]


def test_required_registered_identity_applies_to_both_owned_looks(monkeypatch):
    wardrobe = [*WARDROBE, _piece("신발", 817, "브라운", "부츠")]
    looks = [_unavailable(i) for i in range(1, 6)]
    looks[3:] = [_available(4), _available(5)]
    looks[3]["items"][-1].update(item_id=817, name="갈색 부츠")
    # A plausible model label must never turn the registered black loafer into a boot.
    looks[4]["items"][-1]["name"] = "갈색 부츠"
    result, context = _recommend(
        monkeypatch,
        AgentRecommendationRequest(message="갈색 부츠만 신을 수 있어. 내 옷만 써 줘."),
        wardrobe,
        looks,
    )
    assert context["wardrobe_examples"] == [{"top": 71, "bottom": 72, "shoes": 817}]
    assert _selection(result.looks) == [{"top": 71, "bottom": 72, "shoes": 817}, {}]


def test_required_outfit_is_recovered_with_same_shoes_and_different_bottoms(monkeypatch):
    wardrobe = [
        _piece("하의", 934, "회색", "치노"),
        _piece("신발", 611, "아이보리", "샌들"),
        *reversed(WARDROBE),
    ]
    result, context = _recommend(
        monkeypatch,
        AgentRecommendationRequest(message="내 옷만 써 줘. 신발은 반드시 아이보리 샌들이어야 해."),
        wardrobe,
        [_unavailable(i) for i in range(1, 6)],
    )
    selected = _selection(result.looks)
    assert {look["shoes"] for look in selected} == {611}
    assert {look["bottom"] for look in selected} == {72, 934}
    assert all(example["shoes"] == 611 for example in context["wardrobe_examples"])


def test_excluded_top_is_not_a_required_top(monkeypatch):
    wardrobe = [*WARDROBE, _piece("상의", 814, "흰색", "니트")]
    result, context = _recommend(
        monkeypatch,
        AgentRecommendationRequest(message="내 옷만 써 줘. 셔츠는 제외해 줘."),
        wardrobe,
        [_unavailable(i) for i in range(1, 4)] + [_available(4), _unavailable(5)],
    )
    assert _selection(result.looks) == [{"top": 814, "bottom": 72, "shoes": 73}, {}]
    assert all(ex["top"] == 814 for ex in context["wardrobe_examples"])


@pytest.mark.parametrize(
    "message", ["부츠를 선호해.", "부츠가 필수는 아니야.", "부츠만 신을 필요는 없어."]
)
def test_preference_or_negated_obligation_allows_other_shoes(monkeypatch, message):
    result, context = _recommend(
        monkeypatch,
        AgentRecommendationRequest(message="내 옷만 써 줘. " + message),
        WARDROBE,
        [_unavailable(i) for i in range(1, 4)] + [_available(4), _unavailable(5)],
    )
    assert context["wardrobe_examples"] == [{"top": 71, "bottom": 72, "shoes": 73}]
    assert _selection(result.looks)[0]["shoes"] == 73


def test_unverifiable_material_is_not_assumed_to_be_satisfied(monkeypatch):
    result, _ = _recommend(
        monkeypatch,
        AgentRecommendationRequest(message="내 옷만 써 줘. 반드시 방수 로퍼를 신어야 해."),
        WARDROBE,
        [_unavailable(i) for i in range(1, 4)] + [_available(4), _unavailable(5)],
    )
    assert all(look.status == "unavailable" for look in result.looks[3:])
    assert all("확인" in look.reason for look in result.looks[3:])


def test_required_item_never_masks_foreign_id(monkeypatch):
    looks = [_unavailable(i) for i in range(1, 4)] + [_available(4), _unavailable(5)]
    looks[3]["items"][-1]["item_id"] = 99211
    with pytest.raises(AgentResultError, match="등록되지 않은"):
        _recommend(
            monkeypatch,
            AgentRecommendationRequest(message="내 옷만 써 줘. 로퍼가 필수야."),
            WARDROBE,
            looks,
        )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("셔츠와 흰 허밍슈즈가 모두 필수야.", [712]),
        ("흰 허밍슈즈 말고 골라 줘.", [73]),
        ("흰 허밍슈즈가 필수인 건 아니야.", [73, 712]),
        ("셔츠가 필수지만 방수 원단도 반드시 필요해.", []),
    ],
)
def test_registered_custom_type_and_negation(monkeypatch, message, expected):
    wardrobe = [*WARDROBE, _piece("신발", 712, "화이트", "허밍슈즈")]
    result, _ = _recommend(
        monkeypatch,
        AgentRecommendationRequest(message="내 옷만 써 줘. " + message),
        wardrobe,
        [_unavailable(i) for i in range(1, 6)],
    )
    assert sorted(c["shoes"] for c in _selection(result.looks) if c) == sorted(expected)


@pytest.mark.parametrize(
    ("phrase", "blocked"),
    [
        ("흰 운동화가 필수야.", True),
        ("방수 기능이 필수야.", True),
        ("검정 로퍼가 필수야.", False),
    ],
)
def test_generation_schema_uses_verified_eligibility(phrase, blocked):
    request = AgentRecommendationRequest(message="내 옷만 써 줘. " + phrase)

    def reply(sent):
        schema = json.loads(sent.content)["response_format"]["json_schema"]["schema"]
        look = schema["$defs"]["FashionLook"]
        assert ("anyOf" in look) == blocked
        if blocked:
            assert look["anyOf"][1]["properties"]["items"] == {"const": []}
        body = {"looks": [_unavailable(i) for i in range(1, 6)]}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(body)},
                    }
                ]
            },
        )

    engine = QwenInferenceEngine(
        QwenSettings(base_url="http://127.0.0.1:8001/v1", model="fixture"),
        transport=httpx.MockTransport(reply),
    )
    engine.generate(
        request, {"get_user_context": {"preference": PREFERENCE}, "get_wardrobe": WARDROBE}
    )
