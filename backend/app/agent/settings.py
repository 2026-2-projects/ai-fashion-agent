"""Opt-in local model settings; no OpenAI account or model download is needed."""

import os
from collections.abc import Mapping
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from app.agent.errors import InferenceConfigurationError


class QwenSettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )

    base_url: str
    model: str = Field(min_length=1, max_length=200)
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    timeout_seconds: float = Field(default=60, ge=1, le=600, allow_inf_nan=False)
    max_tokens: int = Field(default=4096, ge=256, le=32768)
    response_format: Literal["json_schema", "json_object"] = "json_schema"
    send_chat_template_kwargs: bool = False
    max_input_chars: int = Field(default=60000, ge=1000, le=500000)
    max_response_bytes: int = Field(default=524288, ge=1024, le=4194304)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        try:
            url = httpx.URL(value)
        except httpx.InvalidURL:
            raise ValueError("유효한 HTTP(S) /v1 주소가 필요합니다.") from None
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.username
            or url.password
            or "?" in value
            or "#" in value
            or (url.port is not None and not 1 <= url.port <= 65535)
            or not url.path.rstrip("/").endswith("/v1")
        ):
            raise ValueError("인증정보·쿼리 없이 /v1로 끝나는 HTTP(S) 주소가 필요합니다.")
        return str(url).rstrip("/")

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value().strip()
        if any(not 33 <= ord(char) <= 126 for char in key):
            raise ValueError("하나의 토큰으로 된 API 키가 필요합니다.")
        return SecretStr(key)


def load_qwen_settings(
    environ: Mapping[str, str] | None = None,
) -> QwenSettings | None:
    """Read only explicit QWEN_* settings. Mock never initializes a model client."""
    env = os.environ if environ is None else environ
    provider = env.get("AGENT_INFERENCE_PROVIDER", "mock").strip().lower()
    if provider == "mock":
        return None
    if provider != "qwen":
        raise InferenceConfigurationError("AGENT_INFERENCE_PROVIDER는 mock 또는 qwen이어야 합니다.")
    values = {
        field: env[key]
        for field, key in {
            "base_url": "QWEN_BASE_URL",
            "model": "QWEN_MODEL",
            "api_key": "QWEN_API_KEY",
            "timeout_seconds": "QWEN_TIMEOUT_SECONDS",
            "max_tokens": "QWEN_MAX_TOKENS",
            "response_format": "QWEN_RESPONSE_FORMAT",
            "send_chat_template_kwargs": "QWEN_SEND_CHAT_TEMPLATE_KWARGS",
            "max_input_chars": "QWEN_MAX_INPUT_CHARS",
            "max_response_bytes": "QWEN_MAX_RESPONSE_BYTES",
        }.items()
        if key in env
    }
    try:
        return QwenSettings.model_validate(values)
    except ValidationError:
        raise InferenceConfigurationError(
            "Qwen 설정이 올바르지 않습니다. QWEN_BASE_URL·QWEN_MODEL과 추론 옵션을 확인해 주세요."
        ) from None
