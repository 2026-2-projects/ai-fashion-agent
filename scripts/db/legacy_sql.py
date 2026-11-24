"""Emit one guarded PostgreSQL upgrade for psql. See backend/migrations/README.md."""

import argparse
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "backend" / "migrations"
FILES = {
    "001": "001_feedback_save.sql",
    "002": "002_optional_dislike_reason.sql",
    "003": "003_feedback_reason_text.sql",
}


def body(version: str) -> str:
    sql = (MIGRATIONS / FILES[version]).read_text(encoding="utf-8").strip()
    if not (sql.startswith("BEGIN;") and sql.endswith("COMMIT;")):
        raise ValueError("Expected a transaction-wrapped legacy migration")
    return sql.removeprefix("BEGIN;").removesuffix("COMMIT;").strip()


def require(condition: str, failure: str) -> str:
    return f"""DO $guard$ BEGIN
    IF ({condition}) IS NOT TRUE THEN RAISE EXCEPTION '{failure}'; END IF;
END $guard$;"""


def constraint(table: str, name: str) -> str:
    return f"""(SELECT pg_get_constraintdef(oid) FROM pg_constraint
        WHERE conrelid = '{table}'::regclass AND conname = '{name}' AND convalidated)"""


def first_version_checks(present: bool) -> str:
    # Detect partially applied 001 even if only indexes or a subset of columns survived.
    objects = ["recommendation_runs", "idx_recommendation_runs_user",
               "uq_feedback_user_look", "uq_saved_outfit_user_look"]
    checks = [f"to_regclass('public.{name}') IS {'NOT ' if present else ''}NULL"
              for name in objects]
    for table, fk in [("feedback", "fk_feedback_recommendation_owner"),
                      ("saved_outfits", "fk_saved_outfit_recommendation_owner")]:
        count = f"""(SELECT count(*) FROM pg_attribute WHERE attrelid = 'public.{table}'::regclass
                 AND attname IN ('recommendation_id', 'look_id') AND NOT attisdropped)"""
        checks += [f"{count} = {2 if present else 0}",
                   f"{constraint('public.' + table, fk)} IS {'NOT ' if present else ''}NULL"]
    return require(" AND ".join(checks), "001 already applied, incomplete or missing")


def guarded(version: str, prior: str) -> str:
    steps = [
        r"\set ON_ERROR_STOP on",
        "BEGIN ISOLATION LEVEL READ COMMITTED;",
        "SET LOCAL lock_timeout = '10s';",
        "SET LOCAL search_path = public, pg_temp;",
        "SELECT pg_catalog.pg_advisory_xact_lock(21023003, 1);",
        "LOCK TABLE public.feedback, public.saved_outfits IN SHARE ROW EXCLUSIVE MODE;",
        first_version_checks(version != "001"),
        require("""NOT EXISTS (SELECT FROM pg_attribute WHERE attrelid = 'public.feedback'::regclass
                AND attname = 'reason_text' AND NOT attisdropped)
                AND NOT EXISTS (SELECT FROM pg_constraint WHERE conrelid = 'public.feedback'::regclass
                AND conname = 'chk_feedback_reason_text_usage')""", "003 already or partly applied"),
    ]
    usage = constraint("public.feedback", "chk_feedback_reason_usage")
    if version in ("002", "003"):
        key = "chk_feedback_reason_usage" if version == "002" else "chk_feedback_reason"
        actual = constraint("public.feedback", key)
        steps += [require(f"encode(convert_to({actual}, 'UTF8'), 'hex') = '{prior.encode().hex()}'",
                          "Previous CHECK differs from the approved legacy definition"),
                  "SET LOCAL search_path = pg_temp;",
                  "CREATE TEMP TABLE feedback (LIKE public.feedback INCLUDING CONSTRAINTS) ON COMMIT DROP;",
                  body("002"),
                  "SET LOCAL search_path = public, pg_temp;"]
        expected = constraint("pg_temp.feedback", "chk_feedback_reason_usage")
        steps.append(require(f"{usage} {'<>' if version == '002' else '='} {expected}",
                             "002 already applied or prerequisite 002 missing"))
    steps.append(body(version))
    if version == "001":
        steps.append(first_version_checks(True))
    elif version == "002":
        steps.append(require(f"{usage} = {expected}", "002 postcondition failed"))
    else:
        steps.append(require(f"{constraint('public.feedback', 'chk_feedback_reason_text_usage')} "
                             "IS NOT NULL", "003 postcondition failed"))
        steps.append(require(f"encode(convert_to({actual}, 'UTF8'), 'hex') <> '{prior.encode().hex()}'",
                             "003 reason constraint already present on an incomplete schema"))
    return "\n\n".join([*steps, "COMMIT;"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", choices=FILES)
    parser.add_argument("--prior-check", type=Path, help="approved previous CHECK definition")
    args = parser.parse_args()
    if (args.version != "001") != bool(args.prior_check):
        parser.error("002 and 003 each require --prior-check, and 001 does not use it")
    prior = args.prior_check.read_text(encoding="utf-8").strip() if args.prior_check else ""
    if args.prior_check and (not prior.startswith("CHECK (") or len(prior) > 20000):
        parser.error("Expected a PostgreSQL CHECK definition from the approved reference")
    print(guarded(args.version, prior))


if __name__ == "__main__":
    main()
