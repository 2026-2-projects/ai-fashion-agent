"""Install the fixed validation worker or collect a previously submitted job without resubmitting."""

import argparse
import base64
import hashlib
import http.client
import json
import math
import os
import re
import time
from pathlib import Path

WORKER = Path(__file__).with_name("runpod_job.py")
REMOTE_DIR = "/workspace/clomori-validation"
TERMINAL = {"completed", "timed_out", "failed"}


class JobFailure(RuntimeError):
    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__(receipt.get("error") or receipt["state"])


class ManagementUnavailable(RuntimeError):
    """Ambiguous acknowledgement. Poll the same ID."""


def remote_script():
    return f"{REMOTE_DIR}/worker-{hashlib.sha256(WORKER.read_bytes()).hexdigest()}.py"


def chunks(body):
    text = base64.b64encode(body).decode("ascii")
    return [text[i : i + 3000] for i in range(0, len(text), 3000)]


def management(argv, timeout):
    pid = os.environ.get("RUNPOD_POD_ID", "")
    key = os.environ.get("RUNPOD_API_KEY", "")
    if not re.fullmatch("[a-z0-9]{5,32}", pid) or not key:
        raise ValueError("Expected Runpod Pod ID and management credential")
    conn = http.client.HTTPSConnection(
        "api.runpod.io", timeout=max(0.01, min(8, timeout))
    )
    try:
        conn.request(
            "POST",
            f"/v2/pods/{pid}/exec",
            json.dumps({"command": argv, "timeoutSeconds": 4}),
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
            },
        )
        response = conn.getresponse()
        if response.status in (401, 403, 404):
            raise ValueError(f"Runpod access failed (HTTP {response.status})")
        if response.status != 200:
            raise ManagementUnavailable()
        envelope = json.loads(response.read(1500000))
        if envelope.get("timedOut") or envelope.get("truncated"):
            raise ManagementUnavailable()
        if envelope.get("exitCode") != 0:
            raise ValueError(
                "Remote validation command failed. Verify the installed worker."
            )
        return json.loads(envelope["stdout"])
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
        raise ManagementUnavailable() from exc
    finally:
        conn.close()


def call(action, job, wait, *args):
    if not re.fullmatch("[0-9a-f]{32}", job):
        raise ValueError("Invalid job ID")
    return management(["python3", remote_script(), action, job, *args], wait)


def install():
    # Create a content-addressed script atomically. An existing version is never overwritten.
    installer = """
import base64,hashlib,json,os,sys,tempfile
from pathlib import Path
target=Path(sys.argv[1]);data=base64.b64decode(''.join(sys.argv[2:]),validate=True)
digest=hashlib.sha256(data).hexdigest()
assert target.name=='worker-'+digest+'.py'
os.umask(0o077);target.parent.mkdir(exist_ok=True,parents=True)
with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as f:
    f.write(data);f.flush();os.fsync(f.fileno());name=f.name
try:
    try:os.link(name,target)
    except FileExistsError:pass
    assert target.read_bytes()==data
finally:os.unlink(name)
print(json.dumps({'installed_sha256':digest}))
"""
    return management(
        ["python3", "-c", installer, remote_script(), *chunks(WORKER.read_bytes())], 8
    )


def await_result(job, body, timeout, *, dispatch=call, poll_seconds=0.5):
    """One submission at most. An ambiguous send or lost read always leads back to status."""
    request_sha = hashlib.sha256(body).hexdigest()
    end = time.monotonic() + timeout
    attempted = False
    last = "unknown"
    while (remaining := end - time.monotonic()) > 0:
        try:
            row = dispatch("status", job, remaining)
            if row.get("job_id") != job:
                raise ValueError("Unexpected receipt identifier")
            state = row["state"]
            if state == "not_found" and not attempted:
                attempted = True
                # Account for local setup time when configuring the independent worker deadline.
                allowed = max(1, math.ceil(end - time.monotonic()))
                row = dispatch(
                    "start",
                    job,
                    max(0.01, end - time.monotonic()),
                    str(allowed),
                    *chunks(body),
                )
                state = row["state"]
            if state in {"reservation_incomplete", "conflict"}:
                raise JobFailure(row)
            if (
                row.get("job_id") != job
                or row.get("request_sha256", request_sha) != request_sha
            ):
                raise ValueError("Remote request digest mismatch")
            last = state
            if state in TERMINAL:
                receipt = dispatch("result", job, max(0.01, end - time.monotonic()))
                if (
                    receipt.get("job_id") != job
                    or receipt.get("request_sha256") != request_sha
                    or receipt.get("state") not in TERMINAL
                ):
                    raise ValueError("Unexpected terminal receipt")
                if receipt["state"] != "completed":
                    raise JobFailure(receipt)
                return receipt
        except ManagementUnavailable:
            pass
        time.sleep(min(poll_seconds, max(0, end - time.monotonic())))
    raise JobFailure(
        {
            "job_id": job,
            "request_sha256": request_sha,
            "state": "collection_timeout",
            "error": "LocalDeadline",
            "last_observed_state": last,
        }
    )


def run_completion(job, payload, timeout):
    body = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()
    receipt = await_result(job, body, timeout)
    raw = base64.b64decode(receipt.pop("body_b64"), validate=True)
    if hashlib.sha256(raw).hexdigest() != receipt["response_sha256"]:
        raise ValueError("Remote response digest mismatch")
    return raw, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("install")
    query = sub.add_parser("collect")
    query.add_argument("job_id")
    query.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.action == "install":
        print(json.dumps(install()))
        return
    # Read-only remote operation. Never backfill an earlier failed API call as a success.
    receipt = call("result", args.job_id, 8)
    if receipt.get("job_id") != args.job_id:
        raise ValueError("Unexpected receipt identifier")
    if "body_b64" in receipt:
        raw = base64.b64decode(receipt["body_b64"], validate=True)
        if hashlib.sha256(raw).hexdigest() != receipt.get("response_sha256"):
            raise ValueError("Remote response digest mismatch")
    os.umask(0o077)
    with args.output.open("x") as f:
        json.dump(receipt, f, ensure_ascii=False)
    print(receipt["job_id"], receipt["state"])


if __name__ == "__main__":
    main()
