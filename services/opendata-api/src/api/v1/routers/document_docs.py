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

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from core.dependencies import get_logger_service, get_app_documents_service, limiter
from api.v1.application.open_data.dto import DocumentDetailDTO, GeneratedDocItemDTO


docs_router = APIRouter(prefix="/document", tags=["docs"])


@docs_router.get(path="/std-docs", response_model=list[GeneratedDocItemDTO])
@limiter.limit("60/minute")
async def get_generated_documents(
    request: Request,
    list_ids: list[int] = Query(None, description="조회할 list_id 목록 (미입력시 전체 조회)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    documents_service=Depends(get_app_documents_service),
    logger: logging.Logger = Depends(lambda: get_logger_service("document_docs")),
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
    documents_service=Depends(get_app_documents_service),
    logger: logging.Logger = Depends(lambda: get_logger_service("document_docs")),
):
    try:
        return await documents_service.get_std_doc_detail(list_id=list_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"[Document/Docs] 상세 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
