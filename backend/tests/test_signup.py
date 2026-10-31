from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import engine, get_db
from app.main import app


@pytest.fixture
def test_client():
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
            with TestClient(app) as client:
                yield client, connection
        finally:
            app.dependency_overrides.pop(get_db, None)
            transaction.rollback()


def test_signup_and_duplicate(test_client):
    client, connection = test_client
    email = f"test-{uuid4().hex}@example.com"
    password = "TestPassword123!"

    response = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password},
    )

    assert response.status_code == 201
    assert response.json()["email"] == email
    assert "password_hash" not in response.json()

    stored_hash = connection.execute(
        text("SELECT password_hash FROM users WHERE email = :email"),
        {"email": email},
    ).scalar_one()

    assert stored_hash != password
    assert PasswordHash.recommended().verify(password, stored_hash)

    duplicate = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password},
    )

    assert duplicate.status_code == 409


def test_invalid_email(test_client):
    client, _ = test_client

    response = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "invalid-email",
            "password": "TestPassword123!",
        },
    )

    assert response.status_code == 422
