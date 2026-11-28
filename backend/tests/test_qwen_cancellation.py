"""Exercise model transport cancellation separately from the ASGI and DB boundary."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import httpx
import pytest

from app.agent.cancellation import ClientDisconnected, RecommendationScope
from app.agent.contracts import AgentRecommendationRequest
from app.agent.errors import InferenceConfigurationError, InferenceTimeoutError
from app.agent.qwen import QwenInferenceEngine
from app.agent.settings import QwenSettings


def _engine(transport):
    return QwenInferenceEngine(
        QwenSettings(base_url="http://127.0.0.1/v1", model="test"),
        transport=transport,
    )


def _within_scope(scope, func):
    with scope.activate():
        return func()


@pytest.mark.parametrize("disconnect", [True, False], ids=["disconnect", "deadline"])
def test_pending_model_request_is_interrupted_without_waiting_for_a_reply(disconnect):
    started, interrupted, release = Event(), Event(), Event()
    received_ids = []
    scope = RecommendationScope("case-deadline-or-cancel", None if disconnect else 0.5)

    class WaitingServer(httpx.BaseTransport, httpx.AsyncBaseTransport):
        def handle_request(self, request):
            started.set()
            release.wait(5)
            return httpx.Response(200, content=b"late")

        async def handle_async_request(self, request):
            received_ids.append(request.headers.get("X-Request-ID"))
            started.set()
            try:
                await asyncio.wait_for(asyncio.Event().wait(), timeout=5)
            except asyncio.CancelledError:
                interrupted.set()
                raise

    engine = _engine(WaitingServer())
    with ThreadPoolExecutor() as workers:
        result = workers.submit(_within_scope, scope, lambda: engine._request_completion({}))
        try:
            assert started.wait(3), "model HTTP request never started"
            if disconnect:
                scope.cancel()
            assert interrupted.wait(2), "the pending model HTTP operation kept running"
            with pytest.raises(ClientDisconnected if disconnect else InferenceTimeoutError):
                result.result(timeout=2)
            assert received_ids == [scope.request_id]
        finally:
            release.set()


def test_late_reply_is_rejected_before_parsing_or_generating_reasons(monkeypatch):
    scope = RecommendationScope("case-late-reply")
    engine = _engine(httpx.MockTransport(lambda _: httpx.Response(200)))

    def reply_while_cancelled(_payload):
        scope.cancel()
        return b"malformed late result"

    monkeypatch.setattr(engine, "_request_completion", reply_while_cancelled)
    with scope.activate(), pytest.raises(ClientDisconnected):
        engine.generate(
            AgentRecommendationRequest(message="내 옷으로 추천"),
            {"get_user_context": {}, "get_wardrobe": []},
        )


def test_real_peer_sees_only_cancelled_request_eof_while_other_request_completes():
    pending_id, healthy_id = "local-cancelled", "local-survivor"
    arrived = {pending_id: Event(), healthy_id: Event()}
    received_ids = []
    eof = Event()

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            self.connection.settimeout(5)
            self.rfile.read(int(self.headers["Content-Length"]))
            received_id = self.headers.get("X-Request-ID")
            received_ids.append(received_id)
            if received_id not in arrived:
                self.send_error(400)
                return
            arrived[received_id].set()
            if received_id == pending_id:
                if self.rfile.read(1) == b"":
                    eof.set()
                return
            if not eof.wait(5):
                self.send_error(500)
                return
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Upstream) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            engine = QwenInferenceEngine(
                QwenSettings(base_url=f"http://127.0.0.1:{server.server_port}/v1", model="test")
            )
            pending, healthy = RecommendationScope(pending_id), RecommendationScope(healthy_id)
            with ThreadPoolExecutor() as pool:

                def call(scope):
                    return _within_scope(scope, lambda: engine._request_completion({}))

                first, second = pool.submit(call, pending), pool.submit(call, healthy)
                assert all(event.wait(3) for event in arrived.values())
                pending.cancel()
                with pytest.raises(ClientDisconnected):
                    first.result(timeout=3)
                assert eof.wait(3), "local server never observed its HTTP connection close"
                assert second.result(timeout=3) == b"ok"
                assert sorted(received_ids) == sorted(arrived)
        finally:
            server.shutdown()
            thread.join()


def test_sync_only_injected_transport_stays_available_to_unscoped_callers():
    calls = []

    class SyncOnly(httpx.BaseTransport):
        def handle_request(self, request):
            calls.append(request)
            return httpx.Response(200, content=b"ok")

    engine = _engine(SyncOnly())
    with (
        RecommendationScope("only-cancellable").activate(),
        pytest.raises(InferenceConfigurationError),
    ):
        engine._request_completion({})
    assert calls == []
    assert engine._request_completion({}) == b"ok"
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("first", "expected"),
    [("disconnect", ClientDisconnected), ("deadline", InferenceTimeoutError), ("commit", None)],
)
def test_disconnect_deadline_and_commit_use_the_first_admitted_transition(
    monkeypatch, first, expected
):
    now = 100.0
    monkeypatch.setattr("app.agent.cancellation.monotonic", lambda: now)
    scope = RecommendationScope("ordered", timeout_seconds=5)
    if first == "commit":
        scope.begin_commit()
    elif first == "disconnect":
        assert scope.cancel()

    now += 6.0
    assert not scope.cancel()
    assert not scope.expire()
    if expected is None:
        scope.checkpoint()
        assert scope.commit_started
    else:
        with pytest.raises(expected):
            scope.begin_commit()
        assert not scope.commit_started
