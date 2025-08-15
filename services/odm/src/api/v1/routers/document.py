from beanie.operators import Eq, In
from fastapi import APIRouter, Query, Path, status, HTTPException, Depends
from typing import Dict, Any, List
from datetime import datetime

from models import OpenDataInfo, APIStdDocument, ParsedAPIInfo
from core.exceptions import create_openapi_http_exception_doc
from core.dependencies import get_cross_collection_service, get_search_service
from service.cross_collection import CrossCollectionService
from service.search import SearchService
from schemas.response import (
    create_paginated_response,
    PaginatedResponse,
    SearchWithDocsItem,
    DocumentWithParsedInfo,
    SuccessRateResponse,
    convert_api_std_document_to_camel_case,
    APIStdDocumentResponse
)


def format_datetime(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


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
            open_data_info = {}

            if list_ids:
                docs = await APIStdDocument.find(
                    In(APIStdDocument.list_id, list_ids)
                ).to_list()

                for doc in docs:
                    std_docs[doc.list_id] = {
                        "token_count": doc.token_count or 0,
                        "has_generated_doc": True,
                        "updated_at": getattr(doc, 'updated_at', None)
                    }

                open_data_docs = await OpenDataInfo.find(
                    In(OpenDataInfo.list_id, list_ids)
                ).to_list()

                for doc in open_data_docs:
                    open_data_info[doc.list_id] = {
                        "updated_at": doc.updated_at,
                        "org_nm": doc.org_nm
                    }

            results = []
            for hit in hits["hits"]:
                source = hit["_source"]
                list_id = source.get("list_id")

                if list_id in std_docs:
                    std_doc_data = std_docs[list_id]
                    token_count = std_doc_data["token_count"]
                    has_generated_doc = std_doc_data["has_generated_doc"]
                    updated_at = std_doc_data.get("updated_at")
                    if updated_at is None and list_id in open_data_info:
                        updated_at = open_data_info[list_id]["updated_at"]

                else:
                    token_count = 0
                    has_generated_doc = False
                    updated_at = open_data_info.get(list_id, {}).get("updated_at") if list_id in open_data_info else None

                updated_at_str = updated_at.isoformat() if updated_at else None
                org_nm = open_data_info.get(list_id, {}).get("org_nm") if list_id in open_data_info else None

                item = SearchWithDocsItem(
                    list_id=list_id,
                    list_title=source.get("list_title", ""),
                    org_nm=org_nm,
                    token_count=token_count,
                    has_generated_doc=has_generated_doc,
                    updated_at=updated_at_str,
                    data_type=source.get("data_type", "API"),
                    score=hit.get("_score"),
                )
                results.append(item.model_dump(by_alias=True))

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
    response_model=List[APIStdDocumentResponse],
    responses=create_openapi_http_exception_doc([
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ]),
    description="API 표준 문서 목록 조회",
)
async def get_api_std_documents(
    list_ids: List[int] = Query(None, description="조회할 list_id 목록 (미입력시 전체 조회)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    try:
        if list_ids:
            documents = (
                await APIStdDocument.find(In(APIStdDocument.list_id, list_ids))
                .skip((page - 1) * page_size)
                .limit(page_size)
                .to_list()
            )

        else:
            documents = (
                await APIStdDocument.find()
                .skip((page - 1) * page_size)
                .limit(page_size)
                .to_list()
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    result = []
    for doc in documents:
        camel_case_dict = convert_api_std_document_to_camel_case(doc.model_dump())
        schema_obj = APIStdDocumentResponse(**camel_case_dict)
        result.append(schema_obj.model_dump(by_alias=True))
    return result


@document_router.get(
    path="/success-rate",
    response_model=SuccessRateResponse,
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

        return SuccessRateResponse(
            total_open_data=total_open_data,
            total_std_docs=total_std_docs,
            success_rate=round(success_rate, 2)
        ).model_dump(by_alias=True)

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
    parsed_info = await ParsedAPIInfo.find_one(
        Eq(ParsedAPIInfo.list_id, list_id)
    )
    open_data_info = await OpenDataInfo.find_one(
        Eq(OpenDataInfo.list_id, list_id)
    )

    document = await APIStdDocument.find_one(
        Eq(APIStdDocument.list_id, list_id)
    )

    if document is None:
        return DocumentWithParsedInfo(
            list_id=open_data_info.list_id if open_data_info else list_id,
            list_title=open_data_info.list_title if open_data_info else None,
            detail_url=f"https://www.data.go.kr/data/{list_id}/openapi.do",
            generated_status=False,
            created_at=format_datetime(open_data_info.created_at) if open_data_info else None,
            updated_at=format_datetime(open_data_info.updated_at) if open_data_info else None,
            org_nm=open_data_info.org_nm if open_data_info else None,
            dept_nm=open_data_info.dept_nm if open_data_info else None,
            phone_number=None,
            is_charged=open_data_info.is_charged if open_data_info else None,
            traffic=None,
            permission=parsed_info.use_prmisn_ennc if parsed_info else None,
            docs=None,
            keywords=open_data_info.keywords if open_data_info else [],
            description=open_data_info.desc if open_data_info else None,
            token_count=0,
            markdown=None,
        ).model_dump(by_alias=True)

    return DocumentWithParsedInfo(
        list_id=document.list_id,
        list_title=open_data_info.list_title if open_data_info else None,
        detail_url=document.detail_url,
        generated_status=True,
        created_at=format_datetime(open_data_info.created_at) if open_data_info else None,
        updated_at=format_datetime(open_data_info.updated_at) if open_data_info else None,
        org_nm=open_data_info.org_nm if open_data_info else None,
        dept_nm=open_data_info.dept_nm if open_data_info else None,
        phone_number=None,
        is_charged=open_data_info.is_charged if open_data_info else None,
        traffic=None,
        permission=parsed_info.use_prmisn_ennc if parsed_info else None,
        docs=None,
        keywords=open_data_info.keywords if open_data_info else [],
        description=open_data_info.desc if open_data_info else None,
        token_count=document.token_count,
        markdown=document.markdown,
    ).model_dump(by_alias=True)
