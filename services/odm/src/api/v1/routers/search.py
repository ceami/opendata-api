from beanie.operators import In
from fastapi import APIRouter, Query, status, HTTPException, Depends
from typing import List

from core.exceptions import create_openapi_http_exception_doc
from core.dependencies import get_search_service
from service.search import SearchService
from models import APIStdDocument
from models import OpenDataInfo
from schemas.response import SearchResponse, IndexStatsResponse, SearchWithDocsItem

search_router = APIRouter(prefix="/search", tags=["search"])


@search_router.get(
    path="/title",
    response_model=SearchResponse,
    responses=create_openapi_http_exception_doc([
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ]),
    description="제목으로 공공 데이터 검색 (표준 문서가 있는 API만)",
)
async def search_titles(
    query: List[str] = Query(..., description="검색할 키워드"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(10, ge=1, le=100, description="페이지 크기"),
    search_service: SearchService = Depends(get_search_service),
):

    try:
        std_doc_list_ids = await APIStdDocument.find().to_list()
        std_doc_list_ids = [doc.list_id for doc in std_doc_list_ids]

        if not std_doc_list_ids:
            return {
                "total": 0,
                "page": page,
                "page_size": page_size,
                "results": []
            }

        search_size = page_size * 3
        from_ = 0

        hits = search_service.search_titles_with_weights(
            queries=query,
            size=search_size,
            from_=from_
        )

        filtered_hits = []
        for hit in hits["hits"]:
            list_id = hit["_source"].get("list_id")
            if list_id in std_doc_list_ids:
                filtered_hits.append(hit)
                if len(filtered_hits) >= page_size * 2:
                    break

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_hits = filtered_hits[start_idx:end_idx]

        list_ids = [hit["_source"].get("list_id") for hit in paginated_hits]
        std_docs = {}

        if list_ids:
            docs = await APIStdDocument.find(
                In(APIStdDocument.list_id, list_ids)
            ).to_list()

            for doc in docs:
                std_docs[doc.list_id] = {
                    "token_count": doc.token_count or 0,
                    "has_generated_doc": True
                }

        open_data_info = {}
        if list_ids:
            open_data_docs = await OpenDataInfo.find(
                In(OpenDataInfo.list_id, list_ids)
            ).to_list()

            for doc in open_data_docs:
                open_data_info[doc.list_id] = {
                    "org_nm": doc.org_nm
                }

        results = []
        for hit in paginated_hits:
            source = hit["_source"]
            list_id = source.get("list_id")

            if list_id in std_docs:
                std_doc_data = std_docs[list_id]
                token_count = std_doc_data["token_count"]
                has_generated_doc = std_doc_data["has_generated_doc"]
            else:
                token_count = 0
                has_generated_doc = False

            org_nm = open_data_info.get(list_id, {}).get("org_nm") if list_id in open_data_info else None

            item = SearchWithDocsItem(
                list_id=list_id,
                list_title=source.get("list_title", ""),
                org_nm=org_nm,
                score=hit.get("_score"),
                token_count=token_count,
                has_generated_doc=has_generated_doc,
                data_type="API"
            )
            results.append(item.model_dump(by_alias=True))

        return SearchResponse(
            total=len(filtered_hits),
            page=page,
            page_size=page_size,
            results=results
        ).model_dump(by_alias=True)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@search_router.get(
    path="/title/std-docs",
    response_model=SearchResponse,
    responses=create_openapi_http_exception_doc([
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ]),
    description="제목으로 공공 데이터 검색 (표준 문서가 있는 API만 필터링)",
)
async def search_titles_with_docs(
    q: str = Query(..., description="검색할 키워드"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(10, ge=1, le=100, description="페이지 크기"),
    search_service: SearchService = Depends(get_search_service),
):
    try:
        std_doc_list_ids = await APIStdDocument.find().to_list()
        std_doc_list_ids = [doc.list_id for doc in std_doc_list_ids]

        if not std_doc_list_ids:
            return SearchResponse(
                total=0,
                page=page,
                page_size=page_size,
                results=[]
            ).model_dump(by_alias=True)

        search_size = page_size * 3
        from_ = 0

        hits = search_service.search_titles(
            query=q,
            size=search_size,
            from_=from_
        )

        filtered_hits = []
        for hit in hits["hits"]:
            list_id = hit["_source"].get("list_id")
            if list_id in std_doc_list_ids:
                filtered_hits.append(hit)
                if len(filtered_hits) >= page_size * 2:
                    break

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_hits = filtered_hits[start_idx:end_idx]

        list_ids = [hit["_source"].get("list_id") for hit in paginated_hits]
        std_docs = {}

        if list_ids:
            docs = await APIStdDocument.find(
                In(APIStdDocument.list_id, list_ids)
            ).to_list()

            for doc in docs:
                std_docs[doc.list_id] = {
                    "token_count": doc.token_count or 0,
                    "has_generated_doc": True
                }

        open_data_info = {}
        if list_ids:
            open_data_docs = await OpenDataInfo.find(
                In(OpenDataInfo.list_id, list_ids)
            ).to_list()

            for doc in open_data_docs:
                open_data_info[doc.list_id] = {
                    "org_nm": doc.org_nm
                }

        results = []
        for hit in paginated_hits:
            try:
                source = hit["_source"]
                list_id = source.get("list_id")

                if list_id in std_docs:
                    std_doc_data = std_docs[list_id]
                    token_count = std_doc_data["token_count"]
                    has_generated_doc = std_doc_data["has_generated_doc"]
                else:
                    token_count = 0
                    has_generated_doc = False

                org_nm = open_data_info.get(list_id, {}).get("org_nm") if list_id in open_data_info else None

                item = SearchWithDocsItem(
                    list_id=list_id,
                    list_title=source.get("list_title", ""),
                    org_nm=org_nm,
                    score=hit.get("_score"),
                    token_count=token_count,
                    has_generated_doc=has_generated_doc,
                    data_type="API"
                )
                results.append(item.model_dump(by_alias=True))
            except Exception:
                continue

        return SearchResponse(
            total=len(filtered_hits),
            page=page,
            page_size=page_size,
            results=results
        ).model_dump(by_alias=True)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@search_router.get(
    path="/stats",
    response_model=IndexStatsResponse,
    responses=create_openapi_http_exception_doc([
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ]),
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
            "search_stats": stats["total"]["search"]
        }

        return IndexStatsResponse(**response_data).model_dump(by_alias=True)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
