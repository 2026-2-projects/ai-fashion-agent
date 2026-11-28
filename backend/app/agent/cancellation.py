"""Lifetime of one user recommendation across the ASGI and database worker threads."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from time import monotonic

from app.agent.errors import InferenceTimeoutError


class ClientDisconnected(Exception):
    """The client disconnected before its recommendation entered commit."""


class RecommendationScope:
    def __init__(self, request_id: str, timeout_seconds: float | None = None):
        self.request_id = request_id
        self._deadline = None if timeout_seconds is None else monotonic() + timeout_seconds
        self._lock = Lock()
        self._error: type[ClientDisconnected | InferenceTimeoutError] | None = None
        self._committing = False
        self._abort: Callable[[], None] | None = None

    @property
    def remaining_seconds(self) -> float | None:
        return None if self._deadline is None else max(0.0, self._deadline - monotonic())

    def _check_locked(self) -> None:
        if self._committing:
            return
        if self._error is ClientDisconnected:
            raise ClientDisconnected("클라이언트가 추천 요청을 취소했습니다.")
        if self._error is InferenceTimeoutError or self.remaining_seconds == 0:
            raise InferenceTimeoutError("Qwen 응답 대기 시간이 초과되었습니다.")

    def checkpoint(self) -> None:
        with self._lock:
            self._check_locked()

    def begin_commit(self) -> None:
        # The cancellation/commit ordering is decided before issuing the irreversible COMMIT.
        with self._lock:
            self._check_locked()
            self._committing = True

    @property
    def commit_started(self) -> bool:
        with self._lock:
            return self._committing

    def _stop(self, error: type[ClientDisconnected | InferenceTimeoutError]) -> bool:
        with self._lock:
            if self._committing or self._error is not None:
                return False
            self._error = InferenceTimeoutError if self.remaining_seconds == 0 else error
            if self._abort is not None:
                self._abort()
            return self._error is error

    def cancel(self) -> bool:
        return self._stop(ClientDisconnected)

    def expire(self) -> bool:
        return self._stop(InferenceTimeoutError)

    @contextmanager
    def interrupt_model(self, abort: Callable[[], None]) -> Iterator[None]:
        # abort schedules cancellation; it must never block or run user code under this lock.
        with self._lock:
            self._check_locked()
            self._abort = abort
        try:
            yield
        finally:
            with self._lock:
                self._abort = None

    @contextmanager
    def activate(self) -> Iterator[None]:
        token = _current.set(self)
        try:
            yield
        finally:
            _current.reset(token)


_current: ContextVar[RecommendationScope | None] = ContextVar("recommendation_scope", default=None)


def current_scope() -> RecommendationScope | None:
    return _current.get()
