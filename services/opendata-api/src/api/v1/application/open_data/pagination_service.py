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
from dataclasses import asdict
from typing import Any

from api.v1.application.open_data.dto import (
    PaginatedUnifiedDataDTO,
    UnifiedDataItemDTO,
)
from models import GeneratedAPIDocs, GeneratedFileDocs
from utils.datetime_util import format_datetime


class PaginationAppService:
    def __init__(self, cross_collection_service: Any):
        self._svc = cross_collection_service

    async def get_rank_or_fallback(
        self,
        *,
        page: int,
        size: int,
        sort_by: str,
        name_sort_by: str,
        org_sort_by: str,
        data_type_sort_by: str,
        token_count_sort_by: str,
        status_sort_by: str,
        fetch_generated_at: Any,
    ) -> dict[str, Any]:
        rank_sort_by = "popular" if sort_by == "all" else sort_by
        rank_result = await self._svc.get_ranked_snapshots(
            sort_by=rank_sort_by, page=page, size=size
        )

        if rank_result.get("redirect_to_original"):
            result = await self._svc.get_unified_data_paginated(
                page=page,
                size=size,
                sort_by=sort_by,
                name_sort_by=name_sort_by,
                org_sort_by=org_sort_by,
                data_type_sort_by=data_type_sort_by,
                token_count_sort_by=token_count_sort_by,
                status_sort_by=status_sort_by,
            )

            items: list[dict[str, Any]] = []
            for item in result["data"]:
                list_id = item.get("list_id")
                data_type = item.get("data_type", "API")
                generated_at = await fetch_generated_at(
                    list_id=list_id, data_type=data_type
                )

                items.append(
                    {
                        "list_id": list_id,
                        "list_title": item.get("list_title", ""),
                        "org_nm": item.get("org_nm"),
                        "token_count": item.get("token_count", 0),
                        "has_generated_doc": item.get(
                            "has_generated_doc", False
                        ),
                        "updated_at": generated_at,
                        "data_type": data_type,
                        "score": None,
                    }
                )

            return {
                "items": items,
                "total": result["total"],
                "page": result["page"],
                "size": result["size"],
            }

        items = []
        for item in rank_result["data"]:
            items.append(
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

        return {
            "items": items,
            "total": rank_result["total"],
            "page": rank_result["page"],
            "size": rank_result["size"],
        }

    async def get_unified_data_paginated(
        self, **kwargs
    ) -> PaginatedUnifiedDataDTO:
        """통합 데이터 페이지네이션 조회"""
        result = await self._svc.get_unified_data_paginated(**kwargs)
        items = []
        for item in result.get("data", []):
            if hasattr(item, "__dataclass_fields__"):
                item = asdict(item)
            items.append(UnifiedDataItemDTO(**item))
        total = result.get("total", 0)
        page = result.get("page", 1)
        size = result.get("size", 10)
        total_pages = (total + size - 1) // size if size > 0 else 0
        has_next = page < total_pages
        has_prev = page > 1

        return PaginatedUnifiedDataDTO(
            items=items,
            total=total,
            page=page,
            size=size,
            total_pages=total_pages,
            has_next=has_next,
            has_prev=has_prev,
        )

    async def get_frontend_data_list(
        self,
        *,
        page: int,
        size: int,
        sort_by: str,
        name_sort_by: str,
        org_sort_by: str,
        data_type_sort_by: str,
        token_count_sort_by: str,
        status_sort_by: str,
    ) -> dict[str, Any]:
        """프론트엔드 데이터 목록 조회 (스냅샷 우선)"""
        rank_result = await self._svc.get_ranked_snapshots(
            sort_by=("popular" if sort_by == "all" else sort_by),
            page=page,
            size=size,
        )
        if rank_result.get("redirect_to_original"):
            result = await self._svc.get_unified_data_paginated(
                page=page,
                size=size,
                sort_by=sort_by,
                name_sort_by=name_sort_by,
                org_sort_by=org_sort_by,
                data_type_sort_by=data_type_sort_by,
                token_count_sort_by=token_count_sort_by,
                status_sort_by=status_sort_by,
            )

            items: list[dict[str, Any]] = []
            for item in result["data"]:
                list_id = item.get("list_id")
                data_type = item.get("data_type", "API")

                generated_at = None
                if data_type == "API":
                    api_doc = await GeneratedAPIDocs.find_one(
                        {"list_id": list_id}
                    )
                    if api_doc:
                        generated_at = getattr(api_doc, "generated_at", None)
                else:
                    file_doc = await GeneratedFileDocs.find_one(
                        {"list_id": list_id}
                    )
                    if file_doc:
                        generated_at = getattr(file_doc, "generated_at", None)

                items.append(
                    {
                        "list_id": list_id,
                        "list_title": item.get("list_title", ""),
                        "org_nm": item.get("org_nm"),
                        "token_count": item.get("token_count", 0),
                        "has_generated_doc": item.get(
                            "has_generated_doc", False
                        ),
                        "updated_at": format_datetime(generated_at),
                        "data_type": data_type,
                        "score": None,
                    }
                )

            return {
                "items": items,
                "total": result["total"],
                "page": result["page"],
                "size": result["size"],
            }

        items = []
        for item in rank_result["data"]:
            items.append(
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

        return {
            "items": items,
            "total": rank_result["total"],
            "page": rank_result["page"],
            "size": rank_result["size"],
        }
