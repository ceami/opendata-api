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
from typing import Any

from models import GeneratedAPIDocs, GeneratedFileDocs, OpenAPIInfo, OpenFileInfo
from beanie.operators import In
from utils.datetime_util import format_datetime


class SearchAppService:
    async def get_frontend_data_search(
        self,
        *,
        q: str,
        page: int,
        size: int,
        exact_match: bool,
        min_score: float | None,
        use_adaptive_filtering: bool,
        search_service: Any,
    ) -> dict[str, Any]:
        from_ = (page - 1) * size

        if use_adaptive_filtering:
            hits = search_service.search_titles_with_adaptive_filtering(
                query=q.strip(), size=size, from_=from_
            )
        else:
            hits = search_service.search_titles(
                query=q.strip(),
                size=size,
                from_=from_,
                exact_match=exact_match,
                min_score=min_score,
            )

        list_ids: list[int] = []
        for hit in hits["hits"]:
            try:
                list_ids.append(int(hit["_source"].get("list_id")))
            except (ValueError, TypeError):
                continue

        api_data_info: dict[int, dict[str, Any]] = {}
        file_data_info: dict[int, dict[str, Any]] = {}

        if list_ids:
            api_docs = await OpenAPIInfo.find(In(OpenAPIInfo.list_id, list_ids)).to_list()
            for doc in api_docs:
                api_data_info[doc.list_id] = {
                    "list_title": doc.list_title,
                    "org_nm": doc.org_nm,
                    "data_type": "API",
                }

            file_docs = await OpenFileInfo.find(In(OpenFileInfo.list_id, list_ids)).to_list()
            for doc in file_docs:
                file_data_info[doc.list_id] = {
                    "list_title": getattr(doc, "list_title", None)
                    or getattr(doc, "title", None),
                    "org_nm": getattr(doc, "org_nm", None)
                    or getattr(doc, "dept_nm", None),
                    "data_type": "FILE",
                }

        api_generated_docs: dict[int, dict[str, Any]] = {}
        file_generated_docs: dict[int, dict[str, Any]] = {}

        if list_ids:
            generated_api_docs = await GeneratedAPIDocs.find(In(GeneratedAPIDocs.list_id, list_ids)).to_list()
            for doc in generated_api_docs:
                api_generated_docs[doc.list_id] = {
                    "token_count": doc.token_count,
                    "has_generated_doc": True,
                    "generated_at": getattr(doc, "generated_at", None),
                }

            generated_file_docs = await GeneratedFileDocs.find(In(GeneratedFileDocs.list_id, list_ids)).to_list()
            for doc in generated_file_docs:
                file_generated_docs[doc.list_id] = {
                    "token_count": doc.token_count,
                    "has_generated_doc": True,
                    "generated_at": getattr(doc, "generated_at", None),
                }

        items: list[dict[str, Any]] = []
        for hit in hits["hits"]:
            source = hit["_source"]
            list_id = int(source.get("list_id"))

            if list_id in api_data_info:
                api_info = api_data_info[list_id]
                gen = api_generated_docs.get(list_id)
                items.append(
                    {
                        "list_id": list_id,
                        "list_title": api_info["list_title"],
                        "org_nm": api_info["org_nm"],
                        "token_count": gen["token_count"] if gen else 0,
                        "has_generated_doc": gen["has_generated_doc"] if gen else False,
                        "updated_at": format_datetime(gen["generated_at"]) if gen else None,
                        "data_type": "API",
                        "score": hit.get("_score"),
                    }
                )
            elif list_id in file_data_info:
                file_info = file_data_info[list_id]
                gen = file_generated_docs.get(list_id)
                items.append(
                    {
                        "list_id": list_id,
                        "list_title": file_info["list_title"],
                        "org_nm": file_info["org_nm"],
                        "token_count": gen["token_count"] if gen else 0,
                        "has_generated_doc": gen["has_generated_doc"] if gen else False,
                        "updated_at": format_datetime(gen["generated_at"]) if gen else None,
                        "data_type": "FILE",
                        "score": hit.get("_score"),
                    }
                )
            elif list_id in file_generated_docs:
                gen = file_generated_docs[list_id]
                org_nm = api_data_info.get(list_id, {}).get("org_nm") or source.get("org_nm")
                items.append(
                    {
                        "list_id": list_id,
                        "list_title": source.get("list_title", ""),
                        "org_nm": org_nm,
                        "token_count": gen["token_count"],
                        "has_generated_doc": gen["has_generated_doc"],
                        "updated_at": format_datetime(gen["generated_at"]),
                        "data_type": "FILE",
                        "score": hit.get("_score"),
                    }
                )
            else:
                items.append(
                    {
                        "list_id": list_id,
                        "list_title": source.get("list_title", ""),
                        "org_nm": None,
                        "token_count": 0,
                        "has_generated_doc": False,
                        "updated_at": None,
                        "data_type": source.get("data_type", "API"),
                        "score": hit.get("_score"),
                    }
                )

        return {
            "items": items,
            "total": hits["total"]["value"],
            "page": page,
            "size": size,
        }

    async def search_titles_with_docs_multi(
        self,
        *,
        queries: list[str],
        page: int,
        page_size: int,
        search_service: Any,
    ) -> dict[str, Any]:
        api_doc_list_ids = await GeneratedAPIDocs.find().to_list()
        file_doc_list_ids = await GeneratedFileDocs.find().to_list()
        api_list_ids = [doc.list_id for doc in api_doc_list_ids]
        file_list_ids = [doc.list_id for doc in file_doc_list_ids]
        all_generated_list_ids = set(api_list_ids + file_list_ids)

        search_size = max(page_size * 3, 10)
        hits = search_service.search_titles_with_weights(
            queries=queries, size=search_size, from_=0
        )

        filtered_hits = []
        for hit in hits["hits"]:
            list_id = hit["_source"].get("list_id")
            list_id_int = int(list_id) if list_id is not None else None
            if list_id_int in all_generated_list_ids:
                filtered_hits.append(hit)
                if len(filtered_hits) >= page_size * 2:
                    break

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_hits = filtered_hits[start_idx:end_idx]

        list_ids: list[int] = []
        for hit in paginated_hits:
            list_id = hit["_source"].get("list_id")
            list_id_int = int(list_id) if list_id is not None else None
            if list_id_int is not None:
                list_ids.append(list_id_int)

        api_docs: dict[int, dict[str, Any]] = {}
        if list_ids:
            api_docs_data = await GeneratedAPIDocs.find(In(GeneratedAPIDocs.list_id, list_ids)).to_list()
            for doc in api_docs_data:
                api_docs[doc.list_id] = {
                    "data_type": "API",
                    "detail": getattr(doc, "detail", None),
                }

        file_docs: dict[int, dict[str, Any]] = {}
        if list_ids:
            file_docs_data = await GeneratedFileDocs.find(In(GeneratedFileDocs.list_id, list_ids)).to_list()
            for doc in file_docs_data:
                file_docs[doc.list_id] = {
                    "data_type": "FILE",
                    "detail": getattr(doc, "detail", None),
                }

        open_api_info: dict[int, dict[str, Any]] = {}
        if list_ids:
            open_api_rows = await OpenAPIInfo.find(In(OpenAPIInfo.list_id, list_ids)).to_list()
            for doc in open_api_rows:
                open_api_info[doc.list_id] = {
                    "org_nm": doc.org_nm,
                    "list_title": doc.list_title,
                    "title": doc.title,
                }

        open_file_info: dict[int, dict[str, Any]] = {}
        if list_ids:
            open_file_rows = await OpenFileInfo.find(In(OpenFileInfo.list_id, list_ids)).to_list()
            for doc in open_file_rows:
                open_file_info[doc.list_id] = {
                    "org_nm": doc.org_nm,
                    "list_title": doc.list_title or doc.title,
                    "title": doc.title,
                }

        results: list[dict[str, Any]] = []
        for hit in paginated_hits:
            source = hit["_source"]
            list_id = source.get("list_id")
            list_id_int = int(list_id) if list_id is not None else None

            if list_id_int in api_docs:
                doc_data = api_docs[list_id_int]
                data_type = doc_data["data_type"]
                detail = doc_data.get("detail")
                org_nm = open_api_info.get(list_id_int, {}).get("org_nm")
                list_title = open_api_info.get(list_id_int, {}).get("list_title") or source.get("list_title", "")
                title = open_api_info.get(list_id_int, {}).get("title") or source.get("title", "")
            elif list_id_int in file_docs:
                doc_data = file_docs[list_id_int]
                data_type = doc_data["data_type"]
                detail = doc_data.get("detail")
                org_nm = open_file_info.get(list_id_int, {}).get("org_nm")
                list_title = open_file_info.get(list_id_int, {}).get("list_title") or source.get("list_title", "")
                title = open_file_info.get(list_id_int, {}).get("title") or source.get("title", "")
            else:
                data_type = source.get("data_type", "API")
                detail = None
                org_nm = open_api_info.get(list_id_int, {}).get("org_nm") or open_file_info.get(list_id_int, {}).get("org_nm")
                list_title = source.get("list_title", "")
                title = source.get("title", "")

            results.append(
                {
                    "list_id": list_id,
                    "list_title": list_title,
                    "org_nm": org_nm,
                    "title": title,
                    "score": hit.get("_score"),
                    "data_type": data_type,
                    "detail": detail,
                }
            )

        return {
            "total": len(filtered_hits),
            "page": page,
            "page_size": page_size,
            "results": results,
        }

    def get_index_stats(self, *, search_service: Any) -> dict[str, Any]:
        stats = search_service.get_index_stats()
        return {
            "index_name": "open_data_titles",
            "total_docs": stats["total"]["docs"]["count"],
            "total_size": stats["total"]["store"]["size_in_bytes"],
            "indexing_stats": stats["total"]["indexing"],
            "search_stats": stats["total"]["search"],
        }
