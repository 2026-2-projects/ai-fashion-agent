from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
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
                yield test_client
        finally:
            app.dependency_overrides.pop(get_db, None)
            transaction.rollback()


def test_login_session_logout(client):
    email = f"test-{uuid4().hex}@example.com"
    password = "TestPassword123!"

    # 로그인 전에는 접근 불가
    assert client.get("/api/v1/auth/me").status_code == 401

    # 테스트 사용자 생성
    signup = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password},
    )
    assert signup.status_code == 201

    # 잘못된 비밀번호
    failed = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WrongPassword"},
    )
    assert failed.status_code == 401

    # 정상 로그인
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200

    csrf_token = login.json()["csrf_token"]
    assert client.cookies.get("fashion_session")

    # 로그인 유지
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == email

    # CSRF 토큰 없으면 로그아웃 차단
    denied = client.post("/api/v1/auth/logout")
    assert denied.status_code == 403

    # 정상 로그아웃
    logout = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert logout.status_code == 204

    # 로그아웃 후 접근 차단
    assert client.get("/api/v1/auth/me").status_code == 401
