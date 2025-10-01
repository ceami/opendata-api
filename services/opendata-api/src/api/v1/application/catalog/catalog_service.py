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
import math
from datetime import datetime, timezone
from typing import Any, Literal

from motor.motor_asyncio import AsyncIOMotorClient

from models import (
    GeneratedAPIDocs,
    GeneratedFileDocs,
    OpenAPIInfo,
    OpenFileInfo,
    RankLatest,
    RankPopular,
    RankTrending,
    RankMetadata,
)
from api.v1.domain.open_data.entities import UnifiedDataItem
from api.v1.application.utils.pagination import (
    calculate_offset,
    validate_pagination_params,
)


class CatalogService:
    def __init__(
        self, mongo_client: AsyncIOMotorClient, logger: logging.Logger | None = None
    ):
        self.mongo_client = mongo_client
        self.open_data_db = self.mongo_client.open_data
        self.odm_db = self.mongo_client.odm
        self.logger = logger or logging.getLogger(__name__)

    async def get_unified_search_data(
        self, query: str, page: int = 1, size: int = 20, search_service=None
    ) -> dict[str, Any]:
        page, size = validate_pagination_params(page, size)
        offset = calculate_offset(page, size)

        list_ids = await self._get_search_list_ids(query, size, search_service)
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

    async def _get_search_list_ids(self, query: str, size: int, search_service) -> list[str]:
        if not search_service:
            return []
        search_size = max(size * 3, 10)
        hits = search_service.search_titles(query=query, size=search_size, from_=0)
        return [hit["_source"].get("list_id") for hit in hits["hits"]]

    async def _get_api_data(self, list_ids: list[str]) -> list[UnifiedDataItem]:
        if not list_ids:
            return []
        api_list_ids = self._convert_to_int_list_ids(list_ids)
        if not api_list_ids:
            return []
        api_docs = await OpenAPIInfo.find({"list_id": {"$in": api_list_ids}}).to_list()

        api_data: list[UnifiedDataItem] = []
        for doc in api_docs:
            generated_doc = await GeneratedAPIDocs.find_one({"list_id": doc.list_id})
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

    async def _get_file_data(self, list_ids: list[str]) -> list[UnifiedDataItem]:
        if not list_ids:
            return []
        file_docs = await OpenFileInfo.find({"list_id": {"$in": list_ids}}).to_list()

        file_data: list[UnifiedDataItem] = []
        for doc in file_docs:
            generated_doc = await GeneratedFileDocs.find_one({"list_id": doc.list_id})
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

    def _convert_to_int_list_ids(self, list_ids: list[str]) -> list[int]:
        api_list_ids: list[int] = []
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
    ) -> dict[str, Any]:
        self.logger.info(
            f"[CatalogService] 데이터 조회 시작: page={page}, size={size}"
        )
        page, size = validate_pagination_params(page, size)
        offset = calculate_offset(page, size)

        api_pipeline = self._build_api_pipeline({})
        file_pipeline = self._build_file_pipeline({}, sort_by)

        self.logger.info("[CatalogService] MongoDB Aggregation 실행 시작")

        api_result, file_result = await asyncio.gather(
            self.open_data_db.open_data_info.aggregate(api_pipeline).to_list(),
            self.open_data_db.open_file_info.aggregate(file_pipeline).to_list(),
        )

        api_data = api_result if api_result else []
        file_data = file_result if file_result else []

        for item in api_data:
            item["request_cnt"] = item.get("request_cnt", 0)
        for item in file_data:
            item["request_cnt"] = item.get("download_cnt", 0)

        unique_data = self._merge_and_deduplicate_data(api_data, file_data)

        if sort_by == "popular":
            unique_data.sort(key=lambda x: x.get("request_cnt", 0), reverse=True)
        else:
            unique_data.sort(
                key=lambda x: x.get("updated_at") or datetime.min, reverse=True
            )

        start_idx = offset
        end_idx = start_idx + size
        paginated_data = unique_data[start_idx:end_idx]

        total_count = len(unique_data)

        self.logger.info(
            f"[CatalogService] 조회 완료: API={len(api_data)}개, File={len(file_data)}개, 총 {len(paginated_data)}개 반환"
        )

        return {"data": paginated_data, "total": total_count, "page": page, "size": size}

    async def rebuild_rank_snapshots(self) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        api_docs = await OpenAPIInfo.find({}, projection_model=None).to_list()
        file_docs = await OpenFileInfo.find({}, projection_model=None).to_list()

        rows: list[dict[str, Any]] = []

        api_generated_map: dict[int, GeneratedAPIDocs] = {}
        api_generated_list = await GeneratedAPIDocs.find({}).to_list()
        for g in api_generated_list:
            api_generated_map[g.list_id] = g

        for doc in api_docs:
            gen = api_generated_map.get(doc.list_id)
            rows.append(
                {
                    "list_id": doc.list_id,
                    "data_type": "API",
                    "list_title": doc.list_title,
                    "org_nm": doc.org_nm,
                    "token_count": gen.token_count if gen else 0,
                    "has_generated_doc": gen is not None,
                    "updated_at": doc.updated_at,
                    "generated_at": getattr(gen, "generated_at", None),
                    "popularity_score": int(doc.request_cnt or 0),
                }
            )

        file_generated_map: dict[int, GeneratedFileDocs] = {}
        file_generated_list = await GeneratedFileDocs.find({}).to_list()
        for g in file_generated_list:
            file_generated_map[g.list_id] = g

        for doc in file_docs:
            gen = file_generated_map.get(doc.list_id)
            rows.append(
                {
                    "list_id": int(doc.list_id) if doc.list_id else 0,
                    "data_type": "FILE",
                    "list_title": getattr(doc, "list_title", None) or getattr(doc, "title", None),
                    "org_nm": getattr(doc, "org_nm", None) or getattr(doc, "dept_nm", None),
                    "token_count": gen.token_count if gen else 0,
                    "has_generated_doc": gen is not None,
                    "updated_at": doc.updated_at,
                    "generated_at": getattr(gen, "generated_at", None),
                    "popularity_score": int(getattr(doc, "download_cnt", 0) or 0),
                }
            )

        latest_sorted = sorted(
            rows,
            key=lambda r: (r.get("generated_at") or r.get("updated_at") or now),
            reverse=True,
        )
        await self._bulk_upsert_rank(RankLatest, latest_sorted[:1000], score_field=None)

        popular_sorted = sorted(rows, key=lambda r: r.get("popularity_score", 0), reverse=True)
        await self._bulk_upsert_rank(RankPopular, popular_sorted[:1000], score_field=None)

        trending_rows: list[dict[str, Any]] = []
        for r in rows:
            updated_at = r.get("updated_at") or now
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=now.tzinfo)
            hours = max(1.0, (now - updated_at).total_seconds() / 3600.0)
            base = max(0.0, float(r.get("popularity_score", 0)))
            trending_score = math.log1p(base) / (hours ** 1.5)
            r2 = dict(r)
            r2["trending_score"] = trending_score
            trending_rows.append(r2)

        trending_sorted = sorted(trending_rows, key=lambda r: r.get("trending_score", 0.0), reverse=True)
        await self._bulk_upsert_rank(RankTrending, trending_sorted[:1000], score_field="trending_score")

        seen_list_ids = set()
        unique_rows = []
        for row in rows:
            list_id = row.get("list_id")
            if list_id and list_id not in seen_list_ids:
                seen_list_ids.add(list_id)
                unique_rows.append(row)
        total_count = len(unique_rows)
        now_utc = datetime.now(datetime.now().astimezone().tzinfo)
        
        for sort_type in ["latest", "popular", "trending"]:
            await RankMetadata.find_one(RankMetadata.sort_type == sort_type).delete()
            metadata = RankMetadata(
                sort_type=sort_type,
                total_count=total_count,
                last_updated=now_utc,
            )
            await metadata.insert()

        return {"latest": len(latest_sorted), "popular": len(popular_sorted), "trending": len(trending_sorted)}

    async def _bulk_upsert_rank(
        self,
        model: type[RankLatest] | type[RankPopular] | type[RankTrending],
        sorted_rows: list[dict[str, Any]],
        score_field: str | None,
    ) -> None:
        bulk: list[model] = []
        for idx, r in enumerate(sorted_rows, start=1):
            doc = model(
                list_id=r["list_id"],
                data_type=r.get("data_type"),
                list_title=r.get("list_title"),
                org_nm=r.get("org_nm"),
                token_count=r.get("token_count"),
                has_generated_doc=r.get("has_generated_doc"),
                updated_at=r.get("updated_at"),
                generated_at=r.get("generated_at"),
                popularity_score=r.get("popularity_score"),
                trending_score=r.get("trending_score"),
                rank=idx,
            )
            bulk.append(doc)

        if not bulk:
            return

        await model.find_all().delete()
        await model.insert_many(bulk)

    async def get_ranked_snapshots(
        self, sort_by: Literal["latest", "popular", "trending"], page: int, size: int
    ) -> dict[str, Any]:
        page, size = validate_pagination_params(page, size)
        skip = calculate_offset(page, size)

        model_map = {"latest": RankLatest, "popular": RankPopular, "trending": RankTrending}
        model = model_map[sort_by]

        max_page_in_snapshot = 1000 // size

        metadata = await RankMetadata.find_one(RankMetadata.sort_type == sort_by)
        total = metadata.total_count if metadata else 0

        if page > max_page_in_snapshot:
            return {"redirect_to_original": True, "reason": "page_exceeds_snapshot_limit", "total": total}

        docs = await model.find().sort("rank").skip(skip).limit(size).to_list()

        items = [
            {
                "list_id": d.list_id,
                "list_title": d.list_title,
                "org_nm": d.org_nm,
                "token_count": d.token_count or 0,
                "has_generated_doc": bool(d.has_generated_doc),
                "data_type": d.data_type,
            }
            for d in docs
        ]

        return {"data": items, "total": total, "page": page, "size": size}

    def _build_sort_conditions(
        self,
        name_sort_by: str,
        org_sort_by: str,
        data_type_sort_by: str,
        token_count_sort_by: str,
        status_sort_by: str,
        sort_field: str,
        sort_order: int,
    ) -> dict[str, int]:
        sort_conditions: dict[str, int] = {}
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

    def _build_api_pipeline(self, sort_conditions: dict[str, int]) -> list[dict]:
        pipeline = [
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
                            {"$arrayElemAt": ["$generated_docs.token_count", 0]},
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
        ]
        if sort_conditions:
            pipeline.append({"$sort": sort_conditions})
        return pipeline

    def _build_file_pipeline(self, sort_conditions: dict[str, int], sort_by: str) -> list[dict]:
        pipeline = [
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
                            {"$arrayElemAt": ["$generated_docs.token_count", 0]},
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
        ]
        if sort_conditions:
            file_sort_conditions = sort_conditions.copy()
            if sort_by == "popular":
                file_sort_conditions["download_cnt"] = -1
            else:
                file_sort_conditions["updated_at"] = -1
            pipeline.append({"$sort": file_sort_conditions})
        return pipeline

    def _merge_and_deduplicate_data(self, api_data: list, file_data: list) -> list:
        all_data = api_data + file_data
        seen_ids = set()
        unique_data = []
        for item in all_data:
            list_id = item.get("list_id")
            if list_id not in seen_ids:
                seen_ids.add(list_id)
                unique_data.append(item)
        return unique_data

    async def get_cross_collection_stats(self) -> dict[str, Any]:
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
            "api_coverage": (total_api_docs / total_api_data * 100) if total_api_data > 0 else 0,
            "file_coverage": (total_file_docs / total_file_data * 100) if total_file_data > 0 else 0,
            "total_coverage": (total_generated_docs / total_open_data * 100) if total_open_data > 0 else 0,
        }
