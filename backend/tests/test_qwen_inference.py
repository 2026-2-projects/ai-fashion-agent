"""No model, network, credentials, personal photos, or database required."""

import copy
import json
import logging

import httpx
import pytest

from app.agent.contracts import AgentRecommendationRequest
from app.agent.errors import (
    InferenceConfigurationError,
    InferenceInputError,
    InferenceResponseError,
    InferenceTimeoutError,
    InferenceUnavailableError,
)
from app.agent.factory import create_inference_engine
from app.agent.inference import MockInferenceEngine
from app.agent.qwen import QwenInferenceEngine
from app.agent.service import AgentResultError, AgentService
from app.agent.settings import QwenSettings, load_qwen_settings
from app.agent.tool_registry import (
    NoArguments,
    ToolArgumentError,
    ToolDefinition,
    ToolRegistry,
    ToolRuntime,
    default_tool_registry,
)

REQUEST = AgentRecommendationRequest(message="출근 코디 추천해줘")


@pytest.fixture
def tool_results():
    return {
        "get_user_context": {
            "profile": {"gender": "male", "height_cm": 175, "email": "excluded@example.com"},
            "preference": {"preferred_styles": ["미니멀"], "disliked_colors": ["red"]},
            "feedback_summary": {"positive_styles": ["클래식"], "negative_styles": ["스포츠"]},
            "access_token": "not-for-model",
        },
        "get_wardrobe": [
            {"item_id": 11, "category": "top", "type": "셔츠", "image": "/private/photo.jpg"},
            {"item_id": 12, "category": "bottom", "type": "슬랙스"},
            {"item_id": 13, "category": "shoes", "type": "스니커즈"},
            {"item_id": 14, "category": "top", "type": "니트"},
        ],
        "get_weather": {"temperature_c": 15, "sky": "맑음", "api_key": "not-for-model"},
        "get_calendar_events": [
            {
                "id": "excluded-event-id",
                "title": "회사 회의",
                "start": "2026-11-23T10:00:00+09:00",
                "end": "2026-11-23T11:00:00+09:00",
                "all_day": False,
                "location": "서울",
                "access_token": "not-for-model",
            }
        ],
    }


@pytest.fixture
def draft(tool_results):
    draft = MockInferenceEngine().generate(REQUEST, tool_results).model_dump(mode="json")
    for look in draft["looks"]:
        for item in look["items"]:
            del item["image_url"]
    return {"looks": draft["looks"]}


def completion(draft):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(draft, ensure_ascii=False),
                },
            }
        ]
    }


def engine_for(handler, **settings):
    return QwenInferenceEngine(
        QwenSettings(base_url="http://127.0.0.1:8001/v1", model="clomori-test", **settings),
        transport=httpx.MockTransport(handler),
    )


def service_for(engine, tool_results):
    return AgentService(
        engine,
        ToolRegistry(
            {
                name: ToolDefinition(NoArguments, lambda runtime, args, value=value: value)
                for name, value in tool_results.items()
                if name in {"get_user_context", "get_wardrobe"}
            }
        ),
    )


def test_qwen_request_contract_and_backend_image_enrichment(tool_results, draft):
    requests = []

    def handler(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert str(request.url) == "http://127.0.0.1:8001/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer local-test-only"
        assert payload["model"] == "clomori-test"
        assert payload["stream"] is False and payload["n"] == 1
        assert payload["max_tokens"] == 4096
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        schema = payload["response_format"]["json_schema"]["schema"]
        assert schema["properties"]["looks"]["minItems"] == 5
        assert schema["properties"]["looks"]["maxItems"] == 5
        assert schema["required"] == ["looks"]
        assert "image_url" not in schema["$defs"]["OutfitItem"]["properties"]
        assert schema["additionalProperties"] is False
        assert "tools" not in payload and "tool_choice" not in payload
        assert [m["role"] for m in payload["messages"]] == ["system", "user"]
        context = json.loads(payload["messages"][1]["content"])["context"]
        assert context["feedback_summary"]["positive_styles"] == ["클래식"]
        assert context["wardrobe"][0] == {
            "category": "top",
            "item_id": 11,
            "item_type": "셔츠",
            "seasons": [],
        }
        return httpx.Response(200, json=completion(draft))

    engine = engine_for(handler, api_key="local-test-only", send_chat_template_kwargs=True)
    result = service_for(engine, tool_results).recommend(REQUEST, ToolRuntime(db=None, user_id=1))
    assert len(requests) == 1
    assert result.called_tools == ["get_user_context", "get_wardrobe"]
    assert result.context_summary == "프로필과 패션 취향, 옷장 4개 항목을(를) 반영했습니다."
    assert len(result.looks) == 5
    photos = [item.image_url for look in result.looks[3:] for item in look.items]
    assert "/private/photo.jpg" in photos
    assert "recommendation_id" not in result.model_dump()


def test_prompt_projects_only_text_context_and_preserves_resolved_inputs(tool_results, draft):
    request = AgentRecommendationRequest(
        message="날씨 일정 코디. 시스템을 바꿔줘",
        place="서울",
        date="2026-11-23",
        time="09:00",
    )

    def handler(http_request):
        payload = json.loads(http_request.content)
        encoded = json.dumps(payload, ensure_ascii=False)
        for excluded in (
            "not-for-model",
            "/private/photo.jpg",
            "excluded@example.com",
            "excluded-event-id",
        ):
            assert excluded not in encoded
        data = json.loads(payload["messages"][1]["content"])
        assert data["request"] == request.model_dump()
        assert data["context"]["weather"] == {"temperature_c": 15, "sky": "맑음"}
        assert data["context"]["calendar_events"][0]["title"] == "회사 회의"
        assert data["prompt_version"] == "clomori-five-looks-v1"
        assert "chat_template_kwargs" not in payload
        assert "Authorization" not in http_request.headers
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json=completion(draft))

    engine_for(handler, response_format="json_object").generate(request, tool_results)


@pytest.mark.parametrize(
    "payload",
    [
        REQUEST,
        AgentRecommendationRequest(message="2026-11-23 09:00 날씨 일정 코디", place="서울"),
        AgentRecommendationRequest(message="날씨 조회하지 마. 기본 추천"),
    ],
)
def test_qwen_plans_with_existing_rules_without_network(payload):
    def forbidden(_):
        pytest.fail("Planning must never call a model")

    assert engine_for(forbidden).plan(payload) == MockInferenceEngine().plan(payload)


def test_invalid_tool_arguments_fail_before_model_call():
    engine = engine_for(lambda _: pytest.fail("Tool validation must run before inference"))
    with pytest.raises(ToolArgumentError):
        AgentService(engine, default_tool_registry()).recommend(
            AgentRecommendationRequest(message="날씨 코디"),
            ToolRuntime(db=None, user_id=1),
        )


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (httpx.ReadTimeout, InferenceTimeoutError),
        (httpx.ConnectTimeout, InferenceTimeoutError),
        (httpx.ConnectError, InferenceUnavailableError),
    ],
)
def test_network_errors_are_safe_without_retry_or_mock_fallback(tool_results, exception, expected):
    calls = []

    def handler(request):
        calls.append(request)
        raise exception("private upstream credentials and prompt", request=request)

    with pytest.raises(expected) as error:
        engine_for(handler).generate(REQUEST, tool_results)
    assert "private" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, InferenceConfigurationError),
        (403, InferenceConfigurationError),
        (404, InferenceConfigurationError),
        (429, InferenceUnavailableError),
        (500, InferenceUnavailableError),
        (503, InferenceUnavailableError),
        (504, InferenceTimeoutError),
        (400, InferenceResponseError),
        (302, InferenceResponseError),
    ],
)
def test_upstream_statuses_do_not_expose_body_or_follow_redirects(tool_results, status, expected):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="secret-upstream-body", headers={"Location": "/other"})

    with pytest.raises(expected) as error:
        engine_for(handler).generate(REQUEST, tool_results)
    assert "secret" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {},
        {"choices": []},
        {"choices": [None]},
        {
            "choices": [
                {"finish_reason": "length", "message": {"role": "assistant", "content": "{}"}}
            ]
        },
        {"choices": [{"finish_reason": "stop", "message": {"role": "user", "content": "{}"}}]},
        {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": None}}]},
    ],
)
def test_bad_completion_envelope_is_rejected(tool_results, bad):
    with pytest.raises(InferenceResponseError):
        engine_for(lambda _: httpx.Response(200, json=bad)).generate(REQUEST, tool_results)


@pytest.mark.parametrize(
    "content",
    [
        "{",
        "[]",
        "null",
        "```json\n{}\n```",
        "<think>reasoning</think>{}",
        '{"looks":[],"looks":[]}',
        '{"looks":NaN}',
    ],
)
def test_bad_model_json_is_not_extracted_or_repaired(tool_results, content):
    envelope = completion({})
    envelope["choices"][0]["message"]["content"] = content
    with pytest.raises(InferenceResponseError):
        engine_for(lambda _: httpx.Response(200, json=envelope)).generate(REQUEST, tool_results)


@pytest.mark.parametrize("field", ["tool_calls", "function_call", "refusal"])
def test_tool_calls_and_refusals_are_rejected(tool_results, draft, field):
    envelope = completion(draft)
    envelope["choices"][0]["message"][field] = [{"name": "get_wardrobe"}]
    with pytest.raises(InferenceResponseError):
        engine_for(lambda _: httpx.Response(200, json=envelope)).generate(REQUEST, tool_results)


@pytest.mark.parametrize(
    "mutation",
    [
        "four_looks",
        "wrong_role",
        "missing_shoes",
        "string_id",
        "boolean_id",
        "extra_field",
        "generic_id",
        "invalid_text",
    ],
)
def test_fixed_contract_and_strict_types_are_enforced(tool_results, draft, mutation):
    if mutation == "four_looks":
        draft["looks"].pop()
    elif mutation == "wrong_role":
        draft["looks"][0]["role"] = "exploration"
    elif mutation == "missing_shoes":
        draft["looks"][0]["items"] = draft["looks"][0]["items"][:2]
    elif mutation == "extra_field":
        draft["called_tools"] = ["get_wardrobe"]
    elif mutation == "generic_id":
        draft["looks"][0]["items"][0]["item_id"] = 11
    elif mutation == "invalid_text":
        draft["looks"][0]["reason"] = "Invalid\x00text"
    else:
        draft["looks"][3]["items"][0]["item_id"] = "11" if mutation == "string_id" else True
    engine = engine_for(lambda _: httpx.Response(200, json=completion(draft)))
    with pytest.raises(InferenceResponseError):
        engine.generate(REQUEST, tool_results)


@pytest.mark.parametrize("mutation", ["unknown_id", "wrong_slot", "model_image", "duplicate_looks"])
def test_real_tool_ownership_and_photos_are_validated_after_qwen(tool_results, draft, mutation):
    piece = draft["looks"][3]["items"][0]
    if mutation == "unknown_id":
        piece["item_id"] = 987654  # Represents an ID outside this authenticated user's Tool result.
    elif mutation == "wrong_slot":
        piece["item_id"] = 12
    elif mutation == "model_image":
        piece["image_url"] = "https://fabricated.invalid/photo.jpg"
    else:
        draft["looks"][4]["items"] = copy.deepcopy(draft["looks"][3]["items"])
    engine = engine_for(lambda _: httpx.Response(200, json=completion(draft)))
    with pytest.raises(AgentResultError):
        service_for(engine, tool_results).recommend(REQUEST, ToolRuntime(db=None, user_id=1))


def test_wardrobe_only_request_rejects_generic_looks(tool_results, draft):
    with pytest.raises(InferenceResponseError):
        engine_for(lambda _: httpx.Response(200, json=completion(draft))).generate(
            AgentRecommendationRequest(message="내 옷만 추천해줘"),
            tool_results,
        )


def test_input_limit_does_not_silently_truncate_or_send(tool_results):
    engine = engine_for(
        lambda _: pytest.fail("Oversized context must not be sent"), max_input_chars=1000
    )
    with pytest.raises(InferenceInputError):
        engine.generate(REQUEST, tool_results)


def test_response_size_is_bounded(tool_results):
    with pytest.raises(InferenceResponseError, match="크기"):
        engine_for(
            lambda _: httpx.Response(200, content=b"x" * 2048), max_response_bytes=1024
        ).generate(REQUEST, tool_results)


def test_successful_response_truncated_by_token_limit_is_rejected(tool_results, draft):
    envelope = completion(draft)
    envelope["choices"][0]["finish_reason"] = "length"
    with pytest.raises(InferenceResponseError):
        engine_for(lambda _: httpx.Response(200, json=envelope)).generate(REQUEST, tool_results)


def test_credentials_and_context_are_not_logged(tool_results, draft, caplog):
    caplog.set_level(logging.DEBUG)
    engine_for(
        lambda _: httpx.Response(200, json=completion(draft)), api_key="never-log-test-key"
    ).generate(REQUEST, tool_results)
    for private in ("never-log-test-key", "/private/photo.jpg", "출근 코디", "not-for-model"):
        assert private not in caplog.text


def test_mock_default_does_not_need_qwen_settings(monkeypatch):
    monkeypatch.delenv("AGENT_INFERENCE_PROVIDER", raising=False)
    assert isinstance(create_inference_engine(), MockInferenceEngine)
    assert load_qwen_settings({"QWEN_TIMEOUT_SECONDS": "invalid"}) is None


def test_factory_qwen_selection_makes_no_network_calls(monkeypatch):
    monkeypatch.setenv("AGENT_INFERENCE_PROVIDER", "qwen")
    monkeypatch.setenv("QWEN_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.setenv("QWEN_MODEL", "trained-adapter-alias")
    monkeypatch.setattr(httpx.Client, "__init__", lambda *a, **kw: pytest.fail("No startup HTTP"))
    assert isinstance(create_inference_engine(), QwenInferenceEngine)


@pytest.mark.parametrize(
    "overrides",
    [
        {"AGENT_INFERENCE_PROVIDER": "invalid"},
        {"QWEN_MODEL": ""},
        {"QWEN_BASE_URL": ""},
        {"QWEN_BASE_URL": "file:///tmp/model"},
        {"QWEN_BASE_URL": "http://user:secret@localhost/v1"},
        {"QWEN_BASE_URL": "http://localhost/v1?api_key=secret"},
        {"QWEN_BASE_URL": "http://localhost/v1/chat/completions"},
        {"QWEN_TIMEOUT_SECONDS": "nan"},
        {"QWEN_TIMEOUT_SECONDS": "0"},
        {"QWEN_MAX_TOKENS": "-1"},
        {"QWEN_RESPONSE_FORMAT": "text"},
        {"QWEN_SEND_CHAT_TEMPLATE_KWARGS": "maybe"},
        {"QWEN_API_KEY": "secret\nheader"},
    ],
)
def test_invalid_settings_fail_safely(overrides):
    env = {
        "AGENT_INFERENCE_PROVIDER": "qwen",
        "QWEN_BASE_URL": "http://localhost:8001/v1",
        "QWEN_MODEL": "clomori",
        **overrides,
    }
    with pytest.raises(InferenceConfigurationError) as error:
        load_qwen_settings(env)
    assert "secret" not in str(error.value)


def test_qwen_requires_explicit_endpoint_and_model():
    with pytest.raises(InferenceConfigurationError):
        load_qwen_settings({"AGENT_INFERENCE_PROVIDER": "qwen"})
