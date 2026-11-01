"""테스트는 실제 PostgreSQL 7개 스키마가 준비된 환경에서 실행한다."""

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
    # 실제 로컬 업로드 폴더와 테스트 업로드를 격리한다.
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


def login(client):
    password = "TestPassword123!"
    email = f"wardrobe-{uuid4().hex}@example.com"
    assert client.post(
        "/api/v1/auth/signup", json={"email": email, "password": password}
    ).status_code == 201
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"id": response.json()["id"], "email": email, "password": password,
            "X-CSRF-Token": response.json()["csrf_token"]}


PAYLOAD = {
    "category": "top",
    "type": "shirt",
    "color": "white",
    "fit": "regular",
    "seasons": ["spring", "summer"],
}


def test_wardrobe_crud_csrf_and_owner_isolation(client):
    assert client.get("/api/v1/wardrobe").status_code == 401
    assert client.post("/api/v1/wardrobe", json=PAYLOAD).status_code == 401

    first = login(client)
    headers = {"X-CSRF-Token": first["X-CSRF-Token"]}

    assert client.post("/api/v1/wardrobe", json=PAYLOAD).status_code == 403
    assert client.post(
        "/api/v1/wardrobe", json={**PAYLOAD, "category": "   "}, headers=headers
    ).status_code == 422

    created = client.post("/api/v1/wardrobe", json=PAYLOAD, headers=headers)
    assert created.status_code == 201
    item = created.json()
    item_id = item["item_id"]
    assert item["type"] == "shirt"
    assert item["seasons"] == ["spring", "summer"]

    assert len(client.get("/api/v1/wardrobe").json()) == 1
    assert client.get(f"/api/v1/wardrobe/{item_id}").json()["color"] == "white"
    context = client.get("/api/v1/wardrobe/agent-context")
    assert context.status_code == 200
    assert context.json()[0]["item_id"] == item_id

    assert client.patch(f"/api/v1/wardrobe/{item_id}", json={"color": "black"}).status_code == 403
    update = client.patch(
        f"/api/v1/wardrobe/{item_id}", json={"color": "black"}, headers=headers
    )
    assert update.status_code == 200
    assert update.json()["color"] == "black"
    assert client.patch(
        f"/api/v1/wardrobe/{item_id}", json={"color": None}, headers=headers
    ).status_code == 422

    second = login(client)
    second_headers = {"X-CSRF-Token": second["X-CSRF-Token"]}
    assert client.get("/api/v1/wardrobe").json() == []
    assert client.get(f"/api/v1/wardrobe/{item_id}").status_code == 404
    assert client.delete(f"/api/v1/wardrobe/{item_id}", headers=second_headers).status_code == 404

    relogin = client.post(
        "/api/v1/auth/login",
        json={"email": first["email"], "password": first["password"]},
    )
    assert relogin.status_code == 200
    own_headers = {"X-CSRF-Token": relogin.json()["csrf_token"]}
    assert client.delete(f"/api/v1/wardrobe/{item_id}", headers=own_headers).status_code == 204
    assert client.get(f"/api/v1/wardrobe/{item_id}").status_code == 404


def test_image_upload_and_deletion(client):
    account = login(client)
    headers = {"X-CSRF-Token": account["X-CSRF-Token"]}
    created = client.post("/api/v1/wardrobe", json=PAYLOAD, headers=headers)
    assert created.status_code == 201
    item_id = created.json()["item_id"]

    assert client.post(
        f"/api/v1/wardrobe/{item_id}/image",
        files={"file": ("fake.exe", b"not an image", "application/octet-stream")},
        headers=headers,
    ).status_code == 422

    buffer = BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    valid = buffer.getvalue()

    assert client.post(
        f"/api/v1/wardrobe/{item_id}/image",
        files={"file": ("shirt.png", valid, "image/png")},
    ).status_code == 403

    uploaded = client.post(
        f"/api/v1/wardrobe/{item_id}/image",
        files={"file": ("shirt.png", valid, "image/png")},
        headers=headers,
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["image_url"] == f"/api/v1/wardrobe/{item_id}/image"

    image = client.get(f"/api/v1/wardrobe/{item_id}/image")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
    assert image.content == valid

    other = login(client)
    assert client.get(f"/api/v1/wardrobe/{item_id}/image").status_code == 404
    assert client.delete(
        f"/api/v1/wardrobe/{item_id}/image", headers={"X-CSRF-Token": other["X-CSRF-Token"]}
    ).status_code == 404
    relogin = client.post(
        "/api/v1/auth/login",
        json={"email": account["email"], "password": account["password"]},
    )
    assert relogin.status_code == 200
    own_headers = {"X-CSRF-Token": relogin.json()["csrf_token"]}
    assert (
        client.delete(f"/api/v1/wardrobe/{item_id}/image", headers=own_headers).status_code
        == 204
    )
    assert client.get(f"/api/v1/wardrobe/{item_id}/image").status_code == 404
    assert client.get(f"/api/v1/wardrobe/{item_id}").json()["image_url"] is None


def test_image_size_limit_and_account_cleanup(client):
    account = login(client)
    headers = {"X-CSRF-Token": account["X-CSRF-Token"]}
    item = client.post("/api/v1/wardrobe", json=PAYLOAD, headers=headers).json()["item_id"]

    oversized = b"x" * (5 * 1024 * 1024 + 1)
    assert client.post(
        f"/api/v1/wardrobe/{item}/image",
        files={"file": ("large.png", oversized, "image/png")},
        headers=headers,
    ).status_code == 413

    assert client.delete(f"/api/v1/wardrobe/{item}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/wardrobe/{item}").status_code == 404


def test_account_deletion_removes_image_files(client):
    account = login(client)
    headers = {"X-CSRF-Token": account["X-CSRF-Token"]}
    item = client.post("/api/v1/wardrobe", json=PAYLOAD, headers=headers).json()["item_id"]
    stream = BytesIO()
    Image.new("RGB", (2, 2), "white").save(stream, format="PNG")
    result = client.post(
        f"/api/v1/wardrobe/{item}/image",
        files={"file": ("image.png", stream.getvalue(), "image/png")},
        headers=headers,
    )
    assert result.status_code == 200
    assert (wardrobe_images.MEDIA_ROOT / str(account["id"])).is_dir()

    deleted = client.request(
        "DELETE", "/api/v1/auth/account",
        json={"password": account["password"]}, headers=headers,
    )
    assert deleted.status_code == 204
    assert not (wardrobe_images.MEDIA_ROOT / str(account["id"])).exists()
    assert client.get("/api/v1/wardrobe").status_code == 401





def test_wrong_password_preserves_account_and_images(client):
    # 1. 로그인
    account = login(client)

    headers = {
        "X-CSRF-Token": account["X-CSRF-Token"]
    }

    # 2. 옷 등록
    response = client.post(
        "/api/v1/wardrobe",
        json=PAYLOAD,
        headers=headers,
    )
    assert response.status_code in (200, 201), response.text

    item_id = response.json()["item_id"]

    # 3. 이미지 업로드
    stream = BytesIO()
    Image.new("RGB", (2, 2), "white").save(
        stream,
        format="PNG",
    )

    upload = client.post(
        f"/api/v1/wardrobe/{item_id}/image",
        files={
            "file": (
                "image.png",
                stream.getvalue(),
                "image/png",
            )
        },
        headers=headers,
    )
    assert upload.status_code == 200, upload.text

    # 4. 실제 이미지 파일 저장 확인
    image_dir = (
        wardrobe_images.MEDIA_ROOT / str(account["id"])
    )

    assert image_dir.is_dir()

    saved_files = list(image_dir.iterdir())
    assert saved_files

    # 5. 잘못된 비밀번호로 회원 탈퇴 시도
    wrong = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json={
            "password": "DefinitelyWrongPassword123!"
        },
        headers=headers,
    )

    assert wrong.status_code == 403

    # 6. 사용자 DB 데이터 및 세션 유지 확인
    me = client.get("/api/v1/auth/me")

    assert me.status_code == 200
    assert me.json()["id"] == account["id"]

    # 7. 이미지 파일 유지 확인
    assert image_dir.is_dir()
    assert all(path.is_file() for path in saved_files)
