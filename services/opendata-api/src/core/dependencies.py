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
import asyncio
import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from elasticsearch import Elasticsearch
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

from db import MongoDB

from .settings import Settings, get_settings

limiter = Limiter(key_func=get_remote_address)


def rate_limit_exceeded_handler_wrapper(
    request: Request, exc: Exception
) -> Response:
    return _rate_limit_exceeded_handler(request, exc)


def get_rate_limit_exceeded_handler():
    return rate_limit_exceeded_handler_wrapper


class ServiceContainer:
    _instance: Any | None = None
    _services: dict[str, Any] = {}
    _semaphores: dict[str, asyncio.Semaphore] = {}
    _loggers: dict[str, logging.Logger] = {}
    _initialized: bool = False
    _settings: Settings | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def set_settings(self, settings: Settings) -> None:
        self._settings = settings

    def get_settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    async def initialize(self) -> None:
        if self._initialized:
            return

        logger = self.get_logger("service_container")
        logger.info("서비스 컨테이너 초기화 시작")

        try:
            settings = self.get_settings()
            await MongoDB.init(settings.MONGO_URL, settings.MONGO_DB)
            self._services["mongo_client"] = MongoDB.get_client()

            es_client = Elasticsearch([settings.ELASTICSEARCH_URL])
            self._services["elasticsearch"] = es_client

            self._initialized = True
            logger.info("서비스 컨테이너 초기화 완료")
        except Exception as e:
            logger.error(f"서비스 컨테이너 초기화 실패: {e}")
            raise e

    async def shutdown(self) -> None:
        logger = self.get_logger("service_container")
        logger.info("서비스 컨테이너 종료 시작")

        await MongoDB.close()

        for service_name, service in self._services.items():
            try:
                if hasattr(service, "close"):
                    await service.close()
                elif hasattr(service, "shutdown"):
                    await service.shutdown()
            except Exception as e:
                logger.warning(f"서비스 {service_name} 종료 중 오류: {e}")

        self.clear_cache()
        logger.info("서비스 컨테이너 종료 완료")

    def clear_cache(self) -> None:
        self._services.clear()
        self._semaphores.clear()
        self._loggers.clear()
        self._initialized = False

    def health_check(self) -> dict[str, Any]:
        health_status = {
            "initialized": self._initialized,
            "services_count": len(self._services),
            "semaphores_count": len(self._semaphores),
            "loggers_count": len(self._loggers),
            "services": {},
        }

        for name, service in self._services.items():
            try:
                is_healthy = hasattr(service, "__dict__")
                health_status["services"][name] = {
                    "status": "healthy" if is_healthy else "unhealthy",
                    "type": type(service).__name__,
                }
            except Exception as e:
                health_status["services"][name] = {
                    "status": "error",
                    "error": str(e),
                }

        return health_status

    @lru_cache(maxsize=32)
    def get_logger(self, name: str = "ml_server") -> logging.Logger:
        from utils.logger import setup_logger

        if name not in self._loggers:
            self._loggers[name] = setup_logger(
                name=name, service_name="ml_server"
            )
        return self._loggers[name]

    def get_service_logger(self, service_name: str) -> logging.Logger:
        return self.get_logger(f"service.{service_name}")


service_container = ServiceContainer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from utils.logger import setup_logger

    logger = setup_logger("lifespan", service_name="core-server")
    logger.info("애플리케이션 시작 중...")

    await service_container.initialize()
    logger.info("애플리케이션 초기화 완료")

    yield

    logger.info("애플리케이션 종료 중...")

    await service_container.shutdown()
    logger.info("애플리케이션 종료 완료")


def get_service_container() -> ServiceContainer:
    return service_container


def get_health_status() -> dict[str, Any]:
    return service_container.health_check()


def get_settings_dependency() -> Settings:
    return get_settings()


def get_service_container_with_settings(
    settings: Settings = Depends(get_settings_dependency),
) -> ServiceContainer:
    service_container.set_settings(settings)
    return service_container


def get_elasticsearch_client() -> Elasticsearch:
    return service_container._services.get("elasticsearch")


def get_mongo_client():
    return service_container._services.get("mongo_client")


def get_cross_collection_service():
    from api.v1.application.catalog.catalog_service import CatalogService

    mongo_client = get_mongo_client()
    logger = service_container.get_service_logger("catalog")
    return CatalogService(mongo_client, logger)


def get_search_service():
    from api.v1.application.search.search_provider import SearchProvider

    es_client = get_elasticsearch_client()
    if not es_client:
        raise HTTPException(
            status_code=500,
            detail="Elasticsearch 클라이언트를 사용할 수 없습니다.",
        )

    return SearchProvider(es_client)


def get_logger_service(service_name: str):
    return service_container.get_service_logger(service_name)


def get_app_search_service():
    from api.v1.application.open_data.search_service import SearchAppService

    return SearchAppService()


def get_app_pagination_service():
    from api.v1.application.open_data.pagination_service import (
        PaginationAppService,
    )

    cross = get_cross_collection_service()
    return PaginationAppService(cross)


def get_app_documents_service():
    from api.v1.application.open_data.documents_service import (
        DocumentsAppService,
    )

    return DocumentsAppService()


def get_recommendation_service():
    from recommend_system.recommendation_service import RecommendationService

    return RecommendationService()
