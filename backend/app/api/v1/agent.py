"""WBS 4.5 Agent Core·Tool Calling HTTP 엔드포인트."""

import json
import logging
import re
from functools import lru_cache
from typing import Annotated
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.cancellation import ClientDisconnected, RecommendationScope, current_scope
from app.agent.clarification import (
    ClarificationPolicy,
    ClarificationRequest,
    ClarificationResponse,
    RuleBasedClarificationPolicy,
)
from app.agent.contracts import (
    AgentRecommendationRequest,
    AgentRecommendationResponse,
    AgentRecommendationResult,
)
from app.agent.errors import (
    InferenceConfigurationError,
    InferenceInputError,
    InferenceResponseError,
    InferenceTimeoutError,
    InferenceUnavailableError,
)
from app.agent.factory import create_inference_engine
from app.agent.service import AgentResultError, AgentService
from app.agent.tool_registry import (
    AgentRoutingError,
    ToolArgumentError,
    ToolRuntime,
    default_tool_registry,
)
from app.api.v1.auth import get_current_user, require_csrf
from app.core.database import get_db
from app.services.errors import (
    AmbiguousPlaceError,
    ExternalServiceError,
    ForecastUnavailableError,
    PlaceNotFoundError,
    ServiceConfigurationError,
    WeatherInputError,
)
from app.services.google_calendar import (
    CalendarAuthorizationError,
    CalendarConfigurationError,
    CalendarExternalError,
    CalendarInputError,
    CalendarNotConnectedError,
    CalendarRateLimitError,
    CalendarResponseError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["Agent"])
CurrentUser = Annotated[dict, Depends(get_current_user)]
Database = Annotated[Session, Depends(get_db)]
CsrfCheck = Annotated[None, Depends(require_csrf)]


@lru_cache(maxsize=1)
def get_agent_service() -> AgentService:
    """기본 Mock. 환경변수 변경 후 재시작하면 Qwen으로 전환한다."""
    try:
        return AgentService(create_inference_engine(), default_tool_registry())
    except InferenceConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def save_recommendation(
    db: Session,
    user_id: int,
    result: AgentRecommendationResult,
) -> UUID:
    """검증된 5 LOOK 추천 결과를 사용자별로 저장한다."""
    recommendation_id = uuid4()

    looks_json = json.dumps(
        [look.model_dump(mode="json") for look in result.looks],
        ensure_ascii=False,
    )

    scope = current_scope()
    if scope is not None:
        scope.checkpoint()
    db.execute(
        text("""
            INSERT INTO recommendation_runs
                (id, user_id, looks)
            VALUES
                (:id, :user_id, CAST(:looks AS JSONB))
        """),
        {
            "id": recommendation_id,
            "user_id": user_id,
            "looks": looks_json,
        },
    )

    if scope is not None:
        # Cancellation before admission rolls back this INSERT. Once admitted, COMMIT owns it.
        scope.begin_commit()
    db.commit()
    return recommendation_id


@router.post("/recommend", response_model=AgentRecommendationResponse)
async def recommend(
    request: Request,
    response: Response,
    payload: AgentRecommendationRequest,
    user: CurrentUser,
    db: Database,
    _: CsrfCheck,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentRecommendationResponse:
    scope = RecommendationScope(uuid4().hex, getattr(service, "request_timeout_seconds", None))
    request_headers = {"X-Recommendation-Request-Id": scope.request_id}
    response.headers.update(request_headers)
    edge_id = request.headers.get("x-railway-request-id", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", edge_id):
        edge_id = "-"
    outcome: AgentRecommendationResponse | Exception

    def log_event(event: str) -> None:
        logger.warning(
            "Recommendation %s request_id=%s railway_request_id=%s commit_admitted=%s",
            event,
            scope.request_id,
            edge_id,
            scope.commit_started,
        )

    async def work() -> None:
        nonlocal outcome
        try:
            # The watcher never uses the request's SQLAlchemy session. Join this worker
            # even if the ASGI task is cancelled, before dependency cleanup closes it.
            with scope.activate(), anyio.CancelScope(shield=True):
                outcome = await anyio.to_thread.run_sync(
                    _recommend_and_save, payload, user["id"], db, service, scope
                )
        except Exception as exc:
            outcome = exc
        finally:
            group.cancel_scope.cancel()

    async with anyio.create_task_group() as group:
        group.start_soon(work)
        try:
            # FastAPI has already consumed the request body.
            with anyio.move_on_after(scope.remaining_seconds) as timer:
                while (await request.receive())["type"] != "http.disconnect":
                    pass
            if timer.cancel_called:
                scope.expire()
                log_event("deadline_reached")
            else:
                scope.cancel()
                log_event("client_disconnected")
        finally:
            # Covers cancellation of the ASGI application itself while work is running.
            scope.cancel()

    if isinstance(outcome, HTTPException):
        outcome.headers = {**(outcome.headers or {}), **request_headers}
        if outcome.status_code == 504:
            log_event("timeout_response")
    if isinstance(outcome, Exception):
        raise outcome
    return outcome


def _recommend_and_save(
    payload: AgentRecommendationRequest,
    user_id: int,
    db: Session,
    service: AgentService,
    scope: RecommendationScope,
) -> AgentRecommendationResponse:
    try:
        scope.checkpoint()
        result = service.recommend(
            payload,
            ToolRuntime(db=db, user_id=user_id),
        )

        scope.checkpoint()
        try:
            recommendation_id = save_recommendation(
                db=db,
                user_id=user_id,
                result=result,
            )
        except SQLAlchemyError as exc:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail="추천 결과 저장 중 오류가 발생했습니다.",
            ) from exc

        return AgentRecommendationResponse(
            **result.model_dump(),
            recommendation_id=recommendation_id,
        )
    except ClientDisconnected:
        db.rollback()
        raise HTTPException(status_code=499, detail="추천 요청의 연결이 종료되었습니다.") from None
    except InferenceTimeoutError as exc:
        db.rollback()
        raise HTTPException(status_code=504, detail=str(exc)) from None
    except (InferenceConfigurationError, InferenceUnavailableError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except InferenceResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except InferenceInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except ToolArgumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentRoutingError as exc:
        raise HTTPException(
            status_code=502,
            detail="Agent가 올바르지 않은 Tool 호출 계획을 생성했습니다.",
        ) from exc
    except PydanticValidationError as exc:
        raise HTTPException(
            status_code=502,
            detail="Agent 결과가 고정 JSON 형식과 일치하지 않습니다.",
        ) from exc
    except AgentResultError as exc:
        raise HTTPException(
            status_code=502,
            detail="Agent 결과가 실제 옷장 정보와 일치하지 않습니다.",
        ) from exc
    except AmbiguousPlaceError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "candidates": exc.candidates},
        ) from exc
    except PlaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (WeatherInputError, ForecastUnavailableError, CalendarInputError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (CalendarNotConnectedError, CalendarAuthorizationError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CalendarRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (ServiceConfigurationError, CalendarConfigurationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except (
        ExternalServiceError,
        CalendarExternalError,
        CalendarResponseError,
    ) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=401, detail="유효하지 않은 사용자입니다.") from exc


# CLOMORI_CLARIFICATION_STEP10_V1
_clarification_policy = RuleBasedClarificationPolicy()


def get_clarification_policy() -> ClarificationPolicy:
    """Run the rule-based preflight independently of recommendation inference."""
    return _clarification_policy


@router.post("/clarify", response_model=ClarificationResponse)
def clarify_before_recommendation(
    payload: ClarificationRequest,
    user: CurrentUser,
    _: CsrfCheck,
    policy: Annotated[ClarificationPolicy, Depends(get_clarification_policy)],
) -> ClarificationResponse:
    """Authenticated, CSRF-guarded, non-mutating recommendation preflight."""
    # ``user`` forces current-session validation; no chat text or answers are persisted.
    try:
        return policy.inspect(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
