"""SerpApi Google Shopping 상품 이미지 조회와 프로세스 로컬 캐시."""

import re
import threading
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx

SERPAPI_SEARCH_ENDPOINT = "https://serpapi.com/search.json"
PROVIDER = "serpapi_google_shopping"
CACHE_VERSION = "v1"
COUNTRY = "kr"
LANGUAGE = "ko"
DEVICE = "desktop"
TOKEN_PATTERN = re.compile(r"[0-9a-zA-Z가-힣]+")

ImageStatus = Literal[
    "found",
    "not_found",
    "provider_unavailable",
    "provider_disabled",
]

SLOT_TERMS: dict[str, tuple[str, ...]] = {
    "top": ("상의", "셔츠", "니트", "티셔츠", "블라우스", "탑"),
    "bottom": ("하의", "팬츠", "바지", "슬랙스", "데님", "스커트"),
    "shoes": ("신발", "슈즈", "스니커즈", "로퍼", "부츠", "샌들"),
    "outer": ("아우터", "재킷", "자켓", "코트", "점퍼", "블루종"),
    "accessory": ("액세서리", "가방", "모자", "벨트", "스카프", "주얼리"),
}


@dataclass(frozen=True)
class ShoppingImageResult:
    """라우트 계층이 외부 응답 세부사항 없이 사용할 안전한 결과."""

    status: ImageStatus
    url: str | None = None
    title: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    provider: str = PROVIDER


@dataclass(frozen=True)
class _CacheEntry:
    result: ShoppingImageResult
    expires_at: float


class _ApiKeyQueryTransport(httpx.BaseTransport):
    """httpx의 상위 요청 로그에 API 키가 남지 않게 전송 직전에만 추가한다."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._transport = transport or httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if (
            request.url.scheme != "https"
            or request.url.host != "serpapi.com"
            or request.url.path != "/search.json"
        ):
            raise httpx.UnsupportedProtocol("SerpApi 고정 엔드포인트만 호출할 수 있습니다.")

        authenticated_request = httpx.Request(
            method=request.method,
            url=request.url.copy_merge_params({"api_key": self._api_key}),
            headers=request.headers,
            content=request.content,
            extensions=request.extensions,
        )
        return self._transport.handle_request(authenticated_request)

    def close(self) -> None:
        self._transport.close()


class ShoppingImageService:
    """동일 검색을 병합하고 결과를 제한된 메모리에 보관한다."""

    def __init__(
        self,
        api_key: str | None,
        *,
        enabled: bool = True,
        timeout_seconds: float = 8.0,
        max_cache_entries: int = 1000,
        success_ttl_seconds: float = 24 * 60 * 60,
        not_found_ttl_seconds: float = 10 * 60,
        error_ttl_seconds: float = 60,
        http: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds는 양수여야 합니다.")
        if max_cache_entries <= 0:
            raise ValueError("max_cache_entries는 양수여야 합니다.")
        if min(success_ttl_seconds, not_found_ttl_seconds, error_ttl_seconds) <= 0:
            raise ValueError("캐시 TTL은 모두 양수여야 합니다.")

        self._api_key = api_key.strip() if isinstance(api_key, str) else ""
        self._enabled = enabled
        self._timeout_seconds = timeout_seconds
        self._max_cache_entries = max_cache_entries
        self._success_ttl_seconds = success_ttl_seconds
        self._not_found_ttl_seconds = not_found_ttl_seconds
        self._error_ttl_seconds = error_ttl_seconds
        if http is not None and transport is not None:
            raise ValueError("http와 transport를 동시에 지정할 수 없습니다.")
        self._http = http or httpx.Client(
            transport=_ApiKeyQueryTransport(self._api_key, transport=transport),
            follow_redirects=False,
        )
        self._clock = clock
        self._cache: OrderedDict[tuple[str, ...], _CacheEntry] = OrderedDict()
        self._inflight: dict[tuple[str, ...], threading.Event] = {}
        self._lock = threading.Lock()

    def resolve(self, name: str, slot: str) -> ShoppingImageResult:
        """서버가 검증한 의류 이름과 슬롯으로 상품 이미지 하나를 선택한다."""
        if not self._enabled or not self._api_key:
            return ShoppingImageResult(status="provider_disabled")

        normalized_name = _normalize_text(name)
        normalized_slot = _normalize_text(slot)
        if not normalized_name or normalized_slot not in SLOT_TERMS:
            return ShoppingImageResult(status="not_found")

        key = (
            CACHE_VERSION,
            PROVIDER,
            COUNTRY,
            LANGUAGE,
            normalized_slot,
            normalized_name,
        )
        owner, event, cached = self._claim(key)
        if cached is not None:
            return cached
        if not owner:
            event.wait(timeout=self._timeout_seconds + 1)
            with self._lock:
                cached = self._get_cached_locked(key)
            return cached or ShoppingImageResult(status="provider_unavailable")

        result = ShoppingImageResult(status="provider_unavailable")
        try:
            result = self._search(normalized_name, normalized_slot)
        except Exception:
            # API 키가 포함된 요청 객체나 원본 응답을 상위 계층에 노출하지 않는다.
            result = ShoppingImageResult(status="provider_unavailable")
        finally:
            with self._lock:
                self._store_locked(key, result)
                completed = self._inflight.pop(key, None)
                if completed is not None:
                    completed.set()
        return result

    def _claim(
        self,
        key: tuple[str, ...],
    ) -> tuple[bool, threading.Event, ShoppingImageResult | None]:
        with self._lock:
            cached = self._get_cached_locked(key)
            if cached is not None:
                return False, threading.Event(), cached
            event = self._inflight.get(key)
            if event is not None:
                return False, event, None
            event = threading.Event()
            self._inflight[key] = event
            return True, event, None

    def _get_cached_locked(self, key: tuple[str, ...]) -> ShoppingImageResult | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return entry.result

    def _store_locked(self, key: tuple[str, ...], result: ShoppingImageResult) -> None:
        self._cache[key] = _CacheEntry(
            result=result,
            expires_at=self._clock() + self._ttl_for(result.status),
        )
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_cache_entries:
            self._cache.popitem(last=False)

    def _ttl_for(self, status: ImageStatus) -> float:
        if status == "found":
            return self._success_ttl_seconds
        if status == "not_found":
            return self._not_found_ttl_seconds
        return self._error_ttl_seconds

    def _search(self, name: str, slot: str) -> ShoppingImageResult:
        params = {
            "engine": "google_shopping",
            "q": f"{name} {SLOT_TERMS[slot][0]}",
            "gl": COUNTRY,
            "hl": LANGUAGE,
            "device": DEVICE,
            "no_cache": "false",
        }
        try:
            response = self._http.get(
                SERPAPI_SEARCH_ENDPOINT,
                params=params,
                timeout=self._timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.RequestError):
            return ShoppingImageResult(status="provider_unavailable")
        if not response.is_success:
            return ShoppingImageResult(status="provider_unavailable")

        try:
            payload = response.json()
        except ValueError:
            return ShoppingImageResult(status="provider_unavailable")
        if not isinstance(payload, dict) or isinstance(payload.get("error"), str):
            return ShoppingImageResult(status="provider_unavailable")

        raw_results = payload.get("shopping_results")
        if raw_results is None:
            return ShoppingImageResult(status="not_found")
        if not isinstance(raw_results, list):
            return ShoppingImageResult(status="provider_unavailable")

        selected = _select_candidate(raw_results, name, slot)
        return selected or ShoppingImageResult(status="not_found")


def _normalize_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _https_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return normalized


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _select_candidate(
    raw_results: list[object],
    name: str,
    slot: str,
) -> ShoppingImageResult | None:
    query_tokens = set(TOKEN_PATTERN.findall(_normalize_text(name)))
    candidates: list[tuple[int, int, str, ShoppingImageResult]] = []

    for fallback_position, raw in enumerate(raw_results, start=1):
        if not isinstance(raw, dict):
            continue
        image_url = _https_url(raw.get("serpapi_thumbnail")) or _https_url(raw.get("thumbnail"))
        if image_url is None:
            continue

        title = _optional_text(raw.get("title"))
        normalized_title = _normalize_text(title)
        title_tokens = set(TOKEN_PATTERN.findall(normalized_title))
        token_score = len(query_tokens & title_tokens)
        slot_score = 2 if any(term in normalized_title for term in SLOT_TERMS[slot]) else 0
        position = raw.get("position")
        if not isinstance(position, int) or isinstance(position, bool) or position <= 0:
            position = fallback_position

        result = ShoppingImageResult(
            status="found",
            url=image_url,
            title=title,
            source_name=_optional_text(raw.get("source")),
            source_url=_https_url(raw.get("product_link")),
        )
        candidates.append((-(token_score + slot_score), position, title or "", result))

    if not candidates:
        return None
    candidates.sort(key=lambda candidate: (candidate[0], candidate[1], candidate[2]))
    return candidates[0][3]
