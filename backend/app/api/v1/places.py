import os
from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.kakao_local import KakaoLocalClient, KakaoLocalError, PlaceSearchResult

router = APIRouter(prefix="/places", tags=["Places"])


async def get_kakao_client() -> AsyncIterator[KakaoLocalClient]:
    async with httpx.AsyncClient() as http:
        yield KakaoLocalClient(http, os.environ.get("KAKAO_REST_API_KEY", ""))


@router.get("/search", response_model=PlaceSearchResult)
async def search_places(
    query: Annotated[str, Query(min_length=1)],
    client: Annotated[KakaoLocalClient, Depends(get_kakao_client)],
    page: Annotated[int, Query(ge=1, le=45)] = 1,
    size: Annotated[int, Query(ge=1, le=15)] = 5,
) -> PlaceSearchResult:
    if not query.strip():
        raise HTTPException(status_code=422, detail="query must not be blank")
    try:
        return await client.search_places(query, page, size)
    except KakaoLocalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
