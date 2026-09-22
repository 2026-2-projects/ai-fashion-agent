"""Kakao keyword search adapter; x is longitude, y is latitude."""

import httpx
from pydantic import BaseModel, Field


class KakaoLocalError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class Place(BaseModel):
    id: str
    place_name: str
    address_name: str
    road_address_name: str
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    place_url: str


class SearchMeta(BaseModel):
    total_count: int = Field(ge=0)
    pageable_count: int = Field(ge=0)
    is_end: bool


class PlaceSearchResult(BaseModel):
    places: list[Place]
    meta: SearchMeta


class KakaoLocalClient:
    def __init__(self, http: httpx.AsyncClient, api_key: str) -> None:
        self.http = http
        self.api_key = api_key.strip()

    async def search_places(
        self, query: str, page: int = 1, size: int = 5
    ) -> PlaceSearchResult:
        query = query.strip()
        if not query or not 1 <= page <= 45 or not 1 <= size <= 15:
            raise ValueError("query must be nonblank; page: 1..45; size: 1..15")
        if not self.api_key:
            raise KakaoLocalError(503, "Kakao Local API key is not configured")
        try:
            response = await self.http.get(
                "https://dapi.kakao.com/v2/local/search/keyword.json",
                headers={"Authorization": f"KakaoAK {self.api_key}"},
                params={"query": query, "page": page, "size": size},
                timeout=10.0,
            )
        except httpx.TimeoutException as exc:
            raise KakaoLocalError(504, "Kakao Local API request timed out") from exc
        except httpx.RequestError as exc:
            raise KakaoLocalError(502, "Kakao Local API connection failed") from exc

        if response.status_code in (401, 403):
            raise KakaoLocalError(503, "Kakao Local API authentication or permission failed")
        if response.status_code == 429:
            raise KakaoLocalError(503, "Kakao Local API quota exceeded")
        if not response.is_success:
            raise KakaoLocalError(502, "Kakao Local API request failed")
        try:
            data = response.json()
            places = [
                Place(
                    id=item["id"],
                    place_name=item["place_name"],
                    address_name=item["address_name"],
                    road_address_name=item["road_address_name"],
                    longitude=item["x"],
                    latitude=item["y"],
                    place_url=item["place_url"],
                )
                for item in data["documents"]
            ]
            return PlaceSearchResult(places=places, meta=SearchMeta.model_validate(data["meta"]))
        except (ValueError, KeyError, TypeError) as exc:
            raise KakaoLocalError(502, "Kakao Local API returned an invalid response") from exc
