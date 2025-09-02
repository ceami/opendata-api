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
from datetime import datetime
from typing import Any, Dict, List

from beanie.operators import Eq, In
from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    status,
)

from core.dependencies import (
    get_cross_collection_service,
    get_logger_service,
    get_search_service,
    limiter,
)
from core.exceptions import create_openapi_http_exception_doc
from models import (
    GeneratedAPIDocs,
    GeneratedFileDocs,
    OpenAPIInfo,
    OpenFileInfo,
    SavedRequest,
)
from schemas.response import (
    DocumentWithParsedInfo,
    GeneratedDocumentResponse,
    PaginatedResponse,
    SaveRequestBody,
    SearchWithDocsItem,
    SuccessRateResponse,
    convert_generated_document_to_camel_case,
    create_paginated_response,
)
from service.cross_collection import CrossCollectionService
from service.search import SearchService


def format_datetime(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


document_router = APIRouter(prefix="/document", tags=["document"])


@document_router.get(
    path="",
    response_model=PaginatedResponse[Dict[str, Any]],
    responses=create_openapi_http_exception_doc(
        [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND,
            status.HTTP_429_TOO_MANY_REQUESTS,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ]
    ),
    description="Frontend용 통합 API - 검색 / 데이터 제공 (API + File)",
)
@limiter.limit("60/minute")
async def get_frontend_data(
    request: Request,
    q: str = Query(None, description="검색 키워드"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    size: int = Query(20, ge=1, le=100, description="페이지 크기"),
    sort_by: str = Query(
        "popular",
        description="정렬 기준 (popular: request_cnt 순, trending: updated_at 순)",
    ),
    name_sort_by: str = Query(
        "all", description="이름 정렬 기준 (asc: 오름차순, desc: 내림차순)"
    ),
    org_sort_by: str = Query(
        "all", description="조직 정렬 기준 (asc: 오름차순, desc: 내림차순)"
    ),
    data_type_sort_by: str = Query(
        "all",
        description="데이터 타입 정렬 기준  (asc: 오름차순, desc: 내림차순)",
    ),
    token_count_sort_by: str = Query(
        "all", description="토큰 수 정렬 기준  (asc: 오름차순, desc: 내림차순)"
    ),
    status_sort_by: str = Query(
        "all", description="상태 정렬 기준  (asc: 오름차순, desc: 내림차순)"
    ),
    exact_match: bool = Query(False, description="정확한 매칭 여부"),
    min_score: float = Query(None, description="최소 점수 필터링"),
    use_adaptive_filtering: bool = Query(True, description="자동 필터링 사용"),
    search_service: SearchService = Depends(get_search_service),
    cross_collection_service: CrossCollectionService = Depends(
        get_cross_collection_service
    ),
    logger: logging.Logger = Depends(
        lambda: get_logger_service("document_router")
    ),
):
    try:
        logger.info(
            f"[Document] get_frontend_data_v2 호출: q={q}, page={page}, size={size}, sort_by={sort_by}"
        )
        if q and q.strip():
            from_ = (page - 1) * size

            if use_adaptive_filtering:
                hits = search_service.search_titles_with_adaptive_filtering(
                    query=q.strip(),
                    size=size,
                    from_=from_,
                )
            else:
                hits = search_service.search_titles(
                    query=q.strip(),
                    size=size,
                    from_=from_,
                    exact_match=exact_match,
                    min_score=min_score,
                )

            list_ids = []
            for hit in hits["hits"]:
                try:
                    list_ids.append(int(hit["_source"].get("list_id")))
                except (ValueError, TypeError):
                    continue

            api_data_info = {}
            file_data_info = {}

            if list_ids:
                api_docs = await OpenAPIInfo.find(
                    {"list_id": {"$in": list_ids}}
                ).to_list()

                for doc in api_docs:
                    api_data_info[doc.list_id] = {
                        "list_title": doc.list_title,
                        "org_nm": doc.org_nm,
                        "data_type": "API",
                    }

                file_docs = await OpenFileInfo.find(
                    {"list_id": {"$in": list_ids}}
                ).to_list()

                for doc in file_docs:
                    file_data_info[doc.list_id] = {
                        "list_title": getattr(doc, "list_title", None)
                        or getattr(doc, "title", None),
                        "org_nm": getattr(doc, "org_nm", None)
                        or getattr(doc, "dept_nm", None),
                        "data_type": "FILE",
                    }

            api_generated_docs = {}
            file_generated_docs = {}

            if list_ids:
                generated_api_docs = await GeneratedAPIDocs.find(
                    {"list_id": {"$in": list_ids}}
                ).to_list()

                for doc in generated_api_docs:
                    api_generated_docs[doc.list_id] = {
                        "token_count": doc.token_count,
                        "has_generated_doc": True,
                        "generated_at": getattr(doc, "generated_at", None),
                    }

                generated_file_docs = await GeneratedFileDocs.find(
                    {"list_id": {"$in": list_ids}}
                ).to_list()

                for doc in generated_file_docs:
                    file_generated_docs[doc.list_id] = {
                        "token_count": doc.token_count,
                        "has_generated_doc": True,
                        "generated_at": getattr(doc, "generated_at", None),
                    }

            results = []
            for hit in hits["hits"]:
                source = hit["_source"]
                list_id = int(source.get("list_id"))
                data_type = source.get("data_type", "API")

                if list_id in api_data_info:
                    api_info = api_data_info[list_id]

                    if list_id in api_generated_docs:
                        generated_info = api_generated_docs[list_id]
                        token_count = generated_info["token_count"]
                        has_generated_doc = generated_info["has_generated_doc"]
                        generated_at = generated_info["generated_at"]
                    else:
                        token_count = 0
                        has_generated_doc = False
                        generated_at = None

                    generated_at_str = (
                        generated_at.isoformat() if generated_at else None
                    )

                    item = SearchWithDocsItem(
                        list_id=list_id,
                        list_title=api_info["list_title"],
                        org_nm=api_info["org_nm"],
                        token_count=token_count,
                        has_generated_doc=has_generated_doc,
                        updated_at=generated_at_str,
                        data_type="API",
                        score=hit.get("_score"),
                    )

                elif list_id in file_data_info:
                    file_info = file_data_info[list_id]

                    if list_id in file_generated_docs:
                        generated_info = file_generated_docs[list_id]
                        token_count = generated_info["token_count"]
                        has_generated_doc = generated_info["has_generated_doc"]
                        generated_at = generated_info["generated_at"]
                    else:
                        token_count = 0
                        has_generated_doc = False
                        generated_at = None

                    generated_at_str = (
                        generated_at.isoformat() if generated_at else None
                    )

                    item = SearchWithDocsItem(
                        list_id=list_id,
                        list_title=file_info["list_title"],
                        org_nm=file_info["org_nm"],
                        token_count=token_count,
                        has_generated_doc=has_generated_doc,
                        updated_at=generated_at_str,
                        data_type="FILE",
                        score=hit.get("_score"),
                    )

                elif list_id in file_generated_docs:
                    generated_info = file_generated_docs[list_id]
                    token_count = generated_info["token_count"]
                    has_generated_doc = generated_info["has_generated_doc"]
                    generated_at = generated_info["generated_at"]
                    generated_at_str = (
                        generated_at.isoformat() if generated_at else None
                    )
                    org_nm = None

                    if list_id in api_data_info:
                        org_nm = api_data_info[list_id]["org_nm"]
                    elif source.get("org_nm"):
                        org_nm = source.get("org_nm")

                    item = SearchWithDocsItem(
                        list_id=list_id,
                        list_title=source.get("list_title", ""),
                        org_nm=org_nm,
                        token_count=token_count,
                        has_generated_doc=has_generated_doc,
                        updated_at=generated_at_str,
                        data_type="FILE",
                        score=hit.get("_score"),
                    )

                else:
                    item = SearchWithDocsItem(
                        list_id=list_id,
                        list_title=source.get("list_title", ""),
                        org_nm=None,
                        token_count=0,
                        has_generated_doc=False,
                        updated_at=None,
                        data_type=source.get("data_type", "API"),
                        score=hit.get("_score"),
                    )

                results.append(item.model_dump(by_alias=True))

            return create_paginated_response(
                items=results,
                total=hits["total"]["value"],
                page=page,
                size=size,
            )

        else:
            if sort_by not in ["popular", "trending", "all"]:
                raise HTTPException(
                    status_code=400,
                    detail="sort_by는 'popular' 또는 'trending'이어야 합니다",
                )

            result = await cross_collection_service.get_unified_data_paginated(
                page=page,
                size=size,
                sort_by=sort_by,
                name_sort_by=name_sort_by,
                org_sort_by=org_sort_by,
                data_type_sort_by=data_type_sort_by,
                token_count_sort_by=token_count_sort_by,
                status_sort_by=status_sort_by,
            )

            formatted_items = []
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

                generated_at_str = (
                    format_datetime(generated_at) if generated_at else None
                )

                formatted_item = SearchWithDocsItem(
                    list_id=list_id,
                    list_title=item.get("list_title", ""),
                    org_nm=item.get("org_nm"),
                    token_count=item.get("token_count", 0),
                    has_generated_doc=item.get("has_generated_doc", False),
                    updated_at=generated_at_str,
                    data_type=data_type,
                    score=None,
                )
                formatted_items.append(formatted_item.model_dump(by_alias=True))

            logger.info(
                f"[Document] get_frontend_data_v2 완료: 검색 결과 {len(formatted_items)}개"
            )
            return create_paginated_response(
                items=formatted_items,
                total=result["total"],
                page=result["page"],
                size=result["size"],
            )

    except Exception as e:
        logger.error(f"[Document] get_frontend_data_v2 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@document_router.get(
    path="/std-docs",
    response_model=List[GeneratedDocumentResponse],
    responses=create_openapi_http_exception_doc(
        [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND,
            status.HTTP_429_TOO_MANY_REQUESTS,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ]
    ),
    description="생성된 API/File 문서 목록 조회",
)
@limiter.limit("60/minute")
async def get_generated_documents(
    request: Request,
    list_ids: List[int] = Query(
        None, description="조회할 list_id 목록 (미입력시 전체 조회)"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    try:
        result = []

        if list_ids:
            api_docs = (
                await GeneratedAPIDocs.find(
                    In(GeneratedAPIDocs.list_id, list_ids)
                )
                .skip((page - 1) * page_size)
                .limit(page_size)
                .to_list()
            )
        else:
            api_docs = (
                await GeneratedAPIDocs.find()
                .skip((page - 1) * page_size)
                .limit(page_size)
                .to_list()
            )

        for doc in api_docs:
            camel_case_dict = convert_generated_document_to_camel_case(
                doc.model_dump(), "API"
            )
            schema_obj = GeneratedDocumentResponse(**camel_case_dict)
            result.append(schema_obj.model_dump(by_alias=True))

        if list_ids:
            file_docs = (
                await GeneratedFileDocs.find(
                    In(GeneratedFileDocs.list_id, list_ids)
                )
                .skip((page - 1) * page_size)
                .limit(page_size)
                .to_list()
            )
        else:
            file_docs = (
                await GeneratedFileDocs.find()
                .skip((page - 1) * page_size)
                .limit(page_size)
                .to_list()
            )

        for doc in file_docs:
            camel_case_dict = convert_generated_document_to_camel_case(
                doc.model_dump(), "FILE"
            )
            schema_obj = GeneratedDocumentResponse(**camel_case_dict)
            result.append(schema_obj.model_dump(by_alias=True))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return result


@document_router.get(
    path="/success-rate",
    response_model=SuccessRateResponse,
    responses=create_openapi_http_exception_doc(
        [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND,
            status.HTTP_429_TOO_MANY_REQUESTS,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ]
    ),
    description="성공률 조회",
)
@limiter.limit("60/minute")
async def get_success_rate(request: Request):
    try:
        total_open_data = await OpenAPIInfo.count()
        total_std_docs = await GeneratedAPIDocs.count()
        success_rate = (
            (total_std_docs / total_open_data * 100)
            if total_open_data > 0
            else 0
        )

        return SuccessRateResponse(
            total_open_data=total_open_data,
            total_std_docs=total_std_docs,
            success_rate=round(success_rate, 2),
        ).model_dump(by_alias=True)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@document_router.get(
    path="/std-docs/{list_id}",
    response_model=DocumentWithParsedInfo,
    responses=create_openapi_http_exception_doc(
        [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND,
            status.HTTP_429_TOO_MANY_REQUESTS,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ]
    ),
    description="API 표준 문서 상세 조회 (API + File)",
)
@limiter.limit("60/minute")
async def get_api_std_document(
    request: Request,
    list_id: int = Path(..., ge=1),
):
    api_document = await GeneratedAPIDocs.find_one(
        Eq(GeneratedAPIDocs.list_id, list_id)
    )

    if api_document:
        open_api_info = await OpenAPIInfo.find_one(
            Eq(OpenAPIInfo.list_id, list_id)
        )

        return DocumentWithParsedInfo(
            list_id=api_document.list_id,
            data_type="API",
            list_title=open_api_info.list_title if open_api_info else None,
            detail_url=f"https://www.data.go.kr/data/{list_id}/openapi.do",
            generated_status=True,
            created_at=format_datetime(open_api_info.created_at)
            if open_api_info
            else None,
            updated_at=format_datetime(open_api_info.updated_at)
            if open_api_info
            else None,
            description=open_api_info.desc.replace("<br/>", "\n")
            if open_api_info and open_api_info.desc
            else None,
            org_nm=open_api_info.org_nm if open_api_info else None,
            dept_nm=open_api_info.dept_nm if open_api_info else None,
            is_charged=open_api_info.is_charged if open_api_info else None,
            share_scope_nm=open_api_info.share_scope_nm,
            keywords=open_api_info.keywords if open_api_info else [],
            token_count=api_document.token_count,
            generated_at=format_datetime(api_document.generated_at)
            if api_document and api_document.generated_at
            else None,
            markdown=api_document.markdown,
        ).model_dump(by_alias=True)

    file_document = await GeneratedFileDocs.find_one(
        Eq(GeneratedFileDocs.list_id, list_id)
    )

    if file_document:
        open_file_info = await OpenFileInfo.find_one(
            Eq(OpenFileInfo.list_id, list_id)
        )

        return DocumentWithParsedInfo(
            list_id=file_document.list_id,
            data_type="FILE",
            list_title=getattr(open_file_info, "list_title", None)
            or getattr(open_file_info, "title", None),
            detail_url=f"https://www.data.go.kr/data/{list_id}/fileData.do",
            generated_status=file_document is not None,
            created_at=format_datetime(open_file_info.created_at)
            if open_file_info
            else None,
            updated_at=format_datetime(open_file_info.updated_at)
            if open_file_info
            else None,
            description=open_file_info.desc.replace("<br/>", "\n")
            if open_file_info and open_file_info.desc
            else None,
            org_nm=open_file_info.org_nm if open_file_info else None,
            dept_nm=open_file_info.dept_nm if open_file_info else None,
            is_charged=open_file_info.is_charged if open_file_info else None,
            share_scope_nm=open_file_info.share_scope_nm,
            keywords=open_file_info.keywords if open_file_info else [],
            token_count=file_document.token_count if file_document else 0,
            generated_at=format_datetime(file_document.generated_at)
            if file_document
            else None,
            markdown=file_document.markdown if file_document else None,
        ).model_dump(by_alias=True)

    open_api_info = await OpenAPIInfo.find_one(Eq(OpenAPIInfo.list_id, list_id))

    if open_api_info:
        return DocumentWithParsedInfo(
            list_id=open_api_info.list_id,
            data_type="API",
            list_title=open_api_info.list_title,
            detail_url=f"https://www.data.go.kr/data/{list_id}/openapi.do",
            generated_status=False,
            created_at=format_datetime(open_api_info.created_at),
            updated_at=format_datetime(open_api_info.updated_at),
            description=open_api_info.desc.replace("<br/>", "\n")
            if open_api_info.desc
            else None,
            org_nm=open_api_info.org_nm,
            dept_nm=open_api_info.dept_nm,
            is_charged=open_api_info.is_charged,
            share_scope_nm=open_api_info.share_scope_nm,
            keywords=open_api_info.keywords,
            token_count=0,
            generated_at=None,
            markdown=None,
        ).model_dump(by_alias=True)

    open_file_info = await OpenFileInfo.find_one(
        Eq(OpenFileInfo.list_id, list_id)
    )

    if open_file_info:
        return DocumentWithParsedInfo(
            list_id=open_file_info.list_id,
            data_type="FILE",
            list_title=getattr(open_file_info, "list_title", None)
            or getattr(open_file_info, "title", None),
            detail_url=f"https://www.data.go.kr/data/{list_id}/fileData.do",
            generated_status=False,
            created_at=format_datetime(open_file_info.created_at),
            updated_at=format_datetime(open_file_info.updated_at),
            description=open_file_info.desc.replace("<br/>", "\n")
            if open_file_info.desc
            else None,
            org_nm=open_file_info.org_nm,
            dept_nm=open_file_info.dept_nm,
            is_charged=open_file_info.is_charged,
            share_scope_nm=open_file_info.share_scope_nm,
            keywords=open_file_info.keywords if open_file_info else [],
            token_count=0,
            generated_at=None,
            markdown=None,
        ).model_dump(by_alias=True)

    raise HTTPException(status_code=404, detail="데이터를 찾을 수 없습니다")


@document_router.post(
    path="/save-request", response_model=dict, description="list_id나 url 저장"
)
@limiter.limit("60/minute")
async def save_request(
    request: Request,
    body: SaveRequestBody = Body(..., description="저장할 list_id 또는 url"),
):
    if not body.list_id and not body.url:
        raise HTTPException(
            status_code=400, detail="list_id나 url 중 하나는 필수입니다."
        )

    saved = SavedRequest(
        list_id=body.list_id, url=body.url, created_at=datetime.now()
    )
    await saved.insert()
    return {"message": "저장완료", "id": str(saved.id)}
