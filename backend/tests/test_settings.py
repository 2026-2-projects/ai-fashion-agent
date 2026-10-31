from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import engine, get_db
from app.main import app


@pytest.fixture
def client():
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


def signup_and_login(client):
    email = f"test-{uuid4().hex}@example.com"
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
        "X-CSRF-Token": login.json()["csrf_token"],
    }


def test_profile_and_preferences(client):
    client, _ = client
    # 인증되지 않은 사용자 접근 차단
    assert client.get("/api/v1/profile/me").status_code == 401
    assert client.get("/api/v1/preferences/me").status_code == 401

    first = signup_and_login(client)
    headers = {"X-CSRF-Token": first["X-CSRF-Token"]}

    # 최초 조회
    profile = client.get("/api/v1/profile/me")
    assert profile.status_code == 200
    assert profile.json()["height_cm"] is None

    # CSRF 검증
    denied = client.patch(
        "/api/v1/profile/me",
        json={"height_cm": 175},
    )
    assert denied.status_code == 403

    # 프로필 저장
    updated = client.patch(
        "/api/v1/profile/me",
        headers=headers,
        json={
            "gender": "male",
            "age_group": "20s",
            "height_cm": 175,
            "body_type": "slim",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["height_cm"] == 175

    # 패션 취향 저장
    preferences = client.patch(
        "/api/v1/preferences/me",
        headers=headers,
        json={
            "preferred_styles": ["casual", "minimal"],
            "preferred_colors": ["black", "navy"],
            "disliked_colors": ["red"],
            "preferred_fit": "regular",
        },
    )
    assert preferences.status_code == 200

    fetched = client.get("/api/v1/preferences/me")
    assert fetched.json()["preferred_fit"] == "regular"

    # 잘못된 키 입력 거부
    invalid = client.patch(
        "/api/v1/profile/me",
        headers=headers,
        json={"height_cm": -10},
    )
    assert invalid.status_code == 422

    # 다른 사용자로 로그인한 뒤 데이터 격리 확인
    second = signup_and_login(client)
    assert second["id"] != first["id"]

    other_profile = client.get("/api/v1/profile/me")
    assert other_profile.status_code == 200
    assert other_profile.json()["height_cm"] is None

    other_preferences = client.get("/api/v1/preferences/me")
    assert other_preferences.json()["preferred_styles"] == []


def test_delete_account(client):
    client, connection = client

    account = signup_and_login(client)
    user_id = account["id"]
    headers = {"X-CSRF-Token": account["X-CSRF-Token"]}

    # 연관 데이터 생성
    profile = client.patch(
        "/api/v1/profile/me",
        headers=headers,
        json={"height_cm": 175},
    )
    assert profile.status_code == 200

    preferences = client.patch(
        "/api/v1/preferences/me",
        headers=headers,
        json={"preferred_fit": "regular"},
    )
    assert preferences.status_code == 200

    # 잘못된 비밀번호로 삭제 시도
    wrong = client.request(
        "DELETE",
        "/api/v1/auth/account",
        headers=headers,
        json={"password": "WrongPassword123!"},
    )
    assert wrong.status_code == 403

    # 올바르지 않은 CSRF 토큰
    invalid_csrf = client.request(
        "DELETE",
        "/api/v1/auth/account",
        headers={"X-CSRF-Token": "invalid"},
        json={"password": "TestPassword123!"},
    )
    assert invalid_csrf.status_code == 403

    # 정상 회원 탈퇴
    deleted = client.request(
        "DELETE",
        "/api/v1/auth/account",
        headers=headers,
        json={"password": "TestPassword123!"},
    )
    assert deleted.status_code == 204

    # 로그아웃 상태 확인
    assert client.get("/api/v1/auth/me").status_code == 401

    # 사용자 및 연관 데이터 삭제 확인
    tables = [
        "users",
        "user_profiles",
        "user_preferences",
        "wardrobe_items",
        "feedback",
        "saved_outfits",
        "google_calendar_connections",
    ]

    for table in tables:
        count = connection.execute(
            text(
                f"SELECT COUNT(*) FROM {table} "
                "WHERE " + ("id = :user_id" if table == "users" else "user_id = :user_id")
            ),
            {"user_id": user_id},
        ).scalar_one()

        assert count == 0, f"{table}에 삭제되지 않은 데이터가 있습니다."
