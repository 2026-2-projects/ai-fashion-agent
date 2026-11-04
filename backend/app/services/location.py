"""Kakao Local API를 이용한 장소 검색과 단일 장소 결정."""

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import KAKAO_REST_API_KEY
from app.services.errors import (
    AmbiguousPlaceError,
    ExternalServiceError,
    PlaceNotFoundError,
    ServiceConfigurationError,
    WeatherInputError,
)

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


@dataclass(frozen=True)
class Place:
    place_id: str
    name: str
    address: str
    road_address: str
    latitude: float
    longitude: float

    def public_candidate(self) -> dict[str, str]:
        """좌표와 외부 키를 제외한 사용자 확인용 후보."""
        return {
            "name": self.name,
            "address": self.road_address or self.address,
        }


def _normalized_name(value: str) -> str:
    return "".join(value.split()).casefold()


class KakaoLocalClient:
    def __init__(
        self,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else KAKAO_REST_API_KEY
        self.http_client = http_client

    def search_places(self, query: str, *, size: int = 5) -> list[Place]:
        query = query.strip()
        if not query:
            raise WeatherInputError("장소를 입력해 주세요.")
        if len(query) > 100:
            raise WeatherInputError("장소는 100자 이하로 입력해 주세요.")
        if not self.api_key:
            raise ServiceConfigurationError("Kakao Local API 설정이 필요합니다.")

        try:
            if self.http_client is None:
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(
                        KAKAO_KEYWORD_URL,
                        headers={"Authorization": f"KakaoAK {self.api_key}"},
                        params={"query": query, "size": size, "sort": "accuracy"},
                    )
            else:
                response = self.http_client.get(
                    KAKAO_KEYWORD_URL,
                    headers={"Authorization": f"KakaoAK {self.api_key}"},
                    params={"query": query, "size": size, "sort": "accuracy"},
                )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            # 원본 예외에는 요청 정보가 포함될 수 있으므로 API 키 노출을 막기 위해 전달하지 않는다.
            raise ExternalServiceError("장소 검색 서비스 응답을 확인할 수 없습니다.") from None

        documents = payload.get("documents") if isinstance(payload, dict) else None
        if not isinstance(documents, list):
            raise ExternalServiceError("장소 검색 서비스 응답 형식이 올바르지 않습니다.")

        places: list[Place] = []
        for document in documents:
            place = self._parse_place(document)
            if place is not None:
                places.append(place)
        return places

    def resolve_place(self, query: str) -> Place:
        places = self.search_places(query)
        if not places:
            raise PlaceNotFoundError("검색된 장소가 없습니다.")

        normalized_query = _normalized_name(query)
        exact = [place for place in places if _normalized_name(place.name) == normalized_query]
        if len(exact) == 1:
            return exact[0]

        candidates = exact if len(exact) > 1 else places
        if len(candidates) > 1:
            raise AmbiguousPlaceError([place.public_candidate() for place in candidates])
        return candidates[0]

    @staticmethod
    def _parse_place(document: Any) -> Place | None:
        if not isinstance(document, dict):
            return None
        try:
            latitude = float(document["y"])
            longitude = float(document["x"])
            name = str(document["place_name"]).strip()
        except (KeyError, TypeError, ValueError):
            return None
        if not name or not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            return None
        return Place(
            place_id=str(document.get("id", "")),
            name=name,
            address=str(document.get("address_name", "")),
            road_address=str(document.get("road_address_name", "")),
            latitude=latitude,
            longitude=longitude,
        )
