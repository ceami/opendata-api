from beanie.operators import Eq, In
from fastapi import APIRouter, Query, Path, status, HTTPException, Depends
from typing import Dict, Any

from models import OpenDataInfo, APIStdDocument
from core.exceptions import create_openapi_http_exception_doc
from core.dependencies import get_cross_collection_service, get_search_service
from service.cross_collection import CrossCollectionService
from service.search import SearchService
from schemas.response import create_paginated_response, PaginatedResponse, SearchWithDocsItem, DocumentWithParsedInfo

document_router = APIRouter(prefix="/document", tags=["document"])


@document_router.get(
    path="",
    response_model=PaginatedResponse[Dict[str, Any]],
    responses=create_openapi_http_exception_doc([
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ]),
    description="Frontend용 통합 API - 검색 / 데이터 제공",
)
async def get_frontend_data(
    q: str = Query(None, description="검색 키워드"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    size: int = Query(20, ge=1, le=100, description="페이지 크기"),
    sort_by: str = Query("popular", description="정렬 기준 (popular: request_cnt 순, trending: updated_at 순)"),
    search_service: SearchService = Depends(get_search_service),
    cross_collection_service: CrossCollectionService = Depends(get_cross_collection_service),
):
    try:
        if q and q.strip():
            from_ = (page - 1) * size

            hits = search_service.search_titles(
                query=q.strip(),
                size=size,
                from_=from_
            )

            list_ids = [hit["_source"].get("list_id") for hit in hits["hits"]]

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

            results = []
            for hit in hits["hits"]:
                source = hit["_source"]
                list_id = source.get("list_id")

                if list_id in std_docs:
                    std_doc_data = std_docs[list_id]
                    token_count = std_doc_data["token_count"]
                    has_generated_doc = std_doc_data["has_generated_doc"]
                else:
                    token_count = 0
                    has_generated_doc = False

                item = SearchWithDocsItem(
                    list_id=list_id,
                    list_title=source.get("list_title", ""),
                    title=source.get("title", ""),
                    score=hit.get("_score"),
                    token_count=token_count,
                    has_generated_doc=has_generated_doc
                )
                results.append(item.model_dump())

            return create_paginated_response(
                items=results,
                total=hits["total"]["value"],
                page=page,
                size=size
            )

        else:
            if sort_by not in ["popular", "trending"]:
                raise HTTPException(status_code=400, detail="sort_by는 'popular' 또는 'trending'이어야 합니다")

            result = await cross_collection_service.get_cross_collection_data_paginated(
                page=page,
                size=size,
                sort_by=sort_by
            )

            return create_paginated_response(
                items=result["data"],
                total=result["total"],
                page=result["page"],
                size=result["size"]
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@document_router.get(
    path="/std-docs",
    response_model=list[APIStdDocument],
    responses=create_openapi_http_exception_doc([
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ]),
    description="API 표준 문서 목록 조회",
)
async def get_api_std_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    try:
        documents = (
            await APIStdDocument.find()
            .skip((page - 1) * page_size)
            .limit(page_size)
            .to_list()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return documents


@document_router.get(
    path="/success-rate",
    response_model=dict,
    responses=create_openapi_http_exception_doc([
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ]),
    description="성공률 조회",
)
async def get_success_rate():
    try:
        total_open_data = await OpenDataInfo.count()
        total_std_docs = await APIStdDocument.count()

        success_rate = (total_std_docs / total_open_data * 100) if total_open_data > 0 else 0

        return {
            "total_open_data": total_open_data,
            "total_std_docs": total_std_docs,
            "success_rate": round(success_rate, 2)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@document_router.get(
    path="/std-docs/{list_id}",
    response_model=DocumentWithParsedInfo,
    responses=create_openapi_http_exception_doc([
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ]),
    description="API 표준 문서 상세 조회",
)
async def get_api_std_document(
    list_id: int = Path(..., ge=1),
):
    document = await APIStdDocument.find_one(
        Eq(APIStdDocument.list_id, list_id)
    )

    if document is None:
        raise HTTPException(
            status_code=404,
            detail=f"list_id {list_id}에 해당하는 문서를 찾을 수 없습니다."
        )

    open_data_info = await OpenDataInfo.find_one(
        Eq(OpenDataInfo.list_id, list_id)
    )

    response_data = {
        "id": document.id,
        "list_id": document.list_id,
        "title": open_data_info.title if open_data_info else None,
        "description": open_data_info.desc if open_data_info else None,
        "detail_url": document.detail_url,
        "markdown": document.markdown,
        "llm_model": document.llm_model,
        "token_count": document.token_count,
    }

    return DocumentWithParsedInfo(**response_data)
