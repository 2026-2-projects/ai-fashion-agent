import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.v1.places import get_kakao_client
from app.main import app
from app.services.kakao_local import KakaoLocalClient, KakaoLocalError


def payload() -> dict:
    return {
        "documents": [{
            "id": "123", "place_name": "서울역", "address_name": "서울 용산구",
            "road_address_name": "서울 용산구 한강대로 405",
            "x": "126.9706", "y": "37.5547", "place_url": "http://place.map.kakao.com/123",
        }],
        "meta": {"total_count": 1, "pageable_count": 1, "is_end": True},
    }


def run_search(handler, key="test-key", **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await KakaoLocalClient(http, key).search_places(**kwargs)
    return asyncio.run(run())


def test_search_request_and_coordinates():
    def handler(request):
        assert request.url.path == "/v2/local/search/keyword.json"
        assert request.headers["Authorization"] == "KakaoAK test-key"
        assert dict(request.url.params) == {"query": "서울역", "page": "2", "size": "3"}
        return httpx.Response(200, json=payload())

    result = run_search(handler, query=" 서울역 ", page=2, size=3)
    assert result.places[0].longitude == 126.9706
    assert result.places[0].latitude == 37.5547
    assert result.meta.is_end is True


def test_empty_results():
    data = payload()
    data["documents"] = []
    data["meta"].update(total_count=0, pageable_count=0)
    result = run_search(lambda _: httpx.Response(200, json=data), query="없는장소")
    assert result.places == []


@pytest.mark.parametrize("status,expected", [(401, 503), (403, 503), (429, 503), (500, 502)])
def test_upstream_error_is_sanitized(status, expected):
    with pytest.raises(KakaoLocalError) as error:
        run_search(lambda _: httpx.Response(status, text="secret upstream body"), query="서울역")
    assert error.value.status_code == expected
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("exc,expected", [(httpx.ReadTimeout, 504), (httpx.ConnectError, 502)])
def test_network_errors(exc, expected):
    def handler(request):
        raise exc("secret", request=request)
    with pytest.raises(KakaoLocalError) as error:
        run_search(handler, query="서울역")
    assert error.value.status_code == expected


@pytest.mark.parametrize("body", ["not-json", '{}', '{"documents":null}', '[]'])
def test_malformed_response(body):
    with pytest.raises(KakaoLocalError) as error:
        run_search(lambda _: httpx.Response(200, text=body), query="서울역")
    assert error.value.status_code == 502


def test_missing_key_does_not_call_kakao():
    def handler(_):
        pytest.fail("Must not call Kakao without a key")
    with pytest.raises(KakaoLocalError) as error:
        run_search(handler, key=" ", query="서울역")
    assert error.value.status_code == 503


@pytest.mark.parametrize("params", [{}, {"query": " "}, {"query": "a", "page": 46},
                                    {"query": "a", "size": 16}])
def test_route_validation(params):
    with TestClient(app) as client:
        assert client.get("/api/v1/places/search", params=params).status_code == 422


def test_route_success():
    async def override():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload()))
        ) as http:
            yield KakaoLocalClient(http, "test-key")
    app.dependency_overrides[get_kakao_client] = override
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/places/search", params={"query": "서울역"})
        assert response.status_code == 200
        assert response.json()["places"][0]["latitude"] == 37.5547
    finally:
        app.dependency_overrides.pop(get_kakao_client)


def test_route_missing_key(monkeypatch):
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    with TestClient(app) as client:
        response = client.get("/api/v1/places/search", params={"query": "서울역"})
    assert response.status_code == 503
