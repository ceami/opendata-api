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
import asyncio
import logging
from typing import Any, Dict, List

from motor.motor_asyncio import AsyncIOMotorClient

from models import (
    GeneratedAPIDocs,
    GeneratedFileDocs,
    OpenAPIInfo,
    OpenFileInfo,
)
from schemas.response import (
    UnifiedDataItem,
    calculate_offset,
    validate_pagination_params,
)


class CrossCollectionService:
    def __init__(
        self, mongo_client: AsyncIOMotorClient, logger: logging.Logger = None
    ):
        self.mongo_client = mongo_client
        self.open_data_db = self.mongo_client.open_data
        self.odm_db = self.mongo_client.odm
        self.logger = logger or logging.getLogger(__name__)

    async def get_unified_search_data(
        self, query: str, page: int = 1, size: int = 20, search_service=None
    ) -> Dict[str, Any]:
        try:
            page, size = validate_pagination_params(page, size)
            offset = calculate_offset(page, size)

            list_ids = await self._get_search_list_ids(
                query, size, search_service
            )

            api_data = await self._get_api_data(list_ids)
            file_data = await self._get_file_data(list_ids)

            all_data = api_data + file_data
            all_data.sort(key=lambda x: x.request_cnt, reverse=True)

            start_idx = offset
            end_idx = start_idx + size
            paginated_data = all_data[start_idx:end_idx]

            return {
                "data": [item.model_dump() for item in paginated_data],
                "total": len(all_data),
                "page": page,
                "size": size,
            }

        except Exception as e:
            raise e

    async def _get_search_list_ids(
        self, query: str, size: int, search_service
    ) -> List[str]:
        if not search_service:
            return []

        search_size = max(size * 3, 10)
        hits = search_service.search_titles(
            query=query, size=search_size, from_=0
        )
        return [hit["_source"].get("list_id") for hit in hits["hits"]]

    async def _get_api_data(self, list_ids: List[str]) -> List[UnifiedDataItem]:
        if not list_ids:
            return []

        api_list_ids = self._convert_to_int_list_ids(list_ids)
        if not api_list_ids:
            return []

        api_docs = await OpenAPIInfo.find(
            {"list_id": {"$in": api_list_ids}}
        ).to_list()

        api_data = []
        for doc in api_docs:
            generated_doc = await GeneratedAPIDocs.find_one(
                {"list_id": doc.list_id}
            )

            item = UnifiedDataItem(
                list_id=doc.list_id,
                title=doc.list_title,
                description=doc.desc,
                department=doc.dept_nm or "",
                category=doc.category_nm,
                data_type="API",
                data_format=doc.data_format,
                pricing=doc.is_charged,
                copyright=doc.is_copyrighted,
                third_party_copyright=doc.is_third_party_copyrighted,
                keywords=doc.keywords if isinstance(doc.keywords, list) else [],
                register_status=doc.register_status or "",
                request_cnt=doc.request_cnt,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
                use_prmisn_ennc=doc.use_prmisn_ennc,
                title_en=doc.title_en,
                api_type=doc.api_type,
                endpoints=None,
                has_generated_doc=generated_doc is not None,
                token_count=generated_doc.token_count if generated_doc else 0,
                score=None,
            )
            api_data.append(item)

        return api_data

    async def _get_file_data(
        self, list_ids: List[str]
    ) -> List[UnifiedDataItem]:
        """파일 데이터를 조회하여 UnifiedDataItem으로 변환"""
        if not list_ids:
            return []

        file_docs = await OpenFileInfo.find(
            {"list_id": {"$in": list_ids}}
        ).to_list()

        file_data = []
        for doc in file_docs:
            generated_doc = await GeneratedFileDocs.find_one(
                {"list_id": doc.list_id}
            )

            item = UnifiedDataItem(
                list_id=int(doc.list_id) if doc.list_id else 0,
                title=doc.list_title or doc.title or "",
                description=doc.desc or "",
                department=doc.org_nm or doc.dept_nm or "",
                category=doc.new_category_nm or "",
                data_type="FILE",
                data_format=doc.data_type or "",
                pricing=doc.is_charged,
                copyright=doc.is_copyrighted,
                third_party_copyright=doc.is_third_party_copyrighted or "",
                keywords=doc.keywords if isinstance(doc.keywords, list) else [],
                register_status=doc.register_status or "",
                request_cnt=doc.download_cnt or 0,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
                use_prmisn_ennc=doc.ownership_grounds or "",
                title_en=None,
                api_type="FILE",
                endpoints=None,
                has_generated_doc=generated_doc is not None,
                token_count=generated_doc.token_count if generated_doc else 0,
                score=None,
            )
            file_data.append(item)

        return file_data

    def _convert_to_int_list_ids(self, list_ids: List[str]) -> List[int]:
        """문자열 list_id를 정수로 변환"""
        api_list_ids = []
        for lid in list_ids:
            try:
                if isinstance(lid, str):
                    if lid.isdigit():
                        api_list_ids.append(int(lid))
                elif isinstance(lid, int):
                    api_list_ids.append(lid)
            except (ValueError, AttributeError):
                continue
        return api_list_ids

    async def get_unified_data_paginated(
        self,
        page: int = 1,
        size: int = 10,
        sort_by: str = "popular",
        name_sort_by: str = "all",
        org_sort_by: str = "all",
        data_type_sort_by: str = "all",
        token_count_sort_by: str = "all",
        status_sort_by: str = "all",
    ) -> Dict[str, Any]:
        """페이지네이션된 통합 데이터를 조회"""
        try:
            self.logger.info(
                f"[CrossCollectionService] 데이터 조회 시작: page={page}, size={size}"
            )
            page, size = validate_pagination_params(page, size)
            offset = calculate_offset(page, size)
            sort_field = "request_cnt" if sort_by == "popular" else "updated_at"
            sort_order = -1

            sort_conditions = self._build_sort_conditions(
                name_sort_by,
                org_sort_by,
                data_type_sort_by,
                token_count_sort_by,
                status_sort_by,
                sort_field,
                sort_order,
            )

            api_pipeline = self._build_api_pipeline(sort_conditions)
            file_pipeline = self._build_file_pipeline(sort_conditions, sort_by)

            self.logger.info(
                "[CrossCollectionService] MongoDB Aggregation 실행 시작"
            )

            api_result, file_result = await asyncio.gather(
                self.open_data_db.open_data_info.aggregate(
                    api_pipeline
                ).to_list(),
                self.open_data_db.open_file_info.aggregate(
                    file_pipeline
                ).to_list(),
            )

            api_data = api_result if api_result else []
            file_data = file_result if file_result else []

            self._log_data_samples(api_data, file_data)
            self._normalize_request_counts(api_data, file_data)

            unique_data = self._merge_and_deduplicate_data(api_data, file_data)
            unique_data.sort(
                key=lambda x: x.get("request_cnt", 0), reverse=True
            )

            start_idx = offset
            end_idx = start_idx + size
            paginated_data = unique_data[start_idx:end_idx]

            total_count = len(unique_data)

            self.logger.info(
                f"[CrossCollectionService] 조회 완료: API={len(api_data)}개, "
                f"File={len(file_data)}개, 총 {len(paginated_data)}개 반환"
            )

            return {
                "data": paginated_data,
                "total": total_count,
                "page": page,
                "size": size,
            }

        except Exception as e:
            self.logger.error(
                f"[CrossCollectionService] 데이터 조회 오류: {str(e)}"
            )
            raise e

    def _build_sort_conditions(
        self,
        name_sort_by: str,
        org_sort_by: str,
        data_type_sort_by: str,
        token_count_sort_by: str,
        status_sort_by: str,
        sort_field: str,
        sort_order: int,
    ) -> Dict[str, int]:
        sort_conditions = {}

        if name_sort_by == "asc":
            sort_conditions["list_title"] = 1
        elif name_sort_by == "desc":
            sort_conditions["list_title"] = -1

        if org_sort_by == "asc":
            sort_conditions["org_nm"] = 1
        elif org_sort_by == "desc":
            sort_conditions["org_nm"] = -1

        if data_type_sort_by == "asc":
            sort_conditions["data_type"] = 1
        elif data_type_sort_by == "desc":
            sort_conditions["data_type"] = -1

        if token_count_sort_by == "asc":
            sort_conditions["token_count"] = 1
        elif token_count_sort_by == "desc":
            sort_conditions["token_count"] = -1

        if status_sort_by == "asc":
            sort_conditions["has_generated_doc"] = 1
        elif status_sort_by == "desc":
            sort_conditions["has_generated_doc"] = -1

        sort_conditions[sort_field] = sort_order
        return sort_conditions

    def _build_api_pipeline(
        self, sort_conditions: Dict[str, int]
    ) -> List[Dict]:
        """API 데이터용 MongoDB 파이프라인을 구성"""
        return [
            {
                "$lookup": {
                    "from": "generated_api_docs",
                    "localField": "list_id",
                    "foreignField": "list_id",
                    "as": "generated_docs",
                }
            },
            {
                "$project": {
                    "list_id": 1,
                    "list_title": 1,
                    "org_nm": 1,
                    "request_cnt": {"$toInt": "$request_cnt"},
                    "updated_at": 1,
                    "token_count": {
                        "$cond": [
                            {"$gt": [{"$size": "$generated_docs"}, 0]},
                            {
                                "$arrayElemAt": [
                                    "$generated_docs.token_count",
                                    0,
                                ]
                            },
                            0,
                        ]
                    },
                    "has_generated_doc": {
                        "$cond": [
                            {"$gt": [{"$size": "$generated_docs"}, 0]},
                            True,
                            False,
                        ]
                    },
                    "data_type": {"$literal": "API"},
                }
            },
            {"$sort": sort_conditions},
        ]

    def _build_file_pipeline(
        self, sort_conditions: Dict[str, int], sort_by: str
    ) -> List[Dict]:
        """파일 데이터용 MongoDB 파이프라인을 구성"""
        file_sort_conditions = sort_conditions.copy()

        if sort_by == "popular":
            file_sort_conditions["download_cnt"] = -1
        else:
            file_sort_conditions["updated_at"] = -1

        return [
            {
                "$lookup": {
                    "from": "generated_file_docs",
                    "localField": "list_id",
                    "foreignField": "list_id",
                    "as": "generated_docs",
                }
            },
            {
                "$project": {
                    "list_id": 1,
                    "list_title": {"$ifNull": ["$list_title", "$title"]},
                    "org_nm": {"$ifNull": ["$org_nm", "$dept_nm"]},
                    "download_cnt": {"$toInt": "$download_cnt"},
                    "updated_at": 1,
                    "token_count": {
                        "$cond": [
                            {"$gt": [{"$size": "$generated_docs"}, 0]},
                            {
                                "$arrayElemAt": [
                                    "$generated_docs.token_count",
                                    0,
                                ]
                            },
                            0,
                        ]
                    },
                    "has_generated_doc": {
                        "$cond": [
                            {"$gt": [{"$size": "$generated_docs"}, 0]},
                            True,
                            False,
                        ]
                    },
                    "data_type": {"$literal": "FILE"},
                }
            },
            {"$sort": file_sort_conditions},
        ]

    def _log_data_samples(self, api_data: List, file_data: List) -> None:
        """데이터 샘플을 로깅"""
        if api_data:
            self.logger.info(
                f"[CrossCollectionService] API 데이터 샘플: {api_data[0]}"
            )
        if file_data:
            self.logger.info(
                f"[CrossCollectionService] File 데이터 샘플: {file_data[0]}"
            )

    def _normalize_request_counts(
        self, api_data: List, file_data: List
    ) -> None:
        """요청 카운트를 정규화"""
        for item in api_data:
            item["request_cnt"] = item.get("request_cnt", 0)

        for item in file_data:
            item["request_cnt"] = item.get("download_cnt", 0)

    def _merge_and_deduplicate_data(
        self, api_data: List, file_data: List
    ) -> List:
        """API와 파일 데이터를 합치고 중복을 제거"""
        all_data = api_data + file_data

        seen_ids = set()
        unique_data = []
        for item in all_data:
            list_id = item.get("list_id")
            if list_id not in seen_ids:
                seen_ids.add(list_id)
                unique_data.append(item)

        return unique_data

    def _get_markdown_preview(self, markdown: str) -> str:
        """마크다운 미리보기를 생성"""
        if not markdown:
            return ""

        preview = markdown[:200]
        if len(markdown) > 200:
            preview += "..."

        return preview

    async def get_cross_collection_stats(self) -> Dict[str, Any]:
        """크로스 컬렉션 통계를 조회"""
        try:
            total_api_data = await OpenAPIInfo.count()
            total_api_docs = await GeneratedAPIDocs.count()

            total_file_data = await OpenFileInfo.count()
            total_file_docs = await GeneratedFileDocs.count()

            total_open_data = total_api_data + total_file_data
            total_generated_docs = total_api_docs + total_file_docs

            return {
                "total_open_data": total_open_data,
                "total_generated_docs": total_generated_docs,
                "api_data_count": total_api_data,
                "api_docs_count": total_api_docs,
                "file_data_count": total_file_data,
                "file_docs_count": total_file_docs,
                "api_coverage": (total_api_docs / total_api_data * 100)
                if total_api_data > 0
                else 0,
                "file_coverage": (total_file_docs / total_file_data * 100)
                if total_file_data > 0
                else 0,
                "total_coverage": (total_generated_docs / total_open_data * 100)
                if total_open_data > 0
                else 0,
            }

        except Exception:
            raise
