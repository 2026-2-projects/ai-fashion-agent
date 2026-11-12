from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest

from app.services.shopping_images import ShoppingImageService


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class RecordingHttp:
    def __init__(
        self,
        handler: Callable[[str, dict[str, str], float], httpx.Response],
    ) -> None:
        self._handler = handler
        self.calls: list[tuple[str, dict[str, str], float]] = []
        self._lock = threading.Lock()

    def get(
        self,
        url: str,
        *,
        params: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        with self._lock:
            self.calls.append((url, dict(params), timeout))
        return self._handler(url, params, timeout)


def shopping_response(
    *,
    title: str = "아이보리 셔츠",
    serpapi_thumbnail: str = "https://images.example/serpapi.webp",
    thumbnail: str = "https://images.example/original.webp",
    product_link: str = "https://shop.example/product/1",
    source: str = "Example Shop",
    position: int = 1,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "shopping_results": [
                {
                    "position": position,
                    "title": title,
                    "serpapi_thumbnail": serpapi_thumbnail,
                    "thumbnail": thumbnail,
                    "product_link": product_link,
                    "source": source,
                }
            ]
        },
    )


@pytest.mark.parametrize(
    ("enabled", "api_key"),
    [
        (False, "secret-key"),
        (True, None),
        (True, "   "),
    ],
)
def test_disabled_or_blank_key_never_calls_http(enabled: bool, api_key: str | None) -> None:
    def fail_if_called(url: str, params: dict[str, str], timeout: float) -> httpx.Response:
        del url, params, timeout
        raise AssertionError("disabled provider must not call HTTP")

    http = RecordingHttp(fail_if_called)
    service = ShoppingImageService(api_key, enabled=enabled, http=http)

    result = service.resolve("아이보리 셔츠", "top")

    assert result.status == "provider_disabled"
    assert http.calls == []


def test_request_uses_fixed_safe_parameters_and_returns_sanitized_fields() -> None:
    http = RecordingHttp(lambda *_: shopping_response())
    service = ShoppingImageService(
        "private-key",
        timeout_seconds=3.5,
        http=http,
    )

    result = service.resolve("  아이보리   셔츠  ", "TOP")

    assert result.status == "found"
    assert result.url == "https://images.example/serpapi.webp"
    assert result.source_name == "Example Shop"
    assert result.source_url == "https://shop.example/product/1"
    assert len(http.calls) == 1
    url, params, timeout = http.calls[0]
    assert url == "https://serpapi.com/search.json"
    assert timeout == 3.5
    assert params == {
        "engine": "google_shopping",
        "q": "아이보리 셔츠 상의",
        "gl": "kr",
        "hl": "ko",
        "device": "desktop",
        "no_cache": "false",
    }


def test_default_transport_injects_key_below_httpx_request_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "do-not-log-this-serpapi-key"
    upstream_queries: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        upstream_queries.append(dict(request.url.params))
        return shopping_response()

    service = ShoppingImageService(
        secret,
        transport=httpx.MockTransport(handler),
    )
    caplog.set_level(logging.INFO, logger="httpx")

    result = service.resolve("아이보리 셔츠", "top")

    assert result.status == "found"
    assert upstream_queries[0]["api_key"] == secret
    assert secret not in caplog.text
    assert "api_key" not in caplog.text


def test_only_shopping_results_are_parsed() -> None:
    response = httpx.Response(
        200,
        json={
            "inline_shopping_results": [
                {
                    "title": "아이보리 셔츠",
                    "thumbnail": "https://images.example/ad.webp",
                }
            ]
        },
    )
    http = RecordingHttp(lambda *_: response)
    service = ShoppingImageService("private-key", http=http)

    assert service.resolve("아이보리 셔츠", "top").status == "not_found"


def test_serpapi_thumbnail_is_preferred_and_non_https_urls_are_rejected() -> None:
    preferred = RecordingHttp(lambda *_: shopping_response())
    preferred_service = ShoppingImageService("private-key", http=preferred)
    assert preferred_service.resolve("아이보리 셔츠", "top").url == (
        "https://images.example/serpapi.webp"
    )

    fallback = RecordingHttp(
        lambda *_: shopping_response(
            serpapi_thumbnail="http://images.example/insecure.webp",
            thumbnail="https://images.example/fallback.webp",
            product_link="javascript:alert(1)",
        )
    )
    fallback_service = ShoppingImageService("private-key", http=fallback)
    fallback_result = fallback_service.resolve("차콜 셔츠", "top")
    assert fallback_result.status == "found"
    assert fallback_result.url == "https://images.example/fallback.webp"
    assert fallback_result.source_url is None

    rejected = RecordingHttp(
        lambda *_: shopping_response(
            serpapi_thumbnail="data:image/png;base64,AAAA",
            thumbnail="//images.example/scheme-relative.webp",
        )
    )
    rejected_service = ShoppingImageService("private-key", http=rejected)
    rejected_result = rejected_service.resolve("네이비 셔츠", "top")
    assert rejected_result.status == "not_found"
    assert rejected_result.url is None


def test_candidate_selection_is_deterministic_by_relevance_then_position() -> None:
    response = httpx.Response(
        200,
        json={
            "shopping_results": [
                {
                    "position": 1,
                    "title": "아이보리 로퍼",
                    "thumbnail": "https://images.example/irrelevant.webp",
                },
                {
                    "position": 20,
                    "title": "아이보리 레귤러 셔츠 여성 상의",
                    "thumbnail": "https://images.example/relevant.webp",
                },
                {
                    "position": 21,
                    "title": "아이보리 레귤러 셔츠 상의",
                    "thumbnail": "https://images.example/later-tie.webp",
                },
            ]
        },
    )
    http = RecordingHttp(lambda *_: response)
    service = ShoppingImageService("private-key", http=http)

    result = service.resolve("아이보리 레귤러 셔츠", "top")

    assert result.status == "found"
    assert result.url == "https://images.example/relevant.webp"


@pytest.mark.parametrize(
    ("response", "expected_status"),
    [
        (httpx.Response(500, json={"error": "provider failed"}), "provider_unavailable"),
        (httpx.Response(200, content=b"{"), "provider_unavailable"),
        (httpx.Response(200, json=[]), "provider_unavailable"),
        (httpx.Response(200, json={"error": "rate limited"}), "provider_unavailable"),
        (
            httpx.Response(200, json={"shopping_results": {"title": "not a list"}}),
            "provider_unavailable",
        ),
        (httpx.Response(200, json={}), "not_found"),
        (httpx.Response(200, json={"shopping_results": []}), "not_found"),
    ],
)
def test_malformed_error_and_empty_payloads_are_classified(
    response: httpx.Response,
    expected_status: str,
) -> None:
    http = RecordingHttp(lambda *_: response)
    service = ShoppingImageService("private-key", http=http)

    result = service.resolve("아이보리 셔츠", "top")

    assert result.status == expected_status
    assert result.url is None


@pytest.mark.parametrize(
    ("response", "expected_status", "ttl"),
    [
        (shopping_response(), "found", 11.0),
        (httpx.Response(200, json={"shopping_results": []}), "not_found", 7.0),
        (httpx.Response(503, json={"error": "unavailable"}), "provider_unavailable", 3.0),
    ],
)
def test_status_specific_ttl(
    response: httpx.Response,
    expected_status: str,
    ttl: float,
) -> None:
    clock = FakeClock()
    http = RecordingHttp(lambda *_: response)
    service = ShoppingImageService(
        "private-key",
        http=http,
        clock=clock,
        success_ttl_seconds=11,
        not_found_ttl_seconds=7,
        error_ttl_seconds=3,
    )

    assert service.resolve("아이보리 셔츠", "top").status == expected_status
    clock.advance(ttl - 0.1)
    assert service.resolve("아이보리 셔츠", "top").status == expected_status
    assert len(http.calls) == 1

    clock.advance(0.1)
    assert service.resolve("아이보리 셔츠", "top").status == expected_status
    assert len(http.calls) == 2


def test_cache_is_bounded_and_hits_refresh_lru_order() -> None:
    def handler(url: str, params: dict[str, str], timeout: float) -> httpx.Response:
        del url, timeout
        return shopping_response(title=params["q"])

    http = RecordingHttp(handler)
    service = ShoppingImageService(
        "private-key",
        http=http,
        max_cache_entries=2,
    )

    service.resolve("첫 번째 셔츠", "top")
    service.resolve("두 번째 셔츠", "top")
    service.resolve("첫 번째 셔츠", "top")
    service.resolve("세 번째 셔츠", "top")
    service.resolve("두 번째 셔츠", "top")

    assert [call[1]["q"] for call in http.calls] == [
        "첫 번째 셔츠 상의",
        "두 번째 셔츠 상의",
        "세 번째 셔츠 상의",
        "두 번째 셔츠 상의",
    ]


def test_unicode_case_and_whitespace_normalization_share_a_cache_key() -> None:
    http = RecordingHttp(lambda *_: shopping_response(title="navy 셔츠"))
    service = ShoppingImageService("private-key", http=http)

    first = service.resolve("ＮＡＶＹ   셔츠", "ＴＯＰ")
    second = service.resolve("navy 셔츠", "top")

    assert first == second
    assert len(http.calls) == 1
    assert http.calls[0][1]["q"] == "navy 셔츠 상의"


def test_same_key_concurrent_requests_are_single_flight() -> None:
    provider_started = threading.Event()
    release_provider = threading.Event()
    second_started = threading.Event()

    def handler(url: str, params: dict[str, str], timeout: float) -> httpx.Response:
        del url, params, timeout
        provider_started.set()
        assert release_provider.wait(timeout=2)
        return shopping_response()

    http = RecordingHttp(handler)
    service = ShoppingImageService(
        "private-key",
        http=http,
        timeout_seconds=1,
    )

    def second_call() -> Any:
        second_started.set()
        return service.resolve("아이보리 셔츠", "top")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(service.resolve, "아이보리 셔츠", "top")
        assert provider_started.wait(timeout=1)
        second_future = executor.submit(second_call)
        assert second_started.wait(timeout=1)
        assert len(http.calls) == 1
        release_provider.set()
        first = first_future.result(timeout=2)
        second = second_future.result(timeout=2)

    assert first == second
    assert first.status == "found"
    assert len(http.calls) == 1


def test_provider_exception_does_not_expose_api_key(caplog: pytest.LogCaptureFixture) -> None:
    secret = "do-not-leak-this-serpapi-key"

    def fail_with_secret_url(
        url: str,
        params: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        del timeout
        request = httpx.Request("GET", url, params=params)
        raise httpx.ReadTimeout(f"request failed for {request.url}", request=request)

    http = RecordingHttp(fail_with_secret_url)
    service = ShoppingImageService(secret, http=http)

    result = service.resolve("아이보리 셔츠", "top")

    assert result.status == "provider_unavailable"
    assert secret not in repr(result)
    assert secret not in caplog.text
