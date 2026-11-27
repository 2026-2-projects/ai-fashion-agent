"""Run synthetic wardrobe cases on a real Qwen endpoint. Load only the archived inputs/gold."""

import argparse
import contextvars
import hashlib
import json
import logging
import os
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import smoke_qwen
from app.agent import prompts
from app.agent.contracts import AgentRecommendationRequest
from app.agent.qwen import QwenInferenceEngine
from app.agent.service import AgentService
from app.agent.settings import load_qwen_settings
from app.agent.tool_registry import (
    CalendarArguments,
    NoArguments,
    ToolRegistry,
    ToolRuntime,
    WeatherArguments,
)
from sqlalchemy.orm import Session

FROZEN_SHA = "4cc5efaaf9f3f10de40b1997250f78c7ebcd8277edddfeb5d894c7a78b5a978e"
TYPES = {
    "get_user_context": NoArguments,
    "get_wardrobe": NoArguments,
    "get_weather": WeatherArguments,
    "get_calendar_events": CalendarArguments,
}
FIXTURES = Path(__file__).with_name("fixtures") / "step29b-wardrobe.json"
changes = contextvars.ContextVar("wardrobe_corrections", default=None)


def now():
    return datetime.now(UTC).isoformat()


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime.fromisoformat("2026-11-25T21:25:00+09:00").astimezone(tz)


class Audit(logging.Handler):
    def emit(self, record):
        target = changes.get()
        if target is not None and hasattr(record, "wardrobe_correction"):
            target.append(record.wardrobe_correction)


def cases(archive):
    with zipfile.ZipFile(archive) as z:
        data = z.read("planned.json")
    if hashlib.sha256(data).hexdigest() != FROZEN_SHA:
        raise ValueError("Frozen 36-case fixture digest mismatch")
    rows = json.loads(data)["plan"]
    for index, case in enumerate(json.loads(FIXTURES.read_text())):
        count = min(len(case["eligible_outfits"]), 2)
        rows.append(
            {
                "request_id": case["id"],
                "phase": "extension",
                "case": case["name"],
                "seed": 1201 + index,
                "expected": ["unavailable"] * 3
                + ["available"] * count
                + ["unavailable"] * (2 - count),
                "eligible_outfits": case["eligible_outfits"],
                "unverified": case["unverified"],
                "request": {"message": case["message"]},
                "provided_facts": {
                    "get_user_context": {
                        "profile": {},
                        "preference": {"disliked_colors": case["disliked"]},
                    },
                    "get_wardrobe": [
                        smoke_qwen.wardrobe_item(*item) for item in case["items"]
                    ],
                },
            }
        )
    return rows


def run_case(row, settings, folder, barrier, job_transport=False):
    job = uuid.uuid4().hex
    result = {
        "case_id": row["request_id"],
        "job_id": job,
        "batch_size": barrier.parties if barrier else 1,
        "start": now(),
        "input": row,
        "corrections": [],
        "model_original": None,
        "backend_final": None,
        "error": None,
        "finish_reason": None,
        "usage": None,
    }
    tick = time.monotonic()
    state = folder / (row["request_id"] + "-" + job + ".json")
    state.write_text(json.dumps(result | {"state": "running"}, ensure_ascii=False))
    token = changes.set(result["corrections"])

    class RecordingEngine(QwenInferenceEngine):
        def _request_completion(self, payload):
            if row["seed"] is not None:
                payload = {**payload, "seed": row["seed"]}
            result["sent_payload"] = payload
            if job_transport:
                from runpod_job_client import JobFailure, run_completion

                try:
                    raw, result["remote_receipt"] = run_completion(
                        job, payload, settings.timeout_seconds
                    )
                except JobFailure as exc:
                    result["remote_receipt"] = exc.receipt
                    raise
            else:
                raw = super()._request_completion(payload)
            secret = settings.api_key.get_secret_value()
            if secret and secret.encode() in raw:
                raise ValueError("Unsafe upstream echo")
            result["upstream"] = json.loads(raw)
            env = result["upstream"]
            result["usage"] = env.get("usage")
            result["returned_model"] = env.get("model")
            choice = env["choices"][0]
            result["finish_reason"] = choice.get("finish_reason")
            result["model_original"] = json.loads(choice["message"]["content"])["looks"]
            return raw

    try:
        tools = ToolRegistry(
            {
                k: smoke_qwen.fixed_tool(TYPES[k], v)
                for k, v in row["provided_facts"].items()
            }
        )
        if barrier:
            barrier.wait(timeout=15)
        with Session() as db:
            out = AgentService(RecordingEngine(settings), tools).recommend(
                AgentRecommendationRequest(**row["request"]),
                ToolRuntime(db=db, user_id=1),
            )
            result["backend_final"] = [look.model_dump() for look in out.looks]
            result["called_tools"] = out.called_tools
    except Exception as exc:  # noqa: BLE001 - every failed validation attempt is a result
        result["error"] = type(exc).__name__
    finally:
        changes.reset(token)
        result.update(
            end=now(),
            seconds=round(time.monotonic() - tick, 3),
            state="failed" if result["error"] else "completed",
        )
        tmp = state.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False))
        tmp.replace(state)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--only", nargs="+", help="Run specific case IDs as fresh attempts"
    )
    parser.add_argument(
        "--pod-jobs",
        action="store_true",
        help="Use the installed detached job worker on Runpod",
    )
    args = parser.parse_args()
    rows = cases(args.archive)
    if args.only:
        requested = set(args.only)
        if requested - {r["request_id"] for r in rows}:
            parser.error("Unknown case ID")
        rows = [r for r in rows if r["request_id"] in requested]
    config = load_qwen_settings()
    if config is None:
        parser.error("A Qwen configuration is required")
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=False)
    log = logging.getLogger("app.agent.qwen")
    log.addHandler(Audit())
    log.setLevel(logging.INFO)
    pending = [r for r in rows if r["phase"] == "concurrent"]
    for row in rows:
        if row["phase"] == "concurrent" and row != pending[0]:
            continue
        with (
            nullcontext()
            if row["phase"] == "core"
            else patch.object(prompts, "datetime", FixedClock)
        ):
            if row["phase"] == "concurrent":
                barrier = Barrier(len(pending))
                with ThreadPoolExecutor(len(pending)) as pool:
                    records = list(
                        pool.map(
                            lambda r, gate=barrier: run_case(
                                r, config, args.output, gate, args.pod_jobs
                            ),
                            pending,
                        )
                    )
            else:
                records = [run_case(row, config, args.output, None, args.pod_jobs)]
        for d in records:
            print(
                d["case_id"],
                d["state"],
                d["seconds"],
                d["error"] or d["finish_reason"],
                flush=True,
            )


if __name__ == "__main__":
    main()
