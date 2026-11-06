"""WBS 4.5 Agent Core·Tool Calling HTTP 엔드포인트."""

import json
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.contracts import (
    AgentRecommendationRequest,
    AgentRecommendationResponse,
    AgentRecommendationResult,
)
from app.agent.inference import MockInferenceEngine
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

router = APIRouter(prefix="/agent", tags=["Agent"])
CurrentUser = Annotated[dict, Depends(get_current_user)]
Database = Annotated[Session, Depends(get_db)]
CsrfCheck = Annotated[None, Depends(require_csrf)]

_agent_service = AgentService(MockInferenceEngine(), default_tool_registry())


def get_agent_service() -> AgentService:
    """추후 Qwen3 InferenceEngine으로 교체할 FastAPI 의존성 경계."""
    return _agent_service


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

    db.commit()
    return recommendation_id


@router.post("/recommend", response_model=AgentRecommendationResponse)
def recommend(
    payload: AgentRecommendationRequest,
    user: CurrentUser,
    db: Database,
    _: CsrfCheck,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentRecommendationResponse:
    try:
        result = service.recommend(
            payload,
            ToolRuntime(db=db, user_id=user["id"]),
        )

        try:
            recommendation_id = save_recommendation(
                db=db,
                user_id=user["id"],
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
