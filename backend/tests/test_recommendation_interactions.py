"""WBS 4.6 추천 LOOK 평가·저장·개인화 통합 테스트."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import app.services.recommendation_interactions as recommendation_interactions
from app.core.database import engine, get_db
from app.main import app
from app.services import wardrobe_images


@pytest.fixture
def client_and_connection(tmp_path, monkeypatch):
    """실제 PostgreSQL을 사용하되 각 테스트가 끝나면 모든 변경을 되돌린다."""
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
            transaction.rollback()


def _signup_and_login(client: TestClient) -> dict[str, str | int]:
    email = f"interactions-{uuid4().hex}@example.com"
    password = "TestPassword123!"
    signup = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password},
    )
    assert signup.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    return {
        "id": login.json()["id"],
        "csrf": login.json()["csrf_token"],
    }


def _recommend(client: TestClient, csrf: str) -> dict:
    response = client.post(
        "/api/v1/agent/recommend",
        headers={"X-CSRF-Token": csrf},
        json={"message": "출근 코디를 추천해줘"},
    )
    assert response.status_code == 200
    return response.json()


def _look_url(recommendation_id: str, look_id: int, resource: str) -> str:
    return f"/api/v1/recommendations/{recommendation_id}/looks/{look_id}/{resource}"


def _summary(connection, user_id: int) -> dict:
    return connection.execute(
        text("SELECT feedback_summary FROM user_preferences WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).scalar_one()


def _style_score(summary: dict, style: str) -> int | None:
    scores = {row["style"]: row["score"] for row in summary.get("style_scores", [])}
    return scores.get(style)


def test_new_routes_require_login_and_all_mutations_require_csrf(
    client_and_connection,
):
    client, _ = client_and_connection
    unknown_recommendation_id = str(uuid4())
    feedback_url = _look_url(unknown_recommendation_id, 1, "feedback")
    saved_url = _look_url(unknown_recommendation_id, 1, "saved")

    assert (
        client.get(f"/api/v1/recommendations/{unknown_recommendation_id}/interactions").status_code
        == 401
    )
    assert client.get("/api/v1/saved-outfits").status_code == 401
    assert (
        client.put(
            feedback_url,
            json={"feedback_type": "like"},
        ).status_code
        == 401
    )
    assert client.delete(feedback_url).status_code == 401
    assert client.put(saved_url).status_code == 401
    assert client.delete(saved_url).status_code == 401

    account = _signup_and_login(client)
    recommendation = _recommend(client, str(account["csrf"]))
    available = next(look for look in recommendation["looks"] if look["status"] == "available")
    feedback_url = _look_url(
        recommendation["recommendation_id"],
        available["look_id"],
        "feedback",
    )
    saved_url = _look_url(
        recommendation["recommendation_id"],
        available["look_id"],
        "saved",
    )

    assert (
        client.put(
            feedback_url,
            json={"feedback_type": "like"},
        ).status_code
        == 403
    )
    assert client.delete(feedback_url).status_code == 403
    assert client.put(saved_url).status_code == 403
    assert client.delete(saved_url).status_code == 403


def test_feedback_put_is_idempotent_replaces_opposite_and_delete_removes_score(
    client_and_connection,
):
    client, connection = client_and_connection
    account = _signup_and_login(client)
    recommendation = _recommend(client, str(account["csrf"]))
    recommendation_id = recommendation["recommendation_id"]
    look = recommendation["looks"][0]
    url = _look_url(recommendation_id, look["look_id"], "feedback")
    headers = {"X-CSRF-Token": str(account["csrf"])}

    first = client.put(url, headers=headers, json={"feedback_type": "like"})
    repeated = client.put(url, headers=headers, json={"feedback_type": "like"})

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json() == {
        "recommendation_id": recommendation_id,
        "look_id": look["look_id"],
        "status": "available",
        "feedback": "like",
        "reason": None,
        "saved": False,
    }
    count = connection.execute(
        text("""
            SELECT COUNT(*)
            FROM feedback
            WHERE user_id = :user_id
              AND recommendation_id = :recommendation_id
              AND look_id = :look_id
        """),
        {
            "user_id": account["id"],
            "recommendation_id": UUID(recommendation_id),
            "look_id": look["look_id"],
        },
    ).scalar_one()
    assert count == 1
    assert _style_score(_summary(connection, int(account["id"])), look["style"]) == 1

    changed = client.put(
        url,
        headers=headers,
        json={"feedback_type": "dislike", "reason": "not_my_style"},
    )

    assert changed.status_code == 200
    assert changed.json()["feedback"] == "dislike"
    assert changed.json()["reason"] == "not_my_style"
    stored = (
        connection.execute(
            text("""
                SELECT feedback_type, reason, style_tags, color_tags, fit_tags
                FROM feedback
                WHERE user_id = :user_id
                  AND recommendation_id = :recommendation_id
                  AND look_id = :look_id
            """),
            {
                "user_id": account["id"],
                "recommendation_id": UUID(recommendation_id),
                "look_id": look["look_id"],
            },
        )
        .mappings()
        .one()
    )
    assert dict(stored) == {
        "feedback_type": "DISLIKE",
        "reason": "NOT_MY_STYLE",
        "style_tags": [look["style"]],
        "color_tags": [],
        "fit_tags": [],
    }
    assert _style_score(_summary(connection, int(account["id"])), look["style"]) == -1

    removed = client.delete(url, headers=headers)
    repeated_delete = client.delete(url, headers=headers)

    assert removed.status_code == 200
    assert repeated_delete.status_code == 200
    assert repeated_delete.json()["feedback"] is None
    assert repeated_delete.json()["reason"] is None
    assert (
        connection.execute(
            text("""
                SELECT COUNT(*) FROM feedback
                WHERE user_id = :user_id
                  AND recommendation_id = :recommendation_id
                  AND look_id = :look_id
            """),
            {
                "user_id": account["id"],
                "recommendation_id": UUID(recommendation_id),
                "look_id": look["look_id"],
            },
        ).scalar_one()
        == 0
    )
    assert _style_score(_summary(connection, int(account["id"])), look["style"]) is None


def test_save_is_idempotent_independent_and_uses_exact_server_snapshot(
    client_and_connection,
):
    client, connection = client_and_connection
    account = _signup_and_login(client)
    recommendation = _recommend(client, str(account["csrf"]))
    recommendation_id = recommendation["recommendation_id"]
    look = recommendation["looks"][0]
    headers = {"X-CSRF-Token": str(account["csrf"])}
    feedback_url = _look_url(recommendation_id, look["look_id"], "feedback")
    saved_url = _look_url(recommendation_id, look["look_id"], "saved")

    assert (
        client.put(
            feedback_url,
            headers=headers,
            json={"feedback_type": "like"},
        ).status_code
        == 200
    )
    first = client.put(saved_url, headers=headers)
    repeated = client.put(saved_url, headers=headers)

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json()["feedback"] == "like"
    assert repeated.json()["saved"] is True
    row = (
        connection.execute(
            text("""
                SELECT COUNT(*) OVER () AS row_count, outfit_data
                FROM saved_outfits
                WHERE user_id = :user_id
                  AND recommendation_id = :recommendation_id
                  AND look_id = :look_id
            """),
            {
                "user_id": account["id"],
                "recommendation_id": UUID(recommendation_id),
                "look_id": look["look_id"],
            },
        )
        .mappings()
        .one()
    )
    assert row["row_count"] == 1
    assert row["outfit_data"] == look
    assert _style_score(_summary(connection, int(account["id"])), look["style"]) == 3

    reloaded = client.get(f"/api/v1/recommendations/{recommendation_id}/interactions")
    assert reloaded.status_code == 200
    assert reloaded.json()["recommendation_id"] == recommendation_id
    assert len(reloaded.json()["looks"]) == 5
    assert reloaded.json()["looks"][0] == repeated.json()

    saved_list = client.get("/api/v1/saved-outfits")
    assert saved_list.status_code == 200
    assert len(saved_list.json()) == 1
    assert saved_list.json()[0]["recommendation_id"] == recommendation_id
    assert saved_list.json()[0]["look_id"] == look["look_id"]
    assert saved_list.json()[0]["outfit_data"] == look

    removed_feedback = client.delete(feedback_url, headers=headers)
    assert removed_feedback.status_code == 200
    assert removed_feedback.json()["feedback"] is None
    assert removed_feedback.json()["saved"] is True
    assert _style_score(_summary(connection, int(account["id"])), look["style"]) == 2

    removed_save = client.delete(saved_url, headers=headers)
    repeated_delete = client.delete(saved_url, headers=headers)
    assert removed_save.status_code == 200
    assert repeated_delete.status_code == 200
    assert repeated_delete.json()["saved"] is False
    assert _style_score(_summary(connection, int(account["id"])), look["style"]) is None
    assert client.get("/api/v1/saved-outfits").json() == []


def test_owner_unavailable_range_and_csrf_guards(client_and_connection):
    client, connection = client_and_connection
    first_account = _signup_and_login(client)
    recommendation = _recommend(client, str(first_account["csrf"]))
    recommendation_id = recommendation["recommendation_id"]
    available = recommendation["looks"][0]
    unavailable = next(look for look in recommendation["looks"] if look["status"] == "unavailable")
    available_feedback = _look_url(recommendation_id, available["look_id"], "feedback")
    unavailable_saved = _look_url(recommendation_id, unavailable["look_id"], "saved")

    missing_csrf = client.put(available_feedback, json={"feedback_type": "like"})
    assert missing_csrf.status_code == 403
    assert (
        client.get(f"/api/v1/recommendations/{recommendation_id}/interactions").status_code == 200
    )

    headers = {"X-CSRF-Token": str(first_account["csrf"])}
    unavailable_response = client.put(unavailable_saved, headers=headers)
    assert unavailable_response.status_code == 409
    for look_id in (0, 6):
        response = client.put(
            _look_url(recommendation_id, look_id, "feedback"),
            headers=headers,
            json={"feedback_type": "like"},
        )
        assert response.status_code == 422

    second_account = _signup_and_login(client)
    second_headers = {"X-CSRF-Token": str(second_account["csrf"])}
    assert (
        client.put(
            available_feedback,
            headers=second_headers,
            json={"feedback_type": "like"},
        ).status_code
        == 404
    )
    assert client.put(unavailable_saved, headers=second_headers).status_code == 404
    assert (
        client.get(f"/api/v1/recommendations/{recommendation_id}/interactions").status_code == 404
    )
    assert client.get("/api/v1/saved-outfits").json() == []

    interaction_count = connection.execute(
        text("""
            SELECT
                (SELECT COUNT(*) FROM feedback WHERE recommendation_id = :recommendation_id)
              + (SELECT COUNT(*) FROM saved_outfits WHERE recommendation_id = :recommendation_id)
        """),
        {"recommendation_id": UUID(recommendation_id)},
    ).scalar_one()
    assert interaction_count == 0


def test_dislike_reason_is_optional_but_still_strictly_validated(client_and_connection):
    client, connection = client_and_connection
    account = _signup_and_login(client)
    recommendation = _recommend(client, str(account["csrf"]))
    look = recommendation["looks"][0]
    url = _look_url(recommendation["recommendation_id"], look["look_id"], "feedback")
    headers = {"X-CSRF-Token": str(account["csrf"])}

    response = client.put(
        url,
        headers=headers,
        json={"feedback_type": "dislike"},
    )

    assert response.status_code == 200
    assert response.json()["feedback"] == "dislike"
    assert response.json()["reason"] is None
    stored = (
        connection.execute(
            text("""
                SELECT feedback_type, reason
                FROM feedback
                WHERE user_id = :user_id
                  AND recommendation_id = :recommendation_id
                  AND look_id = :look_id
            """),
            {
                "user_id": account["id"],
                "recommendation_id": UUID(recommendation["recommendation_id"]),
                "look_id": look["look_id"],
            },
        )
        .mappings()
        .one()
    )
    assert dict(stored) == {"feedback_type": "DISLIKE", "reason": None}

    assert (
        client.put(
            url,
            headers=headers,
            json={"feedback_type": "like", "reason": "not_my_style"},
        ).status_code
        == 422
    )
    assert (
        client.put(
            url,
            headers=headers,
            json={"feedback_type": "dislike", "reason": "not_allowed"},
        ).status_code
        == 422
    )


def test_feedback_summary_failure_rolls_back_new_interaction(
    client_and_connection,
    monkeypatch,
):
    client, connection = client_and_connection
    account = _signup_and_login(client)
    recommendation = _recommend(client, str(account["csrf"]))
    look = recommendation["looks"][0]
    url = _look_url(recommendation["recommendation_id"], look["look_id"], "feedback")

    def fail_summary_rebuild(db, user_id):
        del db, user_id
        raise SQLAlchemyError("forced summary rebuild failure")

    monkeypatch.setattr(
        recommendation_interactions,
        "rebuild_feedback_summary",
        fail_summary_rebuild,
    )

    response = client.put(
        url,
        headers={"X-CSRF-Token": str(account["csrf"])},
        json={"feedback_type": "like"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "추천 상태를 저장하는 중 오류가 발생했습니다."}
    assert (
        connection.execute(
            text("""
                SELECT COUNT(*)
                FROM feedback
                WHERE user_id = :user_id
                  AND recommendation_id = :recommendation_id
                  AND look_id = :look_id
            """),
            {
                "user_id": account["id"],
                "recommendation_id": UUID(recommendation["recommendation_id"]),
                "look_id": look["look_id"],
            },
        ).scalar_one()
        == 0
    )

    reloaded = client.get(
        f"/api/v1/recommendations/{recommendation['recommendation_id']}/interactions"
    )
    assert reloaded.status_code == 200
    assert reloaded.json()["looks"][0]["feedback"] is None


def test_feedback_summary_changes_and_then_restores_next_recommendation(
    client_and_connection,
):
    client, connection = client_and_connection
    account = _signup_and_login(client)
    headers = {"X-CSRF-Token": str(account["csrf"])}
    original = _recommend(client, str(account["csrf"]))
    default_style = original["looks"][0]["style"]
    liked_look = original["looks"][1]
    feedback_url = _look_url(
        original["recommendation_id"],
        liked_look["look_id"],
        "feedback",
    )

    liked = client.put(
        feedback_url,
        headers=headers,
        json={"feedback_type": "like"},
    )

    assert liked.status_code == 200
    summary = _summary(connection, int(account["id"]))
    assert summary["positive_styles"] == [liked_look["style"]]
    assert _style_score(summary, liked_look["style"]) == 1

    personalized = _recommend(client, str(account["csrf"]))
    assert personalized["looks"][0]["style"] == liked_look["style"]

    removed = client.delete(feedback_url, headers=headers)

    assert removed.status_code == 200
    assert _summary(connection, int(account["id"])) == {}
    restored = _recommend(client, str(account["csrf"]))
    assert restored["looks"][0]["style"] == default_style
    assert restored["looks"][0]["style"] != liked_look["style"]


def test_feedback_summary_uses_exact_style_as_final_tie_break(client_and_connection):
    client, connection = client_and_connection
    account = _signup_and_login(client)
    headers = {"X-CSRF-Token": str(account["csrf"])}
    recommendation = _recommend(client, str(account["csrf"]))
    recommendation_id = UUID(recommendation["recommendation_id"])
    connection.execute(
        text("""
            UPDATE recommendation_runs
            SET looks = jsonb_set(
                jsonb_set(looks, '{0,style}', to_jsonb('Casual'::TEXT)),
                '{1,style}',
                to_jsonb('casual'::TEXT)
            )
            WHERE id = :recommendation_id
              AND user_id = :user_id
        """),
        {
            "recommendation_id": recommendation_id,
            "user_id": account["id"],
        },
    )

    for look_id in (1, 2):
        response = client.put(
            _look_url(str(recommendation_id), look_id, "feedback"),
            headers=headers,
            json={"feedback_type": "like"},
        )
        assert response.status_code == 200

    summary = _summary(connection, int(account["id"]))
    assert summary["positive_styles"] == ["Casual", "casual"]


def test_legacy_unlinked_rows_are_preserved_and_excluded_from_summary(
    client_and_connection,
):
    client, connection = client_and_connection
    account = _signup_and_login(client)
    recommendation = _recommend(client, str(account["csrf"]))
    look = recommendation["looks"][0]
    headers = {"X-CSRF-Token": str(account["csrf"])}
    feedback_url = _look_url(
        recommendation["recommendation_id"],
        look["look_id"],
        "feedback",
    )

    legacy_feedback_id = connection.execute(
        text("""
            INSERT INTO feedback (
                user_id,
                feedback_type,
                reason,
                style_tags,
                color_tags,
                fit_tags
            )
            VALUES (
                :user_id,
                'LIKE',
                NULL,
                ARRAY['legacy-feedback-style']::TEXT[],
                '{}'::TEXT[],
                '{}'::TEXT[]
            )
            RETURNING id
        """),
        {"user_id": account["id"]},
    ).scalar_one()
    legacy_saved_id = connection.execute(
        text("""
            INSERT INTO saved_outfits (
                user_id,
                title,
                outfit_data
            )
            VALUES (
                :user_id,
                'legacy saved outfit',
                CAST(:outfit_data AS JSONB)
            )
            RETURNING id
        """),
        {
            "user_id": account["id"],
            "outfit_data": '{"style":"legacy-saved-style"}',
        },
    ).scalar_one()

    stored_legacy = (
        connection.execute(
            text("""
                SELECT
                    (SELECT recommendation_id FROM feedback WHERE id = :feedback_id)
                        AS feedback_recommendation_id,
                    (SELECT recommendation_id FROM saved_outfits WHERE id = :saved_id)
                        AS saved_recommendation_id
            """),
            {
                "feedback_id": legacy_feedback_id,
                "saved_id": legacy_saved_id,
            },
        )
        .mappings()
        .one()
    )
    assert dict(stored_legacy) == {
        "feedback_recommendation_id": None,
        "saved_recommendation_id": None,
    }

    linked = client.put(
        feedback_url,
        headers=headers,
        json={"feedback_type": "like"},
    )
    assert linked.status_code == 200
    summary = _summary(connection, int(account["id"]))
    assert _style_score(summary, look["style"]) == 1
    assert _style_score(summary, "legacy-feedback-style") is None
    assert _style_score(summary, "legacy-saved-style") is None

    removed = client.delete(feedback_url, headers=headers)
    assert removed.status_code == 200
    assert _summary(connection, int(account["id"])) == {}
    preserved_count = connection.execute(
        text("""
            SELECT
                (SELECT COUNT(*) FROM feedback
                 WHERE id = :feedback_id AND recommendation_id IS NULL)
              + (SELECT COUNT(*) FROM saved_outfits
                 WHERE id = :saved_id AND recommendation_id IS NULL)
        """),
        {
            "feedback_id": legacy_feedback_id,
            "saved_id": legacy_saved_id,
        },
    ).scalar_one()
    assert preserved_count == 2
