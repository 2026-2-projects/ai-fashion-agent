"""Contextual omissions must not turn inventory evidence into a suitability judgment."""

import json

import httpx
import pytest

from app.agent.contracts import AgentRecommendationRequest
from app.agent.errors import InferenceResponseError
from app.agent.qwen import QwenInferenceEngine
from app.agent.settings import QwenSettings

WARDROBE = [
    {"item_id": 21, "category": "상의", "type": "니트", "color": "밤색"},
    {"item_id": 22, "category": "하의", "type": "슬랙스", "color": "청록"},
    {"item_id": 23, "category": "신발", "type": "로퍼", "color": "검정"},
    {"item_id": 24, "category": "상의", "type": "셔츠", "color": "회색"},
]
WEATHER = {"get_weather": {"temperature_c": -3, "precipitation_type": "눈"}}
CALENDAR = {"get_calendar_events": [{"title": "야외 행사", "all_day": True}]}


def generate(wardrobe, facts, *, best=False, place=None, message="내 옷만 써 줘."):
    roles = (
        "preference_best",
        "preference_alternative",
        "exploration",
        "wardrobe_best",
        "wardrobe_alternative",
    )
    looks = [
        dict(look_id=i, role=role, status="unavailable", style=None, reason="제안 없음", items=[])
        for i, role in enumerate(roles, 1)
    ]
    if best:
        looks[3].update(
            status="available",
            style="미니멀",
            items=[
                {"slot": slot, "name": item["type"], "item_id": item["item_id"]}
                for slot, item in zip(("top", "bottom", "shoes"), wardrobe[:3], strict=True)
            ],
        )
    response = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps({"looks": looks})},
            }
        ]
    }
    engine = QwenInferenceEngine(
        QwenSettings(base_url="http://127.0.0.1:8001/v1", model="fixture"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)),
    )
    return engine.generate(
        AgentRecommendationRequest(message=message, place=place),
        {"get_wardrobe": wardrobe, "get_user_context": {"preference": {}}, **facts},
    ).looks[3:]


@pytest.mark.parametrize(
    ("facts", "best", "place"),
    [
        (WEATHER, False, None),  # Actual weather, no schedule fields; inventory alone would fill.
        (CALENDAR, True, None),  # A distinct alternative exists but no event-suitability rule.
        ({}, False, "원주"),  # Place supplied with no facts certifying suitability.
    ],
)
def test_unverified_context_omission_is_an_inference_error(facts, best, place):
    with pytest.raises(InferenceResponseError, match="적합"):
        generate(WARDROBE, facts, best=best, place=place)


@pytest.mark.parametrize(
    ("wardrobe", "message"),
    [
        (WARDROBE[:2], "내 옷만 써 줘."),
        (WARDROBE, "내 옷만 써 줘. 부츠가 필수야."),
        (WARDROBE, "내 옷만 써 줘. 검정 로퍼를 제외해."),
        (WARDROBE, "내 옷만 써 줘. 방수 로퍼가 필수야."),
    ],
)
def test_context_does_not_restore_missing_excluded_or_unverified_items(wardrobe, message):
    results = generate(wardrobe, WEATHER, message=message)
    assert all(look.status == "unavailable" and not look.items for look in results)


def test_only_complete_outfit_selected_no_contextual_alternative_is_invented():
    best, alternative = generate(WARDROBE[:3], CALENDAR, best=True)
    assert [p.item_id for p in best.items] == [21, 22, 23]
    assert alternative.status == "unavailable"


def test_inventory_only_omissions_still_restore_both_distinct_outfits():
    results = generate(WARDROBE, {})
    assert [[p.item_id for p in look.items] for look in results] == [[21, 22, 23], [24, 22, 23]]


@pytest.mark.parametrize(
    ("message", "facts"),
    [
        ("내 옷만 써 줘. 방수 샌들이 필수야.", {}),
        ("내 옷만 써 줘. 방수 샌들을 제외해.", WEATHER),
    ],
)
def test_registered_type_is_not_evidence_of_performance(message, facts, caplog):
    caplog.set_level("INFO", logger="app.agent.qwen")
    wardrobe = [*WARDROBE[:2], {**WARDROBE[2], "type": "방수 샌들"}]
    results = generate(wardrobe, facts, best=True, message=message)
    assert all(look.status == "unavailable" and "확인" in look.reason for look in results)
    assert any(
        getattr(record, "wardrobe_correction", {}).get("cause") == "unverified_constraint"
        for record in caplog.records
    )


def test_performance_exclusion_checks_all_registered_complete_outfits():
    wardrobe = [
        *WARDROBE[:2],
        {**WARDROBE[2], "type": "샌들"},  # Ordinary sandals have no verified waterproof rating.
        {**WARDROBE[2], "item_id": 30, "type": "방수 샌들"},
        {**WARDROBE[2], "item_id": 31, "type": "샌들"},
        {**WARDROBE[2], "item_id": 32, "type": "로퍼"},
    ]
    best, alternative = generate(
        wardrobe, {}, best=True, message="내 옷만 써 줘. 방수 샌들을 제외해."
    )
    assert [piece.item_id for piece in best.items] == [21, 22, 32]
    assert alternative.status == "unavailable" and not alternative.items


def test_registered_type_remains_selectable_without_performance_requirement():
    wardrobe = [*WARDROBE[:2], {**WARDROBE[2], "type": "방수 샌들"}]
    best, alternative = generate(wardrobe, {}, best=True)
    assert best.items[2].item_id == 23 and "방수 샌들" in best.items[2].name
    assert "등록" in best.reason and "확인되지" in best.reason
    assert alternative.status == "unavailable"


def test_different_registered_color_can_rule_out_a_performance_exclusion():
    wardrobe = [
        *WARDROBE[:2],
        {**WARDROBE[2], "type": "방수 샌들", "color": "흰색"},
        {**WARDROBE[2], "item_id": 33, "type": "샌들", "color": "검정"},
    ]
    best, alternative = generate(wardrobe, {}, message="내 옷만 써 줘. 검정 방수 샌들을 제외해.")
    assert [piece.item_id for piece in best.items] == [21, 22, 23]
    assert alternative.status == "unavailable"
