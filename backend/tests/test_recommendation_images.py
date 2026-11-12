"""추천 원본과 분리된 LOOK별 이미지 조회 통합 테스트."""

import threading
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1 import recommendation_images
from app.api.v1.recommendation_images import get_shopping_image_service
from app.core.database import engine, get_db
from app.main import app
from app.services import wardrobe_images
from app.services.shopping_images import ShoppingImageResult


class FakeShoppingImageService:
    def __init__(
        self,
        results: dict[tuple[str, str], ShoppingImageResult] | None = None,
    ):
        self.results = results or {}
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def resolve(self, name: str, slot: str) -> ShoppingImageResult:
        with self._lock:
            self.calls.append((name, slot))
        if result := self.results.get((name, slot)):
            return result
        return ShoppingImageResult(
            status="found",
            url="https://images.example.test/item.webp",
            title=f"{name} 상품",
            source_name="테스트 판매처",
            source_url="https://shop.example.test/item",
        )


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
            app.dependency_overrides.pop(get_shopping_image_service, None)
            transaction.rollback()


def _signup_and_login(client: TestClient) -> dict[str, str | int]:
    password = "TestPassword123!"
    email = f"images-{uuid4().hex}@example.com"
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


def _recommend(client: TestClient, csrf: str, message: str = "출근 코디를 추천해줘") -> dict:
    response = client.post(
        "/api/v1/agent/recommend",
        headers={"X-CSRF-Token": csrf},
        json={"message": message},
    )
    assert response.status_code == 200
    return response.json()


def _images_url(recommendation_id: str, look_id: int) -> str:
    return f"/api/v1/recommendations/{recommendation_id}/looks/{look_id}/images"


def test_generic_look_requires_login_but_not_csrf_and_uses_stored_items(
    client_and_connection,
):
    client, _ = client_and_connection
    fake = FakeShoppingImageService()
    app.dependency_overrides[get_shopping_image_service] = lambda: fake
    unknown_url = _images_url(str(uuid4()), 1)

    assert client.get(unknown_url).status_code == 401

    account = _signup_and_login(client)
    recommendation = _recommend(client, str(account["csrf"]))
    look = recommendation["looks"][0]
    response = client.get(_images_url(recommendation["recommendation_id"], look["look_id"]))

    assert response.status_code == 200
    body = response.json()
    assert body["look_status"] == "available"
    assert body["resolution_status"] == "complete"
    assert sorted(fake.calls) == sorted((item["name"], item["slot"]) for item in look["items"])
    assert [(item["slot"], item["name"]) for item in body["items"]] == [
        (item["slot"], item["name"]) for item in look["items"]
    ]
    assert all(item["origin"] == "google_shopping" for item in body["items"])
    assert all(item["image"]["rights_status"] == "unverified" for item in body["items"])


def test_partial_and_disabled_results_keep_item_order(client_and_connection):
    client, _ = client_and_connection
    account = _signup_and_login(client)
    recommendation = _recommend(client, str(account["csrf"]))
    look = recommendation["looks"][0]
    result_sequence = [
        ShoppingImageResult(
            status="found",
            url="https://images.example.test/top.webp",
            title="상의",
        ),
        ShoppingImageResult(status="not_found"),
        ShoppingImageResult(status="provider_unavailable"),
    ] + [ShoppingImageResult(status="provider_disabled")] * max(0, len(look["items"]) - 3)
    fake = FakeShoppingImageService(
        dict(
            zip(
                ((item["name"], item["slot"]) for item in look["items"]),
                result_sequence,
                strict=True,
            )
        )
    )
    app.dependency_overrides[get_shopping_image_service] = lambda: fake

    response = client.get(_images_url(recommendation["recommendation_id"], look["look_id"]))

    assert response.status_code == 200
    body = response.json()
    assert body["resolution_status"] == "partial"
    assert [item["status"] for item in body["items"]][:3] == [
        "found",
        "not_found",
        "provider_unavailable",
    ]
    assert body["items"][0]["image"] is not None
    assert all(item["image"] is None for item in body["items"][1:])
    assert [item["slot"] for item in body["items"]] == [item["slot"] for item in look["items"]]


def test_unavailable_look_and_unknown_owner_never_call_provider(client_and_connection):
    client, _ = client_and_connection
    fake = FakeShoppingImageService()
    app.dependency_overrides[get_shopping_image_service] = lambda: fake
    first = _signup_and_login(client)
    recommendation = _recommend(client, str(first["csrf"]), "내 옷만으로 추천해줘")

    unavailable = client.get(_images_url(recommendation["recommendation_id"], 1))
    assert unavailable.status_code == 200
    assert unavailable.json()["resolution_status"] == "not_applicable"
    assert unavailable.json()["items"] == []

    assert client.get(_images_url(str(uuid4()), 1)).status_code == 404
    _signup_and_login(client)
    assert client.get(_images_url(recommendation["recommendation_id"], 1)).status_code == 404
    assert fake.calls == []


def test_wardrobe_look_uses_only_owned_uploads(client_and_connection):
    client, _ = client_and_connection
    fake = FakeShoppingImageService()
    app.dependency_overrides[get_shopping_image_service] = lambda: fake
    account = _signup_and_login(client)
    headers = {"X-CSRF-Token": str(account["csrf"])}
    item_ids: dict[str, int] = {}
    for category, item_type in (
        ("top", "shirt"),
        ("bottom", "slacks"),
        ("shoes", "sneakers"),
    ):
        created = client.post(
            "/api/v1/wardrobe",
            headers=headers,
            json={
                "category": category,
                "type": item_type,
                "color": "black",
                "fit": "regular",
                "seasons": ["spring"],
            },
        )
        assert created.status_code == 201
        item_ids[category] = created.json()["item_id"]

    image = BytesIO()
    Image.new("RGB", (3, 3), "white").save(image, format="PNG")
    uploaded = client.post(
        f"/api/v1/wardrobe/{item_ids['top']}/image",
        headers=headers,
        files={"file": ("shirt.png", image.getvalue(), "image/png")},
    )
    assert uploaded.status_code == 200

    recommendation = _recommend(client, str(account["csrf"]))
    response = client.get(_images_url(recommendation["recommendation_id"], 4))

    assert response.status_code == 200
    body = response.json()
    assert body["look_status"] == "available"
    assert body["resolution_status"] == "partial"
    assert fake.calls == []
    assert all(item["origin"] == "wardrobe" for item in body["items"])
    by_slot = {item["slot"]: item for item in body["items"]}
    assert by_slot["top"]["status"] == "found"
    expected_top_url = f"/api/v1/wardrobe/{item_ids['top']}/image"
    assert by_slot["top"]["image"]["url"] == expected_top_url
    assert by_slot["top"]["image"]["rights_status"] == "user_provided"
    assert by_slot["bottom"]["status"] == "not_found"
    assert by_slot["shoes"]["status"] == "not_found"


def test_lookup_does_not_mutate_recommendation_or_saved_snapshot(client_and_connection):
    client, connection = client_and_connection
    fake = FakeShoppingImageService()
    app.dependency_overrides[get_shopping_image_service] = lambda: fake
    account = _signup_and_login(client)
    headers = {"X-CSRF-Token": str(account["csrf"])}
    recommendation = _recommend(client, str(account["csrf"]))
    recommendation_id = UUID(recommendation["recommendation_id"])
    look = recommendation["looks"][0]
    saved = client.put(
        f"/api/v1/recommendations/{recommendation_id}/looks/{look['look_id']}/saved",
        headers=headers,
    )
    assert saved.status_code == 200

    before_looks = connection.execute(
        text("SELECT looks FROM recommendation_runs WHERE id = :id"),
        {"id": recommendation_id},
    ).scalar_one()
    before_outfit = connection.execute(
        text("SELECT outfit_data FROM saved_outfits WHERE recommendation_id = :id"),
        {"id": recommendation_id},
    ).scalar_one()

    response = client.get(_images_url(str(recommendation_id), look["look_id"]))
    assert response.status_code == 200

    after_looks = connection.execute(
        text("SELECT looks FROM recommendation_runs WHERE id = :id"),
        {"id": recommendation_id},
    ).scalar_one()
    after_outfit = connection.execute(
        text("SELECT outfit_data FROM saved_outfits WHERE recommendation_id = :id"),
        {"id": recommendation_id},
    ).scalar_one()
    assert after_looks == before_looks == recommendation["looks"]
    assert after_outfit == before_outfit == look


def test_path_validation_happens_before_provider_call(client_and_connection):
    client, _ = client_and_connection
    fake = FakeShoppingImageService()
    app.dependency_overrides[get_shopping_image_service] = lambda: fake
    account = _signup_and_login(client)
    recommendation = _recommend(client, str(account["csrf"]))
    recommendation_id = recommendation["recommendation_id"]

    assert client.get(_images_url(recommendation_id, 0)).status_code == 422
    assert client.get(_images_url(recommendation_id, 6)).status_code == 422
    assert client.get(_images_url("not-a-uuid", 1)).status_code == 422
    assert fake.calls == []


def test_db_transaction_is_released_before_external_lookup(
    client_and_connection,
    monkeypatch,
):
    client, _ = client_and_connection
    account = _signup_and_login(client)
    recommendation = _recommend(client, str(account["csrf"]))
    observed_sessions: list[Session] = []
    original_load = recommendation_images.load_owned_looks

    def capture_session(db: Session, user_id: int, recommendation_id: UUID):
        observed_sessions.append(db)
        return original_load(db, user_id, recommendation_id)

    class TransactionCheckingService(FakeShoppingImageService):
        def resolve(self, name: str, slot: str) -> ShoppingImageResult:
            assert observed_sessions
            assert not observed_sessions[-1].in_transaction()
            return super().resolve(name, slot)

    monkeypatch.setattr(recommendation_images, "load_owned_looks", capture_session)
    fake = TransactionCheckingService()
    app.dependency_overrides[get_shopping_image_service] = lambda: fake

    response = client.get(_images_url(recommendation["recommendation_id"], 1))

    assert response.status_code == 200
    assert fake.calls
