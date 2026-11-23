"""Synchronous, opt-in adapter for a local OpenAI-compatible Qwen server."""

import json
from collections.abc import Mapping
from typing import Any

import httpx

from app.agent.contracts import AgentDraft, AgentPlan, AgentRecommendationRequest, ToolName
from app.agent.errors import (
    InferenceConfigurationError,
    InferenceInputError,
    InferenceResponseError,
    InferenceTimeoutError,
    InferenceUnavailableError,
)
from app.agent.inference import (
    RuleBasedToolPlanner,
    summarize_tool_results,
    wardrobe_only_requested,
)
from app.agent.prompts import LOOKS_SCHEMA, build_messages
from app.agent.settings import QwenSettings


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        if isinstance(value, str):
            # PostgreSQL JSONB rejects NUL and unpaired Unicode surrogates.
            if "\x00" in value:
                raise ValueError("NUL in JSON string")
            value.encode("utf-8")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def _load_json(content: str | bytes) -> Any:
    return json.loads(content, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def _completion_content(raw: bytes) -> str:
    envelope = _load_json(raw)
    choices = envelope.get("choices") if isinstance(envelope, dict) else None
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("Expected one completion")
    choice = choices[0]
    message = choice.get("message")
    if (
        choice.get("finish_reason") != "stop"
        or not isinstance(message, dict)
        or message.get("role") != "assistant"
        or message.get("tool_calls")
        or message.get("function_call")
        or message.get("refusal")
        or not isinstance(message.get("content"), str)
    ):
        raise ValueError("Incomplete or non-text completion")
    return message["content"]


class QwenInferenceEngine:
    """Models generate drafts; backend rules alone select and execute Tools."""

    def __init__(
        self,
        settings: QwenSettings,
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        self._settings = settings
        self._transport = transport
        self._planner = RuleBasedToolPlanner()

    def plan(self, request: AgentRecommendationRequest) -> AgentPlan:
        return self._planner.plan(request)

    def generate(
        self,
        request: AgentRecommendationRequest,
        tool_results: Mapping[ToolName, Any],
    ) -> AgentDraft:
        try:
            messages = build_messages(request, tool_results)
        except (TypeError, ValueError, RecursionError):
            raise InferenceInputError("추천에 필요한 정보를 모델에 전송할 수 없습니다.") from None
        if sum(len(message["content"]) for message in messages) > self._settings.max_input_chars:
            raise InferenceInputError("추천에 필요한 정보가 모델 입력 한도를 초과했습니다.")
        payload: dict[str, Any] = {
            "model": self._settings.model,
            "messages": messages,
            "stream": False,
            "n": 1,
            "max_tokens": self._settings.max_tokens,
            "temperature": 0.7,
            "top_p": 0.8,
            "response_format": {"type": self._settings.response_format},
        }
        if self._settings.response_format == "json_schema":
            payload["response_format"]["json_schema"] = {
                "name": "clomori_five_looks",
                "strict": True,
                "schema": LOOKS_SCHEMA,
            }
        if self._settings.send_chat_template_kwargs:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        raw = self._request_completion(payload)
        try:
            output = _load_json(_completion_content(raw))
            if not isinstance(output, dict) or output.keys() != {"looks"}:
                raise ValueError("Expected only looks")
            draft = AgentDraft.model_validate(
                {"context_summary": summarize_tool_results(tool_results), **output},
                strict=True,
            )
            if wardrobe_only_requested(request.message) and any(
                look.status != "unavailable" for look in draft.looks[:3]
            ):
                raise ValueError("Wardrobe-only request must not contain generic LOOKs")
        except (ValueError, RecursionError):
            raise InferenceResponseError(
                "Qwen 응답이 완전한 5 LOOK JSON 형식과 일치하지 않습니다."
            ) from None
        return draft

    def _request_completion(self, payload: dict[str, Any]) -> bytes:
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        key = self._settings.api_key.get_secret_value()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            timeout = self._settings.timeout_seconds
            with httpx.Client(
                timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)),
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            ) as client:
                with client.stream(
                    "POST",
                    f"{self._settings.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response:
                    self._check_status(response.status_code)
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        if len(raw) + len(chunk) > self._settings.max_response_bytes:
                            raise InferenceResponseError("Qwen 응답이 허용된 크기를 초과했습니다.")
                        raw.extend(chunk)
                    return bytes(raw)
        except httpx.TimeoutException:
            raise InferenceTimeoutError("Qwen 응답 대기 시간이 초과되었습니다.") from None
        except httpx.RequestError:
            raise InferenceUnavailableError("Qwen 서버에 연결하지 못했습니다.") from None
        except UnicodeEncodeError:
            raise InferenceInputError("추천에 필요한 정보를 모델에 전송할 수 없습니다.") from None

    @staticmethod
    def _check_status(status_code: int) -> None:
        if status_code in {401, 403, 404}:
            raise InferenceConfigurationError("Qwen 서버의 인증·모델·API 경로를 확인해 주세요.")
        if status_code in {408, 504}:
            raise InferenceTimeoutError("Qwen 응답 대기 시간이 초과되었습니다.")
        if status_code == 429 or status_code >= 500:
            raise InferenceUnavailableError("Qwen 서버가 현재 요청을 처리할 수 없습니다.")
        if status_code != 200:
            raise InferenceResponseError("Qwen 서버가 추론 요청을 정상적으로 수락하지 않았습니다.")
