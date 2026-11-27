"""Exercise actual detached subprocesses and one local synthetic HTTP upstream."""

import base64
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

QUALITY = Path(__file__).resolve().parents[2] / "scripts/quality"
BODY = b'{"model":"clomori-fashion-v2","messages":[]}'
ORIGINAL = json.dumps(
    {
        "choices": [{"message": {"content": '{"looks":[]}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
).encode()


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(QUALITY))
    import runpod_job_client as client

    received = []
    gate = threading.Event()

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            received.append(self.rfile.read(int(self.headers["content-length"])))
            self.send_response(200)
            self.send_header("Content-Length", str(len(ORIGINAL)))
            self.end_headers()
            if self.server.drip:
                for byte in ORIGINAL:
                    try:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                    except (ConnectionResetError, BrokenPipeError):
                        self.server.drip_closed.set()
                        break
                    time.sleep(0.12)
            else:
                gate.wait(5)
                self.wfile.write(ORIGINAL)

    s = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    s.drip = False
    s.drip_closed = threading.Event()
    thread = threading.Thread(target=s.serve_forever, daemon=True)
    thread.start()
    env = {
        **os.environ,
        "CLOMORI_JOB_DIR": str(tmp_path / "jobs"),
        "QWEN_MODEL": "clomori-fashion-v2",
        "CLOMORI_MODEL_URL": f"http://127.0.0.1:{s.server_port}/v1/chat/completions",
    }
    script = [sys.executable, "-B", str(QUALITY / "runpod_job.py")]

    def dispatch(action, job, wait, *args):
        raw = subprocess.check_output([*script, action, job, *args], env=env, timeout=max(1, wait))
        return json.loads(raw)

    try:
        yield client, dispatch, received, gate, s, env, script
    finally:
        gate.set()
        s.shutdown()
        s.server_close()
        thread.join()


def until(predicate, limit=5):
    end = time.monotonic() + limit
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.04)
    pytest.fail("Timed out waiting for local detached job")


def test_disconnect_and_concurrent_status_reads_never_duplicate_inference(environment):
    client, dispatch, received, gate, _, env, script = environment
    job = uuid.uuid4().hex
    # Kill the whole management-side process group after acceptance, with inference still running.
    launcher = "import subprocess,sys,time;subprocess.run(sys.argv[1:],check=True);time.sleep(15)"
    parent = subprocess.Popen(
        [sys.executable, "-u", "-c", launcher, *script, "start", job, "8", *client.chunks(BODY)],
        stdout=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    try:
        assert json.loads(parent.stdout.readline())["state"] == "queued"
        until(lambda: len(received) == 1)
    finally:
        os.killpg(parent.pid, signal.SIGKILL)
        parent.wait()
    assert dispatch("status", job, 4)["state"] == "running"
    with ThreadPoolExecutor(4) as pool:
        repeated = list(
            pool.map(lambda _: dispatch("start", job, 4, "8", *client.chunks(BODY)), range(4))
        )
    assert all(r["state"] == "running" for r in repeated)
    bad = BODY.replace(b"[]", b"[{}]")
    assert dispatch("start", job, 4, "8", *client.chunks(bad))["state"] == "conflict"
    gate.set()
    until(lambda: dispatch("status", job, 4)["state"] == "completed")
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: dispatch("result", job, 4), range(4)))
    assert results == [results[0]] * 4
    row = results[0]
    assert row["submitted"] <= row["start"] <= row["end"] and row["job_id"] == job
    assert (
        base64.b64decode(row["body_b64"]) == ORIGINAL
        and row["request_sha256"] == hashlib.sha256(BODY).hexdigest()
    )
    assert row["response_sha256"] == hashlib.sha256(ORIGINAL).hexdigest()
    assert row["finish_reason"] == "stop" and row["usage"] == {
        "prompt_tokens": 7,
        "completion_tokens": 3,
    }
    assert received == [BODY]


def test_ambiguous_submit_and_lost_result_ack_are_followed_by_reads(environment):
    client, dispatch, received, gate, *_ = environment
    job = uuid.uuid4().hex
    calls = []
    gate.set()

    def unreliable(action, job_id, wait, *args):
        response = dispatch(action, job_id, wait, *args)
        calls.append(action)
        if (action == "start" or action == "result") and calls.count(action) == 1:
            raise client.ManagementUnavailable()
        return response

    result = client.await_result(job, BODY, 8, dispatch=unreliable, poll_seconds=0.03)
    assert result["state"] == "completed" and calls.count("start") == 1
    assert calls[calls.index("start") + 1] == "status" and calls.count("result") == 2
    assert received == [BODY]


def test_absolute_deadline_terminates_dribbling_worker_without_retry(environment):
    client, dispatch, received, _, server, *_ = environment
    server.drip = True
    job = uuid.uuid4().hex
    assert dispatch("result", job, 4)["state"] == "not_found"
    start = time.monotonic()
    dispatch("start", job, 4, "2", *client.chunks(BODY))
    until(lambda: dispatch("status", job, 4)["state"] == "timed_out", limit=4)
    assert time.monotonic() - start < 4
    row = dispatch("result", job, 4)
    assert row["error"] == "JobDeadline" and row["finish_reason"] is None and row["usage"] is None
    assert dispatch("start", job, 4, "2", *client.chunks(BODY))["state"] == "timed_out"
    assert server.drip_closed.wait(3)  # The worker really closed its upstream connection.
    assert received == [BODY]
