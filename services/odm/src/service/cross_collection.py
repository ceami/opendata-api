from typing import Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from models import OpenDataInfo, APIStdDocument


class CrossCollectionService:
    def __init__(self, mongo_client: AsyncIOMotorClient):
        self.mongo_client = mongo_client
        self.open_data_db = self.mongo_client.open_data
        self.odm_db = self.mongo_client.odm

    async def get_cross_collection_data_paginated(
        self,
        page: int = 1,
        size: int = 50,
        sort_by: str = "popular"
    ) -> Dict[str, Any]:
        try:
            from schemas.response import validate_pagination_params, calculate_offset

            page, size = validate_pagination_params(page, size)
            offset = calculate_offset(page, size)

            sort_field = "request_cnt" if sort_by == "popular" else "updated_at"
            sort_order = -1

            pipeline = [
                {
                    "$lookup": {
                        "from": "generated_std_docs",
                        "localField": "list_id",
                        "foreignField": "list_id",
                        "as": "matched_docs"
                    }
                },
                {
                    "$project": {
                        "list_id": 1,
                        "list_title": 1,
                        "org_nm": 1,
                        "request_cnt": 1,
                        "updated_at": 1,
                        "token_count": {
                            "$cond": [
                                {"$gt": [{"$size": "$matched_docs"}, 0]},
                                {"$arrayElemAt": ["$matched_docs.token_count", 0]},
                                0
                            ]
                        },
                        "has_generated_doc": {
                            "$cond": [
                                {"$gt": [{"$size": "$matched_docs"}, 0]},
                                True,
                                False
                            ]
                        }
                    }
                },
                {
                    "$sort": {sort_field: sort_order}
                },
                {
                    "$facet": {
                        "data": [
                            {"$skip": offset},
                            {"$limit": size}
                        ],
                        "total": [
                            {"$count": "count"}
                        ]
                    }
                }
            ]

            result = await self.open_data_db.open_data_info.aggregate(pipeline).to_list(1)

            if not result or not result[0]:
                return {
                    "data": [],
                    "total": 0,
                    "page": page,
                    "size": size
                }

            data = result[0].get("data", [])
            total = result[0].get("total", [{}])[0].get("count", 0) if result[0].get("total") else 0

            from schemas.response import CrossCollectionItem

            formatted_data = []
            for doc in data:
                updated_at = doc.get("updated_at")
                updated_at_str = updated_at.isoformat() if updated_at else None

                item = CrossCollectionItem(
                    list_id=doc["list_id"],
                    list_title=doc.get("list_title", ""),
                    org_nm=doc.get("org_nm", ""),
                    token_count=doc.get("token_count", 0),
                    has_generated_doc=doc.get("has_generated_doc", False),
                    updated_at=updated_at_str,
                    data_type=doc.get("data_type", "API"),
                )
                formatted_data.append(item.model_dump(by_alias=True))

            return {
                "data": formatted_data,
                "total": total,
                "page": page,
                "size": size
            }

        except Exception:
            raise

    def _get_markdown_preview(self, markdown: str) -> str:
        if not markdown:
            return ""

        preview = markdown[:200]
        if len(markdown) > 200:
            preview += "..."

        return preview

    async def get_cross_collection_stats(self) -> Dict[str, Any]:
        try:
            pipeline = [
                {
                    "$lookup": {
                        "from": "generated_std_docs",
                        "localField": "list_id",
                        "foreignField": "list_id",
                        "as": "matched_docs"
                    }
                },
                {
                    "$match": {
                        "matched_docs": {"$ne": []}
                    }
                },
                {
                    "$count": "cross_collection_count"
                }
            ]

            cross_result = await self.open_data_db.open_data_info.aggregate(pipeline).to_list(1)
            cross_collection_count = cross_result[0]["cross_collection_count"] if cross_result else 0

            total_open_data = await OpenDataInfo.count()
            total_std_docs = await APIStdDocument.count()

            return {
                "total_open_data": total_open_data,
                "total_std_docs": total_std_docs,
                "cross_collection_count": cross_collection_count,
                "open_data_coverage": (cross_collection_count / total_open_data * 100) if total_open_data > 0 else 0,
                "std_docs_coverage": (cross_collection_count / total_std_docs * 100) if total_std_docs > 0 else 0
            }

        except Exception:
            raise
