import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import app.api.v1.agent as agent_api
from app.agent.contracts import AgentDraft, AgentRecommendationResponse
from app.core.database import engine, get_db
from app.main import app
from app.services import wardrobe_images


@pytest.fixture
def client_and_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(wardrobe_images, "MEDIA_ROOT", tmp_path / "media")
    with engine.connect() as connection:
        transaction = connection.begin()

        def override_db():
            with Session(
                bind=connection,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        try:
            with TestClient(app) as test_client:
                yield test_client, connection
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(agent_api.get_agent_service, None)
            transaction.rollback()


def _signup_and_login(client: TestClient) -> dict[str, str | int]:
    email = f"history-{uuid4().hex}@example.com"
    password = "TestPassword123!"
    assert (
        client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": password},
        ).status_code
        == 201
    )

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    return {
        "id": login.json()["id"],
        "csrf": login.json()["csrf_token"],
    }


def _recommend(client: TestClient, csrf: str):
    return client.post(
        "/api/v1/agent/recommend",
        headers={"X-CSRF-Token": csrf},
        json={"message": "출근 코디를 추천해줘"},
    )


def test_recommend_returns_required_id_and_persists_five_looks(client_and_connection):
    client, connection = client_and_connection
    account = _signup_and_login(client)

    response = _recommend(client, str(account["csrf"]))

    assert response.status_code == 200
    body = response.json()
    validated = AgentRecommendationResponse.model_validate(body)
    recommendation_id = UUID(body["recommendation_id"])

    assert AgentRecommendationResponse.model_fields["recommendation_id"].is_required()
    assert validated.recommendation_id == recommendation_id
    assert [(look.look_id, look.role) for look in validated.looks] == [
        (1, "preference_best"),
        (2, "preference_alternative"),
        (3, "exploration"),
        (4, "wardrobe_best"),
        (5, "wardrobe_alternative"),
    ]

    row = (
        connection.execute(
            text("""
                SELECT id, user_id, looks
                FROM recommendation_runs
                WHERE id = :id
            """),
            {"id": recommendation_id},
        )
        .mappings()
        .one()
    )

    assert row["id"] == recommendation_id
    assert row["user_id"] == account["id"]
    assert isinstance(row["looks"], list)
    assert len(row["looks"]) == 5
    assert row["looks"] == body["looks"]


def test_recommendation_history_uses_authenticated_user_as_owner(client_and_connection):
    client, connection = client_and_connection
    first_account = _signup_and_login(client)
    first = _recommend(client, str(first_account["csrf"]))
    assert first.status_code == 200

    second_account = _signup_and_login(client)
    second = _recommend(client, str(second_account["csrf"]))
    assert second.status_code == 200

    first_id = UUID(first.json()["recommendation_id"])
    second_id = UUID(second.json()["recommendation_id"])
    rows = connection.execute(
        text("""
            SELECT id, user_id
            FROM recommendation_runs
            WHERE id = :first_id OR id = :second_id
        """),
        {"first_id": first_id, "second_id": second_id},
    ).mappings()
    owners = {row["id"]: row["user_id"] for row in rows}

    assert owners == {
        first_id: first_account["id"],
        second_id: second_account["id"],
    }


def test_recommendation_save_failure_rolls_back_and_returns_500(
    client_and_connection,
    monkeypatch,
):
    client, connection = client_and_connection
    account = _signup_and_login(client)
    failed_id = uuid4()
    rollback_calls = 0

    def fail_after_insert(db, user_id, result):
        nonlocal rollback_calls
        del result
        original_rollback = db.rollback

        def tracked_rollback():
            nonlocal rollback_calls
            rollback_calls += 1
            original_rollback()

        db.rollback = tracked_rollback
        db.execute(
            text("""
                INSERT INTO recommendation_runs (id, user_id, looks)
                VALUES (:id, :user_id, CAST(:looks AS JSONB))
            """),
            {
                "id": failed_id,
                "user_id": user_id,
                "looks": json.dumps([{} for _ in range(5)]),
            },
        )
        raise SQLAlchemyError("forced recommendation persistence failure")

    monkeypatch.setattr(agent_api, "save_recommendation", fail_after_insert)

    response = _recommend(client, str(account["csrf"]))

    assert response.status_code == 500
    assert response.json() == {"detail": "추천 결과 저장 중 오류가 발생했습니다."}
    assert rollback_calls == 1
    assert (
        connection.execute(
            text("SELECT COUNT(*) FROM recommendation_runs WHERE id = :id"),
            {"id": failed_id},
        ).scalar_one()
        == 0
    )


def test_invalid_model_response_contract_returns_502_without_persistence(
    client_and_connection,
):
    client, connection = client_and_connection
    account = _signup_and_login(client)

    class InvalidContractService:
        def recommend(self, request, runtime):
            del request, runtime
            return AgentDraft(
                context_summary="고정 5 LOOK 계약을 위반한 결과",
                looks=[],
            )

    app.dependency_overrides[agent_api.get_agent_service] = InvalidContractService

    response = _recommend(client, str(account["csrf"]))

    assert response.status_code == 502
    assert response.json() == {"detail": "Agent 결과가 고정 JSON 형식과 일치하지 않습니다."}
    assert (
        connection.execute(
            text("SELECT COUNT(*) FROM recommendation_runs WHERE user_id = :user_id"),
            {"user_id": account["id"]},
        ).scalar_one()
        == 0
    )
