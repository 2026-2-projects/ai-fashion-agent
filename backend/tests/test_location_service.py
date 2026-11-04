import httpx
import pytest

from app.services.errors import AmbiguousPlaceError, ExternalServiceError, PlaceNotFoundError
from app.services.location import KakaoLocalClient


def _client(payload: dict, status_code: int = 200) -> KakaoLocalClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "KakaoAK test-key"
        return httpx.Response(status_code, json=payload)

    return KakaoLocalClient(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _document(name: str, address: str, *, place_id: str = "1") -> dict[str, str]:
    return {
        "id": place_id,
        "place_name": name,
        "address_name": address,
        "road_address_name": "",
        "x": "127.08988123196553",
        "y": "35.81411422757866",
    }


def test_resolve_exact_place_from_multiple_search_results() -> None:
    client = _client(
        {
            "documents": [
                _document("전주대학교", "전북 전주시 완산구", place_id="1"),
                _document("전주대학교 스타센터", "전북 전주시 완산구", place_id="2"),
            ]
        }
    )

    place = client.resolve_place(" 전주대학교 ")

    assert place.name == "전주대학교"
    assert place.latitude == pytest.approx(35.81411422757866)
    assert place.longitude == pytest.approx(127.08988123196553)


def test_no_result_and_same_name_are_not_guessed() -> None:
    with pytest.raises(PlaceNotFoundError):
        _client({"documents": []}).resolve_place("없는 장소")

    client = _client(
        {
            "documents": [
                _document("중앙공원", "전북 전주시", place_id="1"),
                _document("중앙공원", "경기 성남시", place_id="2"),
            ]
        }
    )
    with pytest.raises(AmbiguousPlaceError) as exc_info:
        client.resolve_place("중앙공원")
    assert [candidate["address"] for candidate in exc_info.value.candidates] == [
        "전북 전주시",
        "경기 성남시",
    ]


def test_upstream_error_is_sanitized() -> None:
    with pytest.raises(ExternalServiceError) as exc_info:
        _client({"error": "unauthorized"}, status_code=401).search_places("전주대학교")
    assert "test-key" not in str(exc_info.value)
