"""WBS 4.3 Location·Weather Tool 확인용 FastAPI 라우트."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.agent.tools.weather import get_weather
from app.api.v1.auth import get_current_user
from app.services.errors import (
    AmbiguousPlaceError,
    ExternalServiceError,
    ForecastUnavailableError,
    PlaceNotFoundError,
    ServiceConfigurationError,
    WeatherInputError,
)

router = APIRouter(
    prefix="/weather",
    tags=["Weather"],
    dependencies=[Depends(get_current_user)],
)


class WeatherResponse(BaseModel):
    temperature_c: int | float
    precipitation_probability: int
    precipitation_type: str
    wind_mps: float
    humidity_percent: int
    sky: str


@router.get("", response_model=WeatherResponse)
def read_weather(
    place: Annotated[str, Query(min_length=1, max_length=100)],
    date: Annotated[str, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")],
    time: Annotated[str, Query(pattern=r"^\d{2}:\d{2}$")],
) -> dict[str, int | float | str]:
    try:
        return get_weather(place, date, time)
    except AmbiguousPlaceError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "candidates": exc.candidates,
            },
        ) from exc
    except PlaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (WeatherInputError, ForecastUnavailableError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ServiceConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
