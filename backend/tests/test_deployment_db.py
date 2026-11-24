import psycopg
import pytest
from fastapi.testclient import TestClient

from app import init_db
from app.api.v1 import health
from app.core.database_url import postgres_url
from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_database_url_preserves_encoded_components_and_driver(scheme):
    location = "user:a%2Fb%40c@[::1]:5432/db?sslmode=require&options=-c%20timezone%3DUTC"
    assert postgres_url(f"{scheme}://{location}") == f"postgresql://{location}"
    assert postgres_url(f"{scheme}://{location}", sqlalchemy=True) == (
        f"postgresql+psycopg://{location}"
    )


def test_initializer_requires_explicit_target(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert init_db.main() == 2
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic:hidden@localhost/")
    assert init_db.main() == 2
    assert "hidden" not in capsys.readouterr().err


def test_missing_schema_does_not_break_liveness(monkeypatch):
    async def missing_schema():
        return False
    monkeypatch.setattr(health, "_schema_ready", missing_schema)
    assert client.get("/api/v1/health/ready").status_code == 503
    assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_readiness_sanitizes_connection_failure(monkeypatch):
    async def unreachable():
        raise psycopg.OperationalError("synthetic secret")
    monkeypatch.setattr(health, "_schema_ready", unreachable)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is not ready"}
