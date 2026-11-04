"""Use an explicit test database; never fall back to the development database."""

import os

import pytest

os.environ.setdefault("SESSION_SECRET_KEY", "test-only-session-key-" + "x" * 48)
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]


@pytest.fixture(autouse=True)
def require_explicit_test_database(monkeypatch):
    if not os.getenv("TEST_DATABASE_URL"):
        from app.core.database import engine

        def skip_database_connection(*args, **kwargs):
            pytest.skip("Database integration tests require TEST_DATABASE_URL")

        monkeypatch.setattr(engine, "connect", skip_database_connection)
