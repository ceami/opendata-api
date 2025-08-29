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
from typing import List

from beanie.operators import In
from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.dependencies import get_search_service
from core.exceptions import create_openapi_http_exception_doc
from models import (
    GeneratedAPIDocs,
    GeneratedFileDocs,
    OpenAPIInfo,
    OpenFileInfo,
)
from schemas.response import (
    IndexStatsResponse,
    SearchWithDocsDetailItem,
    SearchWithDocsDetailResponse,
)
from service.search import SearchService

search_router = APIRouter(prefix="/search", tags=["search"])


@search_router.get(
    path="/title",
    response_model=SearchWithDocsDetailResponse,
    responses=create_openapi_http_exception_doc(
        [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ]
    ),
    description="제목으로 공공데이터 검색 (생성된 문서가 있는 API/File, 엔드포인트 설명 포함)",
)
async def search_titles(
    query: List[str] = Query(..., description="검색할 키워드"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(10, ge=1, le=100, description="페이지 크기"),
    search_service: SearchService = Depends(get_search_service),
):
    try:
        api_doc_list_ids = await GeneratedAPIDocs.find().to_list()
        file_doc_list_ids = await GeneratedFileDocs.find().to_list()
        api_list_ids = [doc.list_id for doc in api_doc_list_ids]
        file_list_ids = [doc.list_id for doc in file_doc_list_ids]
        all_generated_list_ids = api_list_ids + file_list_ids
        search_size = max(page_size * 3, 10)
        from_ = 0

        hits = search_service.search_titles_with_weights(
            queries=query, size=search_size, from_=from_
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

        list_ids = []
        for hit in paginated_hits:
            list_id = hit["_source"].get("list_id")
            list_id_int = int(list_id) if list_id is not None else None
            if list_id_int is not None:
                list_ids.append(list_id_int)

        api_docs = {}
        if list_ids:
            api_docs_data = await GeneratedAPIDocs.find(
                In(GeneratedAPIDocs.list_id, list_ids)
            ).to_list()

            for doc in api_docs_data:
                api_docs[doc.list_id] = {
                    "data_type": "API",
                    "detail": doc.detail if hasattr(doc, "detail") else None,
                }

        file_docs = {}
        if list_ids:
            file_docs_data = await GeneratedFileDocs.find(
                In(GeneratedFileDocs.list_id, list_ids)
            ).to_list()

            for doc in file_docs_data:
                file_docs[doc.list_id] = {
                    "data_type": "FILE",
                    "detail": doc.detail if hasattr(doc, "detail") else None,
                }

        open_api_info = {}
        if list_ids:
            open_api_docs = await OpenAPIInfo.find(
                In(OpenAPIInfo.list_id, list_ids)
            ).to_list()

            for doc in open_api_docs:
                open_api_info[doc.list_id] = {
                    "org_nm": doc.org_nm,
                    "list_title": doc.list_title,
                    "title": doc.title,
                }

        open_file_info = {}
        if list_ids:
            open_file_docs = await OpenFileInfo.find(
                In(OpenFileInfo.list_id, list_ids)
            ).to_list()

            for doc in open_file_docs:
                open_file_info[doc.list_id] = {
                    "org_nm": doc.org_nm,
                    "list_title": doc.list_title or doc.title,
                    "title": doc.title,
                }

        results = []
        for hit in paginated_hits:
            source = hit["_source"]
            list_id = source.get("list_id")
            data_type = source.get("data_type", "API")

            list_id_int = int(list_id) if list_id is not None else None

            if list_id_int in api_docs:
                doc_data = api_docs[list_id_int]
                data_type = doc_data["data_type"]
                detail = doc_data.get("detail")
                org_nm = open_api_info.get(list_id_int, {}).get("org_nm")
                list_title = open_api_info.get(list_id_int, {}).get(
                    "list_title"
                ) or source.get("list_title", "")
                title = open_api_info.get(list_id_int, {}).get(
                    "title"
                ) or source.get("title", "")

            elif list_id_int in file_docs:
                doc_data = file_docs[list_id_int]
                data_type = doc_data["data_type"]
                detail = doc_data.get("detail")
                org_nm = open_file_info.get(list_id_int, {}).get("org_nm")
                list_title = open_file_info.get(list_id_int, {}).get(
                    "list_title"
                ) or source.get("list_title", "")
                title = open_file_info.get(list_id_int, {}).get(
                    "title"
                ) or source.get("title", "")

            else:
                detail = None
                org_nm = open_api_info.get(list_id_int, {}).get(
                    "org_nm"
                ) or open_file_info.get(list_id_int, {}).get("org_nm")
                list_title = source.get("list_title", "")
                title = source.get("title", "")

            item = SearchWithDocsDetailItem(
                list_id=list_id,
                list_title=list_title,
                title=title,
                org_nm=org_nm,
                score=hit.get("_score"),
                data_type=data_type,
                detail=detail,
            )
            results.append(item)

        return SearchWithDocsDetailResponse(
            total=len(filtered_hits),
            page=page,
            page_size=page_size,
            results=results,
        ).model_dump(by_alias=True)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@search_router.get(
    path="/title/std-docs",
    response_model=SearchWithDocsDetailResponse,
    responses=create_openapi_http_exception_doc(
        [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ]
    ),
    description="제목으로 공공 데이터 검색 (생성된 문서가 있는 API/File 필터링, 엔드포인트 설명 포함)",
)
async def search_titles_with_docs(
    q: str = Query(..., description="검색할 키워드"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(10, ge=1, le=100, description="페이지 크기"),
    search_service: SearchService = Depends(get_search_service),
):
    try:
        api_doc_list_ids = await GeneratedAPIDocs.find().to_list()
        file_doc_list_ids = await GeneratedFileDocs.find().to_list()
        api_list_ids = [doc.list_id for doc in api_doc_list_ids]
        file_list_ids = [doc.list_id for doc in file_doc_list_ids]
        all_generated_list_ids = api_list_ids + file_list_ids
        search_size = max(page_size * 3, 10)
        from_ = 0

        hits = search_service.search_titles(
            query=q, size=search_size, from_=from_
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

        list_ids = []
        for hit in paginated_hits:
            list_id = hit["_source"].get("list_id")
            list_id_int = int(list_id) if list_id is not None else None
            if list_id_int is not None:
                list_ids.append(list_id_int)

        api_docs = {}
        if list_ids:
            api_docs_data = await GeneratedAPIDocs.find(
                In(GeneratedAPIDocs.list_id, list_ids)
            ).to_list()

            for doc in api_docs_data:
                api_docs[doc.list_id] = {
                    "data_type": "API",
                    "detail": doc.detail if hasattr(doc, "detail") else None,
                }

        file_docs = {}
        if list_ids:
            file_docs_data = await GeneratedFileDocs.find(
                In(GeneratedFileDocs.list_id, list_ids)
            ).to_list()

            for doc in file_docs_data:
                file_docs[doc.list_id] = {
                    "data_type": "FILE",
                    "detail": doc.detail if hasattr(doc, "detail") else None,
                }

        open_api_info = {}
        if list_ids:
            open_api_docs = await OpenAPIInfo.find(
                In(OpenAPIInfo.list_id, list_ids)
            ).to_list()

            for doc in open_api_docs:
                open_api_info[doc.list_id] = {
                    "org_nm": doc.org_nm,
                    "list_title": doc.list_title,
                    "title": doc.title,
                }

        open_file_info = {}
        if list_ids:
            open_file_docs = await OpenFileInfo.find(
                In(OpenFileInfo.list_id, list_ids)
            ).to_list()

            for doc in open_file_docs:
                open_file_info[doc.list_id] = {
                    "org_nm": doc.org_nm,
                    "list_title": doc.list_title or doc.title,
                    "title": doc.title,
                }

        results = []
        for hit in paginated_hits:
            source = hit["_source"]
            list_id = source.get("list_id")
            data_type = source.get("data_type", "API")

            list_id_int = int(list_id) if list_id is not None else None

            if list_id_int in api_docs:
                doc_data = api_docs[list_id_int]
                data_type = doc_data["data_type"]
                detail = doc_data.get("detail")
                org_nm = open_api_info.get(list_id_int, {}).get("org_nm")
                list_title = open_api_info.get(list_id_int, {}).get(
                    "list_title"
                ) or source.get("list_title", "")
                title = open_api_info.get(list_id_int, {}).get(
                    "title"
                ) or source.get("title", "")

            elif list_id_int in file_docs:
                doc_data = file_docs[list_id_int]
                data_type = doc_data["data_type"]
                detail = doc_data.get("detail")
                org_nm = open_file_info.get(list_id_int, {}).get("org_nm")
                list_title = open_file_info.get(list_id_int, {}).get(
                    "list_title"
                ) or source.get("list_title", "")
                title = open_file_info.get(list_id_int, {}).get(
                    "title"
                ) or source.get("title", "")

            else:
                detail = None
                org_nm = open_api_info.get(list_id_int, {}).get(
                    "org_nm"
                ) or open_file_info.get(list_id_int, {}).get("org_nm")
                list_title = source.get("list_title", "")
                title = source.get("title", "")

            item = SearchWithDocsDetailItem(
                list_id=list_id,
                list_title=list_title,
                org_nm=org_nm,
                title=title,
                score=hit.get("_score"),
                data_type=data_type,
                detail=detail,
            )
            results.append(item)

        return SearchWithDocsDetailResponse(
            total=len(filtered_hits),
            page=page,
            page_size=page_size,
            results=results,
        ).model_dump(by_alias=True)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@search_router.get(
    path="/stats",
    response_model=IndexStatsResponse,
    responses=create_openapi_http_exception_doc(
        [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ]
    ),
    description="인덱스 통계 정보 조회",
)
async def get_index_stats(
    search_service: SearchService = Depends(get_search_service),
):
    try:
        stats = search_service.get_index_stats()

        response_data = {
            "index_name": "open_data_titles",
            "total_docs": stats["total"]["docs"]["count"],
            "total_size": stats["total"]["store"]["size_in_bytes"],
            "indexing_stats": stats["total"]["indexing"],
            "search_stats": stats["total"]["search"],
        }

        return IndexStatsResponse(**response_data).model_dump(by_alias=True)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
