from copy import deepcopy
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.agent.contracts import AgentRecommendationRequest
from app.agent.inference import MockInferenceEngine
from app.agent.validators import validate_agent_json
from app.api.v1.auth import get_current_user, require_csrf
from app.api.v1.settings import PreferencesUpdate
from app.core.database import get_db
from app.main import app


@pytest.mark.parametrize(
    "preference, weights, top_colors, expected_top_id",
    [
        ({"preferred_colors": ["navy"]}, {"fits": {"wide": 3}}, ("navy", "red"), 1),
        ({"preferred_fit": "regular"}, {"colors": {"red": 3}}, ("navy", "red"), 1),
        ({"preferred_colors": ["네이비"]}, {"fits": {"wide": 3}}, ("navy", "red"), 1),
        ({}, {"fits": {"wide": 3}}, ("navy", "red"), 2),
        ({"preferred_colors": ["navy"]}, {"fits": {"wide": 3}}, ("navy", "navy"), 2),
    ],
)
def test_owned_recommendations_prioritize_explicit_preferences(
    preference, weights, top_colors, expected_top_id
):
    context = {"preference": preference, "feedback_summary": {"weights": weights}}
    original = deepcopy(context)
    wardrobe = [
        {
            "item_id": index,
            "category": "top",
            "type": "shirt",
            "color": color,
            "fit": fit,
        }
        for index, color, fit in ((1, top_colors[0], "regular"), (2, top_colors[1], "wide"))
    ] + [
        {
            "item_id": 3,
            "category": "bottom",
            "type": "pants",
            "color": "navy",
            "fit": "regular",
        },
        {
            "item_id": 4,
            "category": "shoes",
            "type": "sneakers",
            "color": "navy",
            "fit": "regular",
        },
    ]

    draft = MockInferenceEngine().generate(
        AgentRecommendationRequest(message="내 옷으로 추천"),
        {"get_user_context": context, "get_wardrobe": wardrobe},
    )

    assert draft.looks[3].items[0].item_id == expected_top_id
    assert context == original


@pytest.fixture
def preferences_client():
    db = Mock()
    previous = dict(app.dependency_overrides)
    app.dependency_overrides.update(
        {
            get_current_user: lambda: {"id": 1},
            require_csrf: lambda: None,
            get_db: lambda: db,
        }
    )
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize("field", ["preferred_styles", "preferred_colors", "disliked_colors"])
@pytest.mark.parametrize("value", ["x" * 101, "   "])
def test_preference_api_rejects_invalid_tags_before_writing(preferences_client, field, value):
    client, db = preferences_client

    response = client.patch("/api/v1/preferences/me", json={field: [value]})

    assert response.status_code == 422
    db.execute.assert_not_called()


def test_preference_tag_boundary_allows_100_characters_after_trimming():
    value = "x" * 100
    preference = PreferencesUpdate(
        preferred_styles=[f" {value} "],
        preferred_colors=[f" {value} "],
        disliked_colors=[f" {value} "],
    )

    assert preference.preferred_styles == [value]
    assert preference.preferred_colors == [value]
    assert preference.disliked_colors == [value]


def test_legacy_invalid_preferences_can_be_read_and_recommended(preferences_client):
    client, db = preferences_client
    legacy = {
        "user_id": 1,
        "preferred_styles": ["x" * 101, "   ", " minimal "],
        "preferred_colors": ["x" * 101, "", " navy "],
        "disliked_colors": ["x" * 101, " ", " red "],
        "preferred_fit": " regular ",
    }
    original = deepcopy(legacy)
    db.execute.return_value.mappings.return_value.first.return_value = legacy

    response = client.get("/api/v1/preferences/me")

    assert response.status_code == 200
    assert response.json() == {
        "user_id": 1,
        "preferred_styles": ["minimal"],
        "preferred_colors": ["navy"],
        "disliked_colors": ["red"],
        "preferred_fit": "regular",
    }
    draft = MockInferenceEngine().generate(
        AgentRecommendationRequest(message="추천"), {"get_user_context": {"preference": legacy}}
    )
    assert draft.looks[0].status == "available"
    assert draft.looks[0].style.startswith("minimal")
    assert "navy" in draft._look_features[1].colors
    assert len(validate_agent_json(draft).looks) == 5
    assert legacy == original
