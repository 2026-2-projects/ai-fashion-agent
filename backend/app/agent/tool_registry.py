"""허용된 4개 Tool의 인자 검증과 실제 Backend 호출 어댑터."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from sqlalchemy.orm import Session

from app.agent.contracts import AgentPlan, ToolName
from app.agent.tools.calendar import get_calendar_events
from app.agent.tools.user_context import get_user_context
from app.agent.tools.wardrobe import get_wardrobe
from app.agent.tools.weather import get_weather


class AgentRoutingError(Exception):
    """Inference Engine이 허용되지 않은 Tool 계획을 만든 경우."""


class ToolArgumentError(Exception):
    """Tool 호출 전에 인자 계약 검증이 실패한 경우."""

    def __init__(self, tool_name: str, detail: str):
        super().__init__(f"{tool_name} 인자가 올바르지 않습니다: {detail}")
        self.tool_name = tool_name


class NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalendarArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError):
            raise ValueError("date는 실제 YYYY-MM-DD 날짜여야 합니다.") from None
        return value


class WeatherArguments(CalendarArguments):
    place: str
    time: str

    @field_validator("place")
    @classmethod
    def validate_place(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 100:
            raise ValueError("place는 1~100자여야 합니다.")
        return normalized

    @field_validator("time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%H:%M")
        except (TypeError, ValueError):
            raise ValueError("time은 실제 HH:MM 시각이어야 합니다.") from None
        return value


@dataclass(frozen=True)
class ToolRuntime:
    db: Session
    user_id: int


ToolHandler = Callable[[ToolRuntime, BaseModel], Any]


@dataclass(frozen=True)
class ToolDefinition:
    arguments_model: type[BaseModel]
    handler: ToolHandler


@dataclass(frozen=True)
class ValidatedToolCall:
    name: ToolName
    arguments: BaseModel
    definition: ToolDefinition


class ToolRegistry:
    """계획 전체를 먼저 검증한 뒤 Tool을 순서대로 실행한다."""

    def __init__(self, definitions: dict[ToolName, ToolDefinition]):
        self._definitions = definitions

    def validate_plan(self, plan: AgentPlan) -> list[ValidatedToolCall]:
        if len(plan.calls) > 4:
            raise AgentRoutingError("Tool은 한 요청에서 최대 4개까지 호출할 수 있습니다.")

        seen: set[str] = set()
        validated: list[ValidatedToolCall] = []
        for call in plan.calls:
            if call.name in seen:
                raise AgentRoutingError(f"중복 Tool 호출은 허용되지 않습니다: {call.name}")
            seen.add(call.name)
            definition = self._definitions.get(call.name)  # type: ignore[arg-type]
            if definition is None:
                raise AgentRoutingError(f"허용되지 않은 Tool입니다: {call.name}")
            try:
                arguments = definition.arguments_model.model_validate(call.arguments)
            except ValidationError as exc:
                detail = "; ".join(
                    f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                    for error in exc.errors(include_url=False, include_input=False)
                )
                raise ToolArgumentError(call.name, detail) from exc
            validated.append(
                ValidatedToolCall(
                    name=call.name,  # type: ignore[arg-type]
                    arguments=arguments,
                    definition=definition,
                )
            )
        return validated

    def execute(self, plan: AgentPlan, runtime: ToolRuntime) -> dict[ToolName, Any]:
        calls = self.validate_plan(plan)
        results: dict[ToolName, Any] = {}
        for call in calls:
            results[call.name] = call.definition.handler(runtime, call.arguments)
        return results


def _user_context(runtime: ToolRuntime, arguments: BaseModel) -> dict:
    assert isinstance(arguments, NoArguments)
    return get_user_context(runtime.db, runtime.user_id)


def _wardrobe(runtime: ToolRuntime, arguments: BaseModel) -> list[dict]:
    assert isinstance(arguments, NoArguments)
    return get_wardrobe(runtime.db, runtime.user_id)


def _weather(runtime: ToolRuntime, arguments: BaseModel) -> dict[str, int | float | str]:
    del runtime
    assert isinstance(arguments, WeatherArguments)
    return get_weather(arguments.place, arguments.date, arguments.time)


def _calendar(runtime: ToolRuntime, arguments: BaseModel) -> list[dict[str, str | bool]]:
    assert isinstance(arguments, CalendarArguments)
    return get_calendar_events(runtime.db, runtime.user_id, arguments.date)


def default_tool_registry() -> ToolRegistry:
    return ToolRegistry(
        {
            "get_user_context": ToolDefinition(NoArguments, _user_context),
            "get_wardrobe": ToolDefinition(NoArguments, _wardrobe),
            "get_weather": ToolDefinition(WeatherArguments, _weather),
            "get_calendar_events": ToolDefinition(CalendarArguments, _calendar),
        }
    )
