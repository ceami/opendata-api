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

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.security import HTTPBasic
from slowapi.errors import RateLimitExceeded
from starlette.middleware.cors import CORSMiddleware

from api import (
    list_router,
    docs_router,
    stats_router,
    admin_router,
    search_titles_router,
    search_titles_docs_router,
    comments_router,
)
from core.dependencies import (
    get_health_status,
    get_rate_limit_exceeded_handler,
    lifespan,
    limiter,
)
from core.settings import get_settings
from utils.logger import setup_logger

settings = get_settings()

logger = setup_logger(
    name="core_server_app",
    log_level=settings.log_level,
    service_name="core-server",
    log_dir="/tmp/logs",
)

app = FastAPI(
    title=settings.title,
    description=settings.description,
    version=settings.version,
    root_path=settings.root_path,
    docs_url="/docs" if settings.enable_docs else None,
    redoc_url="/redoc" if settings.enable_redoc else None,
    debug=settings.debug,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, get_rate_limit_exceeded_handler())

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

app.include_router(list_router, prefix="/api/v1", tags=["document"])
app.include_router(docs_router, prefix="/api/v1", tags=["document"])
app.include_router(stats_router, prefix="/api/v1", tags=["document"])
app.include_router(admin_router, prefix="/api/v1", tags=["document"])
app.include_router(search_titles_router, prefix="/api/v1", tags=["search"])
app.include_router(search_titles_docs_router, prefix="/api/v1", tags=["search"])
app.include_router(comments_router, prefix="/api/v1", tags=["comments"])

security = HTTPBasic()


@app.get("/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "core-server",
        "version": settings.version,
        "environment": settings.env,
    }


@app.get("/health/services")
async def services_health_check(
    health_status: dict[str, Any] = Depends(get_health_status),
) -> dict[str, Any]:
    is_initialized = health_status.get("initialized", False)
    status = "ok" if is_initialized else "initializing"

    logger.info(f"서비스 헬스 체크 - 상태: {status}")

    return {
        "status": status,
        "service": "core-server",
        "version": settings.version,
        "environment": settings.env,
        "details": health_status,
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=True,
    )
