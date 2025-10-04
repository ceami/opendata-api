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

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
)

from api.v1.application.open_data.dto import (
    DocumentDetailDTO,
    GeneratedDocItemDTO,
    RecommendationItemDTO,
    SaveRequestDTO,
)
from core.dependencies import (
    get_app_documents_service,
    get_logger_service,
    get_recommendation_service,
    limiter,
)
from models import OpenAPIInfo, OpenFileInfo

docs_router = APIRouter(prefix="/document", tags=["docs"])


@docs_router.get(path="/std-docs", response_model=list[GeneratedDocItemDTO])
@limiter.limit("60/minute")
async def get_generated_documents(
    request: Request,
    list_ids: list[int] | None = Query(
        None, description="조회할 list_id 목록 (미입력시 전체 조회)"
    ),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(10, ge=1, le=100, description="페이지 크기"),
    documents_service=Depends(get_app_documents_service),
    logger: logging.Logger = Depends(
        lambda: get_logger_service("document_docs")
    ),
):
    try:
        return await documents_service.get_generated_documents(
            list_ids=list_ids, page=page, page_size=page_size
        )
    except Exception as e:
        logger.exception(f"[Document/Docs] 목록 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@docs_router.get(path="/std-docs/{list_id}", response_model=DocumentDetailDTO)
@limiter.limit("60/minute")
async def get_std_doc_detail(
    request: Request,
    list_id: int = Path(..., ge=1),
    include_recommendations: bool = Query(
        True, description="추천 아이템 포함 여부"
    ),
    documents_service=Depends(get_app_documents_service),
    recommendation_service=Depends(get_recommendation_service),
    logger: logging.Logger = Depends(
        lambda: get_logger_service("document_docs")
    ),
):
    try:
        doc_detail = await documents_service.get_std_doc_detail(list_id=list_id)

        recommendations = []
        if include_recommendations:
            try:
                rec_results = await recommendation_service.get_recommendations(
                    doc_id=str(list_id),
                    target_doc_type=doc_detail.data_type,
                    top_k=4,
                    use_cache=True,
                )

                for rec in rec_results:
                    try:
                        doc_id_int = int(rec["doc_id"])

                        api_doc = await OpenAPIInfo.find_one(
                            OpenAPIInfo.list_id == doc_id_int
                        )
                        file_doc = await OpenFileInfo.find_one(
                            OpenFileInfo.list_id == doc_id_int
                        )

                        if api_doc:
                            recommendations.append(
                                RecommendationItemDTO(
                                    list_id=api_doc.list_id,
                                    list_title=api_doc.list_title,
                                    org_nm=api_doc.org_nm,
                                    data_type="API",
                                    similarity_score=rec.get(
                                        "similarity_score"
                                    ),
                                )
                            )
                        elif file_doc:
                            recommendations.append(
                                RecommendationItemDTO(
                                    list_id=file_doc.list_id or 0,
                                    list_title=file_doc.list_title or "",
                                    org_nm=file_doc.org_nm,
                                    data_type="FILE",
                                    similarity_score=rec.get(
                                        "similarity_score"
                                    ),
                                )
                            )
                    except (ValueError, Exception) as e:
                        logger.warning(
                            f"추천 아이템 {rec.get('doc_id')} 변환 실패: {e}"
                        )
                        continue

            except Exception as e:
                logger.warning(f"추천 조회 실패: {e}")

        doc_detail.recommendations = recommendations

        return doc_detail

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"[Document/Docs] 상세 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@docs_router.post(path="/save-request", response_model=dict[str, str])
@limiter.limit("60/minute")
async def save_request(
    request: Request,
    body: SaveRequestDTO = Body(..., description="저장할 list_id 또는 url"),
    documents_service=Depends(get_app_documents_service),
    logger: logging.Logger = Depends(
        lambda: get_logger_service("document_docs")
    ),
):
    try:
        return await documents_service.save_request(
            list_id=body.list_id, url=body.url
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"[Document/Docs] save_request 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
