from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.core.database import engine, get_db
from app.main import app
from app.services import wardrobe_images


@pytest.fixture
def client(tmp_path, monkeypatch):
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
                yield test_client
        finally:
            app.dependency_overrides.pop(get_db, None)
            transaction.rollback()


def _signup_and_login(client: TestClient) -> dict[str, str | int]:
    email = f"agent-{uuid4().hex}@example.com"
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


def test_agent_recommendation_uses_authenticated_context_and_wardrobe(client):
    account = _signup_and_login(client)
    headers = {"X-CSRF-Token": str(account["csrf"])}
    assert (
        client.patch(
            "/api/v1/preferences/me",
            headers=headers,
            json={
                "preferred_styles": ["minimal"],
                "preferred_colors": ["navy"],
                "disliked_colors": ["red"],
                "preferred_fit": "regular",
            },
        ).status_code
        == 200
    )

    items = [
        {"category": "top", "type": "shirt", "color": "white", "fit": "regular"},
        {"category": "bottom", "type": "slacks", "color": "black", "fit": "regular"},
        {"category": "shoes", "type": "sneakers", "color": "white", "fit": "regular"},
    ]
    item_ids = {}
    for item in items:
        response = client.post(
            "/api/v1/wardrobe",
            headers=headers,
            json={**item, "seasons": ["spring", "fall"]},
        )
        assert response.status_code == 201
        item_ids[item["category"]] = response.json()["item_id"]

    photo = BytesIO()
    Image.new("RGB", (4, 4), "white").save(photo, format="PNG")
    photo_id = item_ids["top"]
    upload = client.post(
        f"/api/v1/wardrobe/{photo_id}/image",
        headers=headers,
        files={"file": ("shirt.png", photo.getvalue(), "image/png")},
    )
    assert upload.status_code == 200

    response = client.post(
        "/api/v1/agent/recommend",
        headers=headers,
        json={"message": "내 옷으로 출근 코디를 추천해줘"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "fashion_recommendation"
    assert body["action"] == "generate_five_looks"
    assert body["called_tools"] == ["get_user_context", "get_wardrobe"]
    assert len(body["looks"]) == 5
    assert [look["role"] for look in body["looks"]] == [
        "preference_best",
        "preference_alternative",
        "exploration",
        "wardrobe_best",
        "wardrobe_alternative",
    ]
    assert all(item["item_id"] is None for look in body["looks"][:3] for item in look["items"])
    returned_ids = {item["item_id"] for look in body["looks"][3:] for item in look["items"]}
    assert returned_ids == set(item_ids.values())
    assert all(item["image_url"] is None for look in body["looks"][:3] for item in look["items"])
    owned_items = {item["item_id"]: item for item in body["looks"][3]["items"]}
    assert owned_items[photo_id]["image_url"] == f"/api/v1/wardrobe/{photo_id}/image"
    assert all(
        item["image_url"] is None for item_id, item in owned_items.items() if item_id != photo_id
    )
    assert body["looks"][4]["status"] == "unavailable"
    assert body["looks"][4]["style"] is None
    assert body["looks"][4]["items"] == []


def test_agent_rejects_missing_tool_arguments_before_execution(client):
    account = _signup_and_login(client)
    headers = {"X-CSRF-Token": str(account["csrf"])}

    response = client.post(
        "/api/v1/agent/recommend",
        headers=headers,
        json={
            "message": "내일 날씨에 맞는 코디를 추천해줘",
            "date": "2026-11-04",
            "time": "08:30",
        },
    )

    assert response.status_code == 422
    assert "get_weather" in response.json()["detail"]


def test_agent_requires_login_and_csrf(client):
    assert (
        client.post(
            "/api/v1/agent/recommend",
            json={"message": "코디 추천해줘"},
        ).status_code
        == 401
    )

    _signup_and_login(client)
    assert (
        client.post(
            "/api/v1/agent/recommend",
            json={"message": "코디 추천해줘"},
        ).status_code
        == 403
    )
