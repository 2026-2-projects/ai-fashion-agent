import asyncio

import psycopg
from fastapi import APIRouter, HTTPException

from app.core.config import DATABASE_URL
from app.core.database_url import postgres_url

router = APIRouter(prefix="/health", tags=["Health"])
REQUIRED_TABLES = (
    "users", "user_profiles", "user_preferences", "wardrobe_items",
    "google_calendar_connections", "recommendation_runs", "feedback", "saved_outfits",
)
_READINESS_SLOTS = asyncio.Semaphore(2)


@router.get("")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


async def _schema_ready() -> bool:
    # A probe must return promptly even when ordinary requests hold all pooled connections.
    async with _READINESS_SLOTS:
        async with await psycopg.AsyncConnection.connect(
            postgres_url(DATABASE_URL), connect_timeout=3
        ) as connection:
            await connection.execute("SET LOCAL statement_timeout = '2s'")
            cursor = await connection.execute(
                """
                SELECT count(*)
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
                  AND c.relname = ANY(%s::text[])
                  AND pg_catalog.pg_table_is_visible(c.oid)
                  AND pg_catalog.has_table_privilege(c.oid, 'SELECT')
                """,
                (list(REQUIRED_TABLES),),
            )
            row = await cursor.fetchone()
            return row == (len(REQUIRED_TABLES),)


@router.get("/ready", responses={503: {"description": "Database or schema is unavailable"}})
async def readiness_check() -> dict[str, str]:
    try:
        async with asyncio.timeout(5):
            if await _schema_ready():
                return {"status": "ready"}
    except (TimeoutError, OSError, psycopg.Error):
        pass
    raise HTTPException(status_code=503, detail="Database is not ready")
