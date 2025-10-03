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

from fastapi import APIRouter, Depends, HTTPException, Request

from core.dependencies import (
    get_logger_service,
    get_cross_collection_service,
)


admin_router = APIRouter(prefix="/document", tags=["admin"])


@admin_router.post(path="/ranks/rebuild", response_model=dict[str, int])
async def rebuild_ranked_list(
    request: Request,
    cross_collection_service=Depends(get_cross_collection_service),
    logger: logging.Logger = Depends(lambda: get_logger_service("document_admin")),
):
    try:
        return await cross_collection_service.rebuild_rank_snapshots()
    except Exception as e:
        logger.exception(f"[Document/Admin] rebuild_ranked_list 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
