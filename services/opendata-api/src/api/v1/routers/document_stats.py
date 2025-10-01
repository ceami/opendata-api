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

from fastapi import APIRouter, Depends, Request

from core.dependencies import get_logger_service, get_app_documents_service, limiter
from api.v1.application.open_data.dto import SuccessRateDTO


stats_router = APIRouter(prefix="/document", tags=["stats"])


@stats_router.get(path="/success-rate", response_model=SuccessRateDTO)
@limiter.limit("60/minute")
async def get_success_rate(
    request: Request,
    documents_service=Depends(get_app_documents_service),
    logger: logging.Logger = Depends(lambda: get_logger_service("document_stats")),
):
    try:
        return await documents_service.get_success_rate()
    except Exception as e:
        logger.exception(f"[Document/Stats] 에러: {str(e)}")
        raise
