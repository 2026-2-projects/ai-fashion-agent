import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

os.environ.setdefault("SESSION_SECRET_KEY", "test-session-key-" + "x" * 48)
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")

from app.api.v1.calendar import get_calendar_service  # noqa: E402
from app.core import config  # noqa: E402
from app.core.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.calendar import CalendarService  # noqa: E402


@pytest.fixture(scope="session")
def test_engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    admin = create_engine(url)
    schema = "test_calendar_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        ddl = (Path(__file__).parents[1] / "sql/001_calendar.sql").read_text()
        with engine.connect() as connection:
            connection.exec_driver_sql(ddl)
            connection.commit()
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def db(test_engine):
    with test_engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(
        config, "GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/api/v1/calendar/callback"
    )
    monkeypatch.setattr(config, "GOOGLE_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture
def upstream():
    requests = []
    responses = []

    def handle(request):
        requests.append(request)
        if not responses:
            raise AssertionError("Unexpected Google request")
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        yield http, requests, responses


@pytest.fixture
def client(db, settings, upstream):
    http, _, _ = upstream
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_calendar_service] = lambda: CalendarService(db, http)
    try:
        with TestClient(app, base_url="http://127.0.0.1:8000") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
