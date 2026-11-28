"""Order disconnect/deadline, INSERT and COMMIT using a real PostgreSQL transaction."""

import asyncio
import json
import threading

import pytest
from fastapi import FastAPI, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

import app.api.v1.agent as agent_api
from app.agent.contracts import AgentRecommendationResult
from app.agent.inference import MockInferenceEngine
from app.api.v1.auth import get_current_user, require_csrf
from app.core.database import engine, get_db


class Gate:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def pause(self):
        self.entered.set()
        assert self.release.wait(5), "test failed to release request"


class RequestExchange:
    """Deliver a real ASGI disconnect independently of the running endpoint."""

    def __init__(self, app, account):
        self.app = app
        self.account = account
        self.disconnect = asyncio.Event()
        self.delivered = asyncio.Event()
        self.status = None
        self.response_headers = {}

    async def run(self):
        sent_body = False

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": json.dumps({"message": "코디"}).encode()}
            await self.disconnect.wait()
            self.delivered.set()
            return {"type": "http.disconnect"}

        async def send(event):
            if event["type"] == "http.response.start":
                self.status = event["status"]
                self.response_headers = dict(event["headers"])

        await self.app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "scheme": "http",
                "method": "POST",
                "path": "/agent/recommend",
                "query_string": b"",
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"x-test-account", str(self.account).encode()),
                    (b"x-request-id", b"same-client-value"),
                ],
            },
            receive,
            send,
        )


@pytest.fixture
def request_pair():
    # Each synthetic account gets its own connection-private table. No live history is touched.
    with engine.connect() as first, engine.connect() as second:
        for conn in (first, second):
            conn.execute(
                text(
                    "CREATE TEMP TABLE recommendation_runs "
                    "(id uuid PRIMARY KEY, user_id integer, looks jsonb)"
                )
            )
            conn.commit()
        try:
            yield first, second
        finally:
            for conn in (first, second):
                conn.execute(text("DROP TABLE pg_temp.recommendation_runs"))
                conn.commit()


@pytest.mark.parametrize(
    ("point", "signal", "expected"),
    [
        ("late_model", "disconnect", 499),
        ("late_model", "deadline", 504),
        ("before_insert", "disconnect", 499),
        ("before_insert", "deadline", 504),
        ("late_model", "asgi_cancel", None),
        ("after_insert", "disconnect", 499),
        ("after_insert", "deadline", 504),
        ("commit_admitted", "disconnect", 200),
        ("commit_admitted", "deadline", 200),
    ],
)
def test_signal_isolated_to_one_recommendation(request_pair, point, signal, expected, monkeypatch):
    gate = Gate()
    first, second = request_pair
    subject_inserts = []
    subject_closed = threading.Event()

    original_save = agent_api.save_recommendation

    def observed_save(db, user_id, result):
        if user_id == 1 and point == "before_insert":
            gate.pause()
        return original_save(db=db, user_id=user_id, result=result)

    monkeypatch.setattr(agent_api, "save_recommendation", observed_save)

    class ObservedSession(Session):
        def execute(self, *args, **kwargs):
            result = super().execute(*args, **kwargs)
            if self.bind is first:
                subject_inserts.append(1)
                if point == "after_insert":
                    gate.pause()
            return result

        def commit(self):
            if self.bind is first and point == "commit_admitted":
                gate.pause()
            super().commit()

    class Service:
        request_timeout_seconds = 0.25 if signal == "deadline" else None

        def recommend(self, request, runtime):
            if runtime.user_id == 1 and point == "late_model":
                gate.pause()  # deliberately returns a valid result even after the signal
            draft = MockInferenceEngine().generate(request, {})
            return AgentRecommendationResult(**draft.model_dump(), called_tools=[])

    def user(request: Request):
        return {"id": int(request.headers["x-test-account"])}

    def db(request: Request):
        conn = first if user(request)["id"] == 1 else second
        with ObservedSession(bind=conn) as session:
            try:
                yield session
            finally:
                if conn is first:
                    subject_closed.set()

    app = FastAPI()
    app.include_router(agent_api.router)
    app.dependency_overrides.update(
        {
            get_db: db,
            get_current_user: user,
            require_csrf: lambda: None,
            agent_api.get_agent_service: Service,
        }
    )

    async def scenario():
        subject = RequestExchange(app, 1)
        unaffected = RequestExchange(app, 2)
        task = asyncio.create_task(subject.run())
        try:
            assert await asyncio.to_thread(gate.entered.wait, 4)
            if signal == "disconnect":
                subject.disconnect.set()
                try:
                    await asyncio.wait_for(subject.delivered.wait(), 0.3)
                except TimeoutError:
                    pass  # A missing disconnect observer must still release the DB test gate.
            elif signal == "deadline":
                await asyncio.sleep(Service.request_timeout_seconds + 0.05)
            else:
                task.cancel()  # The ASGI task itself ends without receiving a disconnect event.
            await unaffected.run()
            if signal == "asgi_cancel":
                assert not subject_closed.is_set(), "ASGI dependency closed while its worker ran"
        finally:
            gate.release.set()
            if signal == "asgi_cancel":
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
            else:
                await asyncio.wait_for(task, 5)
        return subject, unaffected

    subject, unaffected = asyncio.run(scenario())
    saved = tuple(c.scalar(text("SELECT count(*) FROM recommendation_runs")) for c in request_pair)
    assert (subject.status, saved) == (expected, (int(expected == 200), 1))
    assert unaffected.status == 200
    assert len(subject_inserts) == int(point in ("after_insert", "commit_admitted"))
    if signal == "asgi_cancel":
        assert subject_closed.is_set()
        return
    assert signal != "disconnect" or subject.delivered.is_set()
    id_header = b"x-recommendation-request-id"
    assert subject.response_headers[id_header] != unaffected.response_headers[id_header]
