"""Pod-side detached, at-most-once runner for synthetic Qwen validation (POSIX, stdlib only)."""

import argparse
import base64
import fcntl
import hashlib
import http.client
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(os.environ.get("CLOMORI_JOB_DIR", "/workspace/clomori-validation/jobs"))
LIMIT = 524288
TERMINAL = {"completed", "failed", "timed_out"}


def timestamp():
    return datetime.now(UTC).isoformat()


def write_json(path, obj):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(f.name, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_json(path):
    return json.loads(path.read_bytes())


@contextmanager
def locked():
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (ROOT / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def command(action, folder):
    return [sys.executable, str(Path(__file__).resolve()), action, folder.name]


def background(argv):
    return subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def update(folder, state, **fields):
    """Caller holds the lock. Terminal states are immutable."""
    record = read_json(folder / "state.json")
    if record["state"] not in TERMINAL:
        record.update(state=state, **fields)
        if state in TERMINAL:
            record["end"] = timestamp()
        write_json(folder / "state.json", record)
    return record


def status(folder, *, result=False):
    with locked():
        state = folder / "state.json"
        if not state.is_file():
            return {"job_id": folder.name, "state": "not_found"}
        record = read_json(state)
        if record["state"] not in TERMINAL and time.time() >= record["deadline"]:
            record = update(folder, "timed_out", error="JobDeadline")
        if result and record.get("response_sha256"):
            record["body_b64"] = read_json(folder / "response.json")["body_b64"]
        return record


def submit(folder, body, timeout):
    if len(body) > LIMIT or not 1 <= timeout <= 600:
        raise ValueError("request bounds")
    payload = json.loads(body)
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("messages"), list)
        or payload.get("model") != os.environ.get("QWEN_MODEL", "clomori-fashion-v2")
        or payload.get("stream", False)
    ):
        raise ValueError("invalid inference request")
    digest = hashlib.sha256(body).hexdigest()
    with locked():
        target = folder / "state.json"
        if target.exists():
            state = read_json(target)
            if (state["request_sha256"], state["timeout_s"]) != (digest, timeout):
                return {"job_id": folder.name, "state": "conflict"}
            return state
        if folder.exists():
            # An interrupted reservation is never silently reused for another model invocation.
            return {"job_id": folder.name, "state": "reservation_incomplete"}
        folder.mkdir(mode=0o700)
        write_json(
            folder / "request.json", {"body_b64": base64.b64encode(body).decode()}
        )
        state = {
            "job_id": folder.name,
            "request_sha256": digest,
            "state": "queued",
            "submitted": timestamp(),
            "start": None,
            "end": None,
            "timeout_s": timeout,
            "deadline": time.time() + timeout,
            "http": None,
            "usage": None,
            "finish_reason": None,
            "error": None,
        }
        write_json(target, state)
        try:
            background(command("_supervise", folder))
        except OSError:
            return update(folder, "failed", error="SupervisorStartError")
        return state


def endpoint():
    address = os.environ.get("CLOMORI_MODEL_URL")
    if not address:
        pod = os.environ.get("RUNPOD_POD_ID", "")
        if not re.fullmatch("[a-z0-9]{5,32}", pod):
            raise ValueError("missing pod identifier")
        address = f"https://{pod}-8000.proxy.runpod.net/v1/chat/completions"
    url = urlsplit(address)
    if (
        url.username
        or url.password
        or url.query
        or url.fragment
        or not url.hostname
        or url.path != "/v1/chat/completions"
        or not (
            url.scheme == "https"
            or (
                url.scheme == "http"
                and url.hostname in {"127.0.0.1", "::1", "localhost"}
            )
        )
    ):
        raise ValueError("invalid model endpoint")
    return url


def perform(folder):
    record = read_json(folder / "state.json")
    body = base64.b64decode(
        read_json(folder / "request.json")["body_b64"], validate=True
    )
    url = endpoint()
    headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
    key = os.environ.get("VLLM_API_KEY")
    if key:
        headers["Authorization"] = "Bearer " + key
    elif url.scheme == "https":
        raise ValueError("missing service credential")
    connection = (
        http.client.HTTPSConnection
        if url.scheme == "https"
        else http.client.HTTPConnection
    )
    remaining = record["deadline"] - time.time()
    if remaining <= 0:
        return
    # Socket read timeouts alone do not bound a continuously dribbling HTTP response.
    # This also bounds the worker if the detached supervisor itself is lost.
    signal.setitimer(signal.ITIMER_REAL, remaining)
    conn = connection(url.hostname, url.port, timeout=remaining)
    try:
        conn.request("POST", url.path, body=body, headers=headers)
        upstream = conn.getresponse()
        raw = upstream.read(LIMIT + 1)
        if len(raw) > LIMIT or (key and key.encode() in raw):
            raise ValueError("response rejected")
        outcome = {
            "http": upstream.status,
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "body_b64": base64.b64encode(raw).decode(),
            "usage": None,
            "finish_reason": None,
        }
        try:
            envelope = json.loads(raw)
            choice = envelope["choices"][0]
            outcome.update(
                usage=envelope.get("usage"), finish_reason=choice.get("finish_reason")
            )
            if not isinstance(choice["message"]["content"], str):
                raise TypeError("missing original")
            if not 200 <= upstream.status < 300:
                outcome["error"] = "UpstreamHTTPError"
        except (KeyError, IndexError, ValueError, TypeError, AttributeError):
            outcome["error"] = (
                "UpstreamHTTPError" if upstream.status != 200 else "InvalidEnvelope"
            )
        write_json(folder / "response.json", outcome)
    finally:
        conn.close()


def supervise(folder):
    with locked():
        state = read_json(folder / "state.json")
        if state["state"] != "queued":
            return
        remaining = state["deadline"] - time.time()
        if remaining <= 0:
            update(folder, "timed_out", error="JobDeadline")
            return
        update(folder, "running", start=timestamp())
    worker = None
    try:
        end = time.monotonic() + remaining
        worker = background(command("_perform", folder))
        code = worker.wait(timeout=max(0, end - time.monotonic()))
        if code != 0 or not (folder / "response.json").exists():
            with locked():
                expired = code in (124, -signal.SIGALRM) or time.monotonic() >= end
                update(
                    folder,
                    "timed_out" if expired else "failed",
                    error="JobDeadline" if expired else "WorkerError",
                )
            return
        result = read_json(folder / "response.json")
        result.pop("body_b64")
        with locked():
            if time.monotonic() >= end:
                update(folder, "timed_out", error="JobDeadline")
            else:
                update(
                    folder, "failed" if result.get("error") else "completed", **result
                )
    except subprocess.TimeoutExpired:
        with locked():
            update(folder, "timed_out", error="JobDeadline")
    except (OSError, ValueError):
        with locked():
            update(folder, "failed", error="SupervisorError")
    finally:
        if worker and worker.poll() is None:
            try:
                os.killpg(worker.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            worker.wait()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("start", "status", "result", "_supervise", "_perform")
    )
    parser.add_argument("job_id")
    parser.add_argument("timeout", type=int, nargs="?")
    parser.add_argument("chunks", nargs="*")
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{32}", args.job_id):
        parser.error("Expected a lowercase UUID hex identifier")
    folder = ROOT / args.job_id
    if args.action == "_supervise":
        supervise(folder)
    elif args.action == "_perform":
        try:
            perform(folder)
        except TimeoutError:
            return 124
        except (OSError, ValueError, http.client.HTTPException):
            return 1
    else:
        if args.action == "start":
            result = submit(
                folder,
                base64.b64decode("".join(args.chunks), validate=True),
                args.timeout or 0,
            )
        else:
            result = status(folder, result=args.action == "result")
        print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
