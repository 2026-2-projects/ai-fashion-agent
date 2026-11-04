import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.agent.contracts import AgentRecommendationRequest, AgentRecommendationResponse
from app.agent.inference import MockInferenceEngine
from app.agent.tools.user_context import get_user_context
from app.agent.validators import validate_agent_json
from app.api.v1.agent import get_agent_service
from app.core.database import engine, get_db
from app.main import app
from app.services.feedback import FeedbackService, FeedbackWrite, summarize_signals


@pytest.fixture
def feedback_client():
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            app.dependency_overrides[get_db] = lambda: db
            try:
                with TestClient(app) as client:
                    yield client, db
            finally:
                app.dependency_overrides.pop(get_db, None)
                transaction.rollback()


def login(client):
    credentials = {"email": f"feedback-{uuid4().hex}@example.com", "password": "TestPassword123!"}
    assert client.post("/api/v1/auth/signup", json=credentials).status_code == 201
    result = client.post("/api/v1/auth/login", json=credentials)
    assert result.status_code == 200
    return result.json()["id"], {"X-CSRF-Token": result.json()["csrf_token"]}


def recommend(client, headers):
    result = client.post(
        "/api/v1/agent/recommend", headers=headers, json={"message": "출근 코디 추천"}
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert len(body["look_refs"]) == 5
    assert [ref["look_id"] for ref in body["look_refs"]] == [1, 2, 3, 4, 5]
    return body, {ref["look_id"]: ref["outfit_id"] for ref in body["look_refs"]}


def summary(db, user_id):
    return get_user_context(db, user_id)["feedback_summary"]


def test_signal_summary_deduplicates_and_penalizes_only_selected_dimensions():
    signals = [
        {
            "features": {"styles": ["미니멀"], "colors": ["navy", "네이비"], "fits": ["wide"]},
            "reaction": "like",
            "reason_codes": [],
        },
        {
            "features": {"styles": ["minimal"], "colors": ["navy"], "fits": ["wide"]},
            "reaction": "dislike",
            "reason_codes": ["color"],
        },
    ]
    result = summarize_signals(signals)
    assert result["weights"] == {"styles": {"minimal": 1}, "fits": {"wide": 1}, "colors": {}}
    assert summarize_signals([]) == {}


def test_feedback_replace_cancel_and_save_are_reversible(feedback_client):
    client, db = feedback_client
    user_id, headers = login(client)
    _, refs = recommend(client, headers)
    outfit = refs[1]
    url = f"/api/v1/outfits/{outfit}/feedback"
    assert client.get(url).json()["reaction"] is None
    for _ in range(2):
        response = client.put(url, headers=headers, json={"reaction": "like"})
        assert response.status_code == 200
    assert summary(db, user_id)["weights"]["styles"]["minimal"] == 1
    saved_at = None
    for _ in range(2):
        response = client.put(f"/api/v1/saved-outfits/{outfit}", headers=headers)
        assert response.status_code == 200, response.text
        if saved_at:
            assert response.json()["saved_at"] == saved_at
        saved_at = response.json()["saved_at"]
    assert summary(db, user_id)["weights"]["styles"]["minimal"] == 4
    response = client.put(
        url,
        headers=headers,
        json={
            "reaction": "dislike",
            "reason_codes": ["color", "color"],
            "comment": "색상이 별로예요",
        },
    )
    assert response.status_code == 200
    assert response.json()["reason_codes"] == ["color"]
    assert client.get(url).json()["comment"] == "색상이 별로예요"
    assert summary(db, user_id)["weights"]["colors"]["navy"] == 2
    assert summary(db, user_id)["weights"]["styles"]["minimal"] == 3
    assert client.delete(url, headers=headers).status_code == 204
    assert client.delete(url, headers=headers).status_code == 204
    assert summary(db, user_id)["weights"]["colors"]["navy"] == 3
    assert client.delete(f"/api/v1/saved-outfits/{outfit}", headers=headers).status_code == 204
    assert summary(db, user_id) == {}
    assert client.get(f"/api/v1/saved-outfits/{outfit}").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"reaction": "dislike"},
        {"reaction": "dislike", "reason_codes": ["unknown"]},
        {"reaction": "like", "reason_codes": ["color"]},
        {"reaction": "like", "user_id": 99},
        {"reaction": "like", "comment": "x" * 1001},
    ],
)
def test_invalid_feedback_is_rejected_without_changing_memory(feedback_client, payload):
    client, db = feedback_client
    user_id, headers = login(client)
    _, refs = recommend(client, headers)
    response = client.put(f"/api/v1/outfits/{refs[1]}/feedback", headers=headers, json=payload)
    assert response.status_code == 422
    assert summary(db, user_id) == {}


def test_user_isolation_csrf_and_unavailable_looks(feedback_client):
    client, db = feedback_client
    _, headers = login(client)
    _, refs = recommend(client, headers)
    feedback = f"/api/v1/outfits/{refs[1]}/feedback"
    saved = f"/api/v1/saved-outfits/{refs[1]}"
    assert client.put(feedback, json={"reaction": "like"}).status_code == 403
    assert client.put(saved).status_code == 403
    assert client.put(saved, headers=headers, json={"snapshot": {}}).status_code == 422
    for path in (f"/api/v1/outfits/{refs[4]}/feedback", f"/api/v1/saved-outfits/{refs[4]}"):
        response = client.put(
            path, headers=headers, json={"reaction": "like"} if "feedback" in path else {}
        )
        assert response.status_code == 422
    second_id, second_headers = login(client)
    assert client.get(feedback).status_code == 404
    assert (
        client.put(feedback, headers=second_headers, json={"reaction": "like"}).status_code == 404
    )
    assert client.put(saved, headers=second_headers).status_code == 404
    assert client.delete(saved, headers=second_headers).status_code == 404
    assert summary(db, second_id) == {}
    assert client.get("/api/v1/saved-outfits").json()["total"] == 0
    client.cookies.clear()
    assert client.get(feedback).status_code == 401
    assert client.get("/api/v1/saved-outfits").status_code == 401


def test_saved_snapshot_survives_clothing_deletion_but_new_save_is_blocked(feedback_client):
    client, _ = feedback_client
    _, headers = login(client)
    ids = []
    for category, color in (
        ("top", "navy"),
        ("top", "white"),
        ("bottom", "black"),
        ("shoes", "white"),
    ):
        response = client.post(
            "/api/v1/wardrobe",
            headers=headers,
            json={"category": category, "type": category, "color": color, "fit": "regular"},
        )
        assert response.status_code == 201
        ids.append(response.json()["item_id"])
    _, refs = recommend(client, headers)
    saved = client.put(f"/api/v1/saved-outfits/{refs[4]}", headers=headers)
    assert saved.status_code == 200
    original_names = [item["name"] for item in saved.json()["look"]["items"]]
    assert client.delete(f"/api/v1/wardrobe/{ids[2]}", headers=headers).status_code == 204
    detail = client.get(f"/api/v1/saved-outfits/{refs[4]}")
    assert detail.status_code == 200
    assert detail.json()["missing_item_ids"] == [ids[2]]
    assert [item["name"] for item in detail.json()["look"]["items"]] == original_names
    assert client.put(f"/api/v1/saved-outfits/{refs[4]}", headers=headers).status_code == 200
    blocked = client.put(f"/api/v1/saved-outfits/{refs[5]}", headers=headers)
    assert blocked.status_code == 409
    assert client.get("/api/v1/saved-outfits").json()["total"] == 1


def test_saved_listing_pagination_and_account_cascade(feedback_client):
    client, db = feedback_client
    user_id, headers = login(client)
    _, refs = recommend(client, headers)
    for index in (1, 2):
        assert (
            client.put(f"/api/v1/saved-outfits/{refs[index]}", headers=headers).status_code == 200
        )
    assert (
        client.put(
            f"/api/v1/outfits/{refs[1]}/feedback", headers=headers, json={"reaction": "like"}
        ).status_code
        == 200
    )
    first = client.get("/api/v1/saved-outfits?limit=1").json()
    second = client.get("/api/v1/saved-outfits?limit=1&offset=1").json()
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["outfit_id"] != second["items"][0]["outfit_id"]
    assert client.get("/api/v1/saved-outfits?limit=101").status_code == 422
    assert client.get("/api/v1/saved-outfits?offset=-1").status_code == 422
    assert (
        client.request(
            "DELETE", "/api/v1/auth/account", headers=headers, json={"password": "TestPassword123!"}
        ).status_code
        == 204
    )
    for table in ("recommendation_looks", "feedback", "saved_outfits", "user_preferences"):
        assert (
            db.execute(
                text(f"SELECT count(*) FROM {table} WHERE user_id = :user"), {"user": user_id}
            ).scalar_one()
            == 0
        )


def test_feedback_affects_next_recommendation_and_manual_exclusions_win(feedback_client):
    client, db = feedback_client
    user_id, headers = login(client)
    assert (
        client.patch(
            "/api/v1/preferences/me",
            headers=headers,
            json={
                "preferred_styles": ["minimal", "casual"],
                "preferred_colors": ["navy", "ivory"],
                "disliked_colors": ["white", "black"],
                "preferred_fit": "wide",
            },
        ).status_code
        == 200
    )
    before, refs = recommend(client, headers)
    assert before["looks"][0]["style"].startswith("minimal")
    assert client.put(f"/api/v1/saved-outfits/{refs[2]}", headers=headers).status_code == 200
    after, _ = recommend(client, headers)
    assert after["looks"][0]["style"].startswith("casual")
    context = get_user_context(db, user_id)
    assert context["preference"]["preferred_styles"] == ["minimal", "casual"]
    assert context["feedback_summary"]["weights"]["styles"]["casual"] == 3
    assert context["preference"]["preferred_fit"] == "wide"
    for look in after["looks"][:3]:
        assert all(
            "화이트" not in item["name"] and "블랙" not in item["name"] for item in look["items"]
        )


def test_tendency_and_fit_reasons_do_not_penalize_color():
    result = summarize_signals(
        [
            {
                "features": {"styles": ["formal"], "fits": ["slim"], "colors": ["navy"]},
                "reaction": "dislike",
                "reason_codes": ["too_formal", "fit"],
            }
        ]
    )
    assert result["weights"] == {"styles": {"formal": -1}, "fits": {"slim": -1}, "colors": {}}
    assert result["disliked_tendencies"] == ["too_formal"]


@pytest.mark.parametrize("corruption", ["count", "roles", "extra", "bool_id", "json", "mutated"])
def test_json_validator_rejects_malformed_model_content(corruption):
    draft = MockInferenceEngine().generate(AgentRecommendationRequest(message="추천"), {})
    raw = deepcopy(draft.model_dump())
    if corruption == "count":
        raw["looks"].pop()
    elif corruption == "roles":
        raw["looks"][0]["role"] = "exploration"
    elif corruption == "extra":
        raw["secret"] = "unexpected"
    elif corruption == "bool_id":
        raw["looks"][0]["items"][0]["item_id"] = True
    elif corruption == "json":
        raw = "```json\n{}\n```"
    elif corruption == "mutated":
        draft.looks[0].items.pop()
        raw = draft
    with pytest.raises(ValidationError):
        validate_agent_json(raw)


def test_generated_wardrobe_is_rechecked_against_current_user_before_snapshot(feedback_client):
    client, db = feedback_client
    _, headers = login(client)
    for category in ("top", "bottom", "shoes"):
        result = client.post(
            "/api/v1/wardrobe",
            headers=headers,
            json={"category": category, "type": category, "color": "navy", "fit": "regular"},
        )
        assert result.status_code == 201
    body, _ = recommend(client, headers)
    borrowed = AgentRecommendationResponse.model_validate(body)
    other_id, other_headers = login(client)
    # Even a faulty model/service returning another account's real IDs must be rejected.
    app.dependency_overrides[get_agent_service] = lambda: SimpleNamespace(
        recommend=lambda *args: borrowed.model_copy(deep=True)
    )
    try:
        response = client.post(
            "/api/v1/agent/recommend", headers=other_headers, json={"message": "내 옷으로 추천"}
        )
        assert response.status_code == 502
        assert (
            db.execute(
                text("SELECT count(*) FROM recommendation_looks WHERE user_id=:id"),
                {"id": other_id},
            ).scalar_one()
            == 0
        )
    finally:
        app.dependency_overrides.pop(get_agent_service, None)


def test_runtime_attributes_are_not_part_of_model_json():
    draft = MockInferenceEngine().generate(AgentRecommendationRequest(message="추천"), {})
    assert draft._look_features[1].colors
    assert "_attributes" not in draft.model_dump_json()
    assert "_look_features" not in draft.model_dump_json()
    validated = validate_agent_json(draft)
    assert validated._look_features == draft._look_features


def test_concurrent_likes_and_saves_do_not_duplicate_weights():
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("Concurrency test requires an explicitly selected TEST_DATABASE_URL")
    user_id = None
    try:
        with Session(engine) as db:
            user_id = db.execute(
                text("""
                INSERT INTO users (email, password_hash) VALUES (:email, 'test-only') RETURNING id
            """),
                {"email": f"concurrent-{uuid4().hex}@example.com"},
            ).scalar_one()
            db.commit()
            draft = MockInferenceEngine().generate(AgentRecommendationRequest(message="추천"), {})
            response = AgentRecommendationResponse(
                context_summary=draft.context_summary, looks=draft.looks, called_tools=[]
            )
            response._look_features = draft._look_features
            response = FeedbackService(db).record_recommendation(user_id, response)
            outfit = response.look_refs[0].outfit_id

        def click(_):
            with Session(engine) as db:
                service = FeedbackService(db)
                service.put_feedback(user_id, outfit, FeedbackWrite(reaction="like"))
                service.save(user_id, outfit)

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(click, range(6)))
        with Session(engine) as db:
            result = summary(db, user_id)
            assert result["signals"] == {"like": 1, "dislike": 0, "save": 1}
            assert result["weights"]["styles"]["minimal"] == 4
    finally:
        if user_id is not None:
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


def test_initial_sql_builds_clean_schema_and_repeated_migration_preserves_data():
    schema = "feedback_ddl_" + uuid4().hex
    with engine.connect() as connection:
        try:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            paths = sorted((Path(__file__).parents[1] / "sql").glob("*.sql"))
            for path in paths:
                connection.exec_driver_sql(path.read_text())
                connection.commit()
            assert connection.execute(
                text("SELECT version FROM schema_migrations ORDER BY version")
            ).scalars().all() == [1, 2]
            connection.execute(
                text("INSERT INTO users(email,password_hash) VALUES ('ddl@example.com','test')")
            )
            connection.commit()
            with pytest.raises(ProgrammingError):
                connection.exec_driver_sql(paths[-1].read_text())
            connection.rollback()
            assert connection.execute(text("SELECT count(*) FROM users")).scalar_one() == 1
        finally:
            connection.rollback()
            connection.exec_driver_sql("SET search_path TO public")
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            connection.commit()
