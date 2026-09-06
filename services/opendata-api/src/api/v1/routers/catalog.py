"""Public read API for the collected FILE/API/STD/LINKED catalog."""

from collections.abc import Awaitable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import ValidationError
from pymongo.errors import PyMongoError

from api.v1.application.catalog.dto import (
    CatalogPageDTO,
    PortalCatalogDetailDTO,
    PortalCatalogDTO,
    ResourceDTO,
    SourceRecordDTO,
)
from api.v1.application.catalog.portal_catalog_service import (
    CatalogNotFoundError,
    PortalCatalogService,
    StoredMetadataUnavailableError,
)
from db import MongoDB
from models.catalog import CatalogType

catalog_router = APIRouter(prefix="/catalog", tags=["catalog"])
Result = TypeVar("Result")


def get_catalog_service() -> PortalCatalogService:
    return PortalCatalogService(MongoDB.get_db())


CatalogServiceDependency = Annotated[
    PortalCatalogService, Depends(get_catalog_service)
]


async def _read(operation: Awaitable[Result]) -> Result:
    try:
        return await operation
    except CatalogNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (
        StoredMetadataUnavailableError,
        ValidationError,
        PyMongoError,
    ) as error:
        raise HTTPException(
            status_code=503,
            detail="Collected metadata is temporarily unavailable",
        ) from error


@catalog_router.get("", response_model=CatalogPageDTO[PortalCatalogDTO])
async def list_catalog(
    service: CatalogServiceDependency,
    data_type: Annotated[CatalogType | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CatalogPageDTO[PortalCatalogDTO]:
    return await _read(
        service.list_catalog(data_type=data_type, q=q, page=page, size=size)
    )


@catalog_router.get(
    "/{data_type}/{list_id}", response_model=PortalCatalogDetailDTO
)
async def catalog_detail(
    data_type: CatalogType,
    list_id: Annotated[int, Path(ge=1)],
    service: CatalogServiceDependency,
) -> PortalCatalogDetailDTO:
    return await _read(service.get_detail(data_type, list_id))


@catalog_router.get(
    "/{data_type}/{list_id}/sources",
    response_model=CatalogPageDTO[SourceRecordDTO],
)
async def catalog_sources(
    data_type: CatalogType,
    list_id: Annotated[int, Path(ge=1)],
    service: CatalogServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CatalogPageDTO[SourceRecordDTO]:
    return await _read(
        service.list_sources(data_type, list_id, page=page, size=size)
    )


@catalog_router.get(
    "/{data_type}/{list_id}/resources",
    response_model=CatalogPageDTO[ResourceDTO],
)
async def catalog_resources(
    data_type: CatalogType,
    list_id: Annotated[int, Path(ge=1)],
    service: CatalogServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CatalogPageDTO[ResourceDTO]:
    return await _read(
        service.list_resources(data_type, list_id, page=page, size=size)
    )


@catalog_router.get(
    "/{data_type}/{list_id}/resources/{resource_id}/raw",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def catalog_resource_raw(
    data_type: CatalogType,
    list_id: Annotated[int, Path(ge=1)],
    resource_id: str,
    service: CatalogServiceDependency,
) -> Response:
    content = await _read(
        service.get_raw_resource(data_type, list_id, resource_id)
    )
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="portal-metadata.bin"',
            "X-Content-Type-Options": "nosniff",
        },
    )
