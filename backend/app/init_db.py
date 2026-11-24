"""Initialize a new CLOMORI database. Run once with an explicit DATABASE_URL."""

import os
import sys
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from app.core.database_url import postgres_url

BASELINE = Path(__file__).resolve().parents[1] / "migrations" / "baseline_003.sql"


def main() -> int:
    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        print("Set DATABASE_URL explicitly to the new database.", file=sys.stderr)
        return 2

    try:
        conninfo = postgres_url(raw_url)
        if not conninfo_to_dict(conninfo).get("dbname"):
            raise ValueError
    except (ValueError, psycopg.Error):
        print("DATABASE_URL must explicitly identify a PostgreSQL database.", file=sys.stderr)
        return 2

    try:
        script = BASELINE.read_text(encoding="utf-8")
        # The SQL owns BEGIN/COMMIT, takes the lock, and checks emptiness before DDL.
        with psycopg.connect(conninfo, autocommit=True, connect_timeout=5) as connection:
            with connection.execute(script, prepare=False) as result:
                while result.nextset():
                    pass
    except psycopg.errors.RaiseException:
        print("Initialization refused: existing objects or unsuitable target database. "
              "Inspect its migration history before proceeding.", file=sys.stderr)
        return 1
    except (OSError, psycopg.Error) as exc:
        # Raw connection errors may contain credentials, hostnames or SQL parameters.
        code = getattr(exc, "sqlstate", None) or "unavailable"
        print(f"Initialization failed; verify connection, baseline file and permissions "
              f"(SQLSTATE: {code}).", file=sys.stderr)
        return 1

    print("CLOMORI database initialized through migration 003.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
