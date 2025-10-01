# Copyright 2025 Team Aeris
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from core.dependencies import (
    get_logger_service,
    get_app_search_service,
    get_search_service,
    limiter,
)
from api.v1.application.search.search_provider import SearchProvider as SearchService


search_titles_router = APIRouter(prefix="/search", tags=["title"])


@search_titles_router.get(
    path="/title",
    response_model=dict,
    responses={status.HTTP_500_INTERNAL_SERVER_ERROR: {"description": "Server error"}},
    description="제목으로 공공데이터 검색 (생성된 문서가 있는 API/File, 엔드포인트 설명 포함)",
)
@limiter.limit("60/minute")
async def search_titles(
    request: Request,
    query: List[str] = Query(..., description="검색할 키워드"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(10, ge=1, le=100, description="페이지 크기"),
    search_service: SearchService = Depends(get_search_service),
    search_app_service=Depends(get_app_search_service),
    logger: logging.Logger = Depends(lambda: get_logger_service("search_titles")),
):
    try:
        res = await search_app_service.search_titles_with_docs_multi(
            queries=query, page=page, page_size=page_size, search_service=search_service
        )
        logger.info(
            f"[Search/Titles] 검색 완료: 검색어={query}, 결과 {len(res['results'])}개, 총 {res['total']}개"
        )
        return res
    except Exception as e:
        logger.exception(f"[Search/Titles] 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
