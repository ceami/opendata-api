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
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from api.v1.application.open_data.dto import UnifiedDataItemDTO, PaginatedUnifiedDataDTO
from core.dependencies import (
    get_cross_collection_service,
    get_logger_service,
    get_app_search_service,
    get_app_pagination_service,
    get_search_service,
    limiter,
)
from models import GeneratedAPIDocs, GeneratedFileDocs
from utils.datetime_util import format_datetime


list_router = APIRouter(prefix="/document", tags=["list"])


@list_router.get(
    path="",
    response_model=dict[str, Any],
    responses={status.HTTP_500_INTERNAL_SERVER_ERROR: {"description": "Server error"}},
    description="opendata-web용 통합 API - 검색 / 목록 제공 (API + File)",
)
@limiter.limit("60/minute")
async def get_list(
    request: Request,
    q: str | None = Query(None, description="검색 키워드"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    size: int = Query(20, ge=1, le=100, description="페이지 크기"),
    sort_by: str = Query("popular", description="정렬 기준 (popular/trending)"),
    name_sort_by: str = Query("all"),
    org_sort_by: str = Query("all"),
    data_type_sort_by: str = Query("all"),
    token_count_sort_by: str = Query("all"),
    status_sort_by: str = Query("all"),
    exact_match: bool = Query(False, description="정확한 매칭 여부"),
    min_score: float | None = Query(None, description="최소 점수 필터링"),
    use_adaptive_filtering: bool = Query(True, description="자동 필터링 사용"),
    cross_collection_service=Depends(get_cross_collection_service),
    search_app_service=Depends(get_app_search_service),
    pagination_service=Depends(get_app_pagination_service),
    search_service=Depends(get_search_service),
    logger: logging.Logger = Depends(lambda: get_logger_service("document_list")),
):
    try:
        if q and q.strip():
            logger.info(f"[Document/List] 검색 요청: 검색어='{q.strip()}', page={page}, size={size}")
            search_result = await search_app_service.get_frontend_data_search(
                q=q,
                page=page,
                size=size,
                exact_match=exact_match,
                min_score=min_score,
                use_adaptive_filtering=use_adaptive_filtering,
                search_service=search_service,
            )

            total = search_result.get("total", 0)
            items_data = search_result.get("items", [])
            total_pages = (total + size - 1) // size if size > 0 else 0

            if page > total_pages and total_pages > 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"페이지 번호가 범위를 초과했습니다. (요청: {page}, 최대: {total_pages})"
                )

            dto_result = PaginatedUnifiedDataDTO(
                items=[UnifiedDataItemDTO(**item) for item in items_data],
                total=total,
                page=page,
                size=size,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_prev=page > 1,
            )
            return dto_result.model_dump(by_alias=True)

        if sort_by not in ["popular", "trending", "all"]:
            raise HTTPException(status_code=400, detail="sort_by는 'popular' 또는 'trending'이어야 합니다")

        rank_sort_by = "popular" if sort_by == "all" else sort_by
        rank_result = await cross_collection_service.get_ranked_snapshots(sort_by=rank_sort_by, page=page, size=size)

        if rank_result.get("redirect_to_original"):
            logger.info(f"[Document/List] 스냅샷 한계, fallback: page={page}, size={size}")

            consistent_total = rank_result.get("total")

            dto = await pagination_service.get_unified_data_paginated(
                page=page,
                size=size,
                sort_by=sort_by,
                name_sort_by=name_sort_by,
                org_sort_by=org_sort_by,
                data_type_sort_by=data_type_sort_by,
                token_count_sort_by=token_count_sort_by,
                status_sort_by=status_sort_by,
            )

            final_total = consistent_total if consistent_total else dto.total
            total_pages = (final_total + dto.size - 1) // dto.size if dto.size > 0 else 0

            if page > total_pages and total_pages > 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"페이지 번호가 범위를 초과했습니다. (요청: {page}, 최대: {total_pages})"
                )

            formatted_items = []
            for item in dto.items:
                list_id = item.list_id
                data_type = item.data_type

                generated_at = None
                if data_type == "API":
                    api_doc = await GeneratedAPIDocs.find_one({"list_id": list_id})
                    if api_doc:
                        generated_at = getattr(api_doc, "generated_at", None)
                else:
                    file_doc = await GeneratedFileDocs.find_one({"list_id": list_id})
                    if file_doc:
                        generated_at = getattr(file_doc, "generated_at", None)

                generated_at_str = format_datetime(generated_at) if generated_at else None

                formatted_items.append(
                    {
                        "list_id": list_id,
                        "list_title": item.list_title or item.title,
                        "org_nm": item.org_nm or item.department,
                        "token_count": item.token_count,
                        "has_generated_doc": item.has_generated_doc,
                        "updated_at": generated_at_str,
                        "data_type": data_type,
                        "score": None,
                    }
                )

            dto_result = PaginatedUnifiedDataDTO(
                items=[UnifiedDataItemDTO(**i) for i in formatted_items],
                total=final_total,
                page=dto.page,
                size=dto.size,
                total_pages=total_pages,
                has_next=dto.page < total_pages,
                has_prev=dto.page > 1,
            )
            return dto_result.model_dump(by_alias=True)

        formatted_items = []
        for item in rank_result["data"]:
            formatted_items.append(
                {
                    "list_id": item.get("list_id"),
                    "list_title": item.get("list_title", ""),
                    "org_nm": item.get("org_nm"),
                    "token_count": item.get("token_count", 0),
                    "has_generated_doc": item.get("has_generated_doc", False),
                    "updated_at": None,
                    "data_type": item.get("data_type", "API"),
                    "score": None,
                }
            )

        total = rank_result["total"]
        page = rank_result["page"]
        size = rank_result["size"]
        total_pages = (total + size - 1) // size if size > 0 else 0

        if page > total_pages and total_pages > 0:
            raise HTTPException(
                status_code=400,
                detail=f"페이지 번호가 범위를 초과했습니다. (요청: {page}, 최대: {total_pages})"
            )

        dto_result = PaginatedUnifiedDataDTO(
            items=[UnifiedDataItemDTO(**i) for i in formatted_items],
            total=total,
            page=page,
            size=size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1,
        )
        return dto_result.model_dump(by_alias=True)
    except Exception as e:
        logger.exception(f"[Document/List] 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
