"""Read collected catalogs and their lossless source payloads from MongoDB."""

import gzip
import json
import re
import zlib
from typing import Any, TypeVar

from gridfs.errors import NoFile
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket
from starlette.concurrency import run_in_threadpool

from models.catalog import CatalogType

from .dto import (
    CatalogPageDTO,
    PortalCatalogDetailDTO,
    PortalCatalogDTO,
    ResourceDTO,
    SourceRecordDTO,
)

PageItem = TypeVar("PageItem")


class CatalogNotFoundError(LookupError):
    pass


class StoredMetadataUnavailableError(RuntimeError):
    pass


def _page(
    items: list[PageItem], total: int, page: int, size: int
) -> CatalogPageDTO[PageItem]:
    pages = (total + size - 1) // size
    return CatalogPageDTO(
        items=items,
        total=total,
        page=page,
        size=size,
        total_pages=pages,
        has_next=page < pages,
        has_prev=page > 1,
    )


class PortalCatalogService:
    def __init__(self, database: AsyncIOMotorDatabase) -> None:
        self.db = database

    async def list_catalog(
        self,
        *,
        data_type: CatalogType | None = None,
        q: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> CatalogPageDTO[PortalCatalogDTO]:
        query: dict[str, Any] = {"is_active": {"$ne": False}}
        if data_type:
            query["data_type"] = data_type
        if q and q.strip():
            query["title"] = {"$regex": re.escape(q.strip()), "$options": "i"}
        total = await self.db.portal_catalog.count_documents(query)
        rows = await (
            self.db.portal_catalog.find(query)
            .sort([("data_type", 1), ("list_id", 1)])
            .skip((page - 1) * size)
            .limit(size)
            .to_list(length=size)
        )
        items = [PortalCatalogDTO(catalog_id=row["_id"], **row) for row in rows]
        return _page(items, total, page, size)

    async def _catalog(
        self, data_type: CatalogType, list_id: int
    ) -> dict[str, Any]:
        record = await self.db.portal_catalog.find_one(
            {
                "_id": f"{data_type}:{list_id}",
                "is_active": {"$ne": False},
            }
        )
        if record is None:
            raise CatalogNotFoundError("Catalog not found")
        return record

    async def _raw(self, raw_id: str) -> bytes:
        try:
            bucket = AsyncIOMotorGridFSBucket(self.db, bucket_name="portal_raw")
            stream = await bucket.open_download_stream(raw_id)
            try:
                compressed = await stream.read()
            finally:
                stream.close()
            return await run_in_threadpool(gzip.decompress, compressed)
        except (NoFile, OSError, EOFError, zlib.error) as error:
            raise StoredMetadataUnavailableError(
                "Stored metadata cannot be read; recollect this catalog"
            ) from error

    async def get_detail(
        self, data_type: CatalogType, list_id: int
    ) -> PortalCatalogDetailDTO:
        record = await self._catalog(data_type, list_id)
        detail = None
        if record.get("parsed_detail_ref"):
            raw = await self._raw(record["parsed_detail_ref"])
            try:
                detail = await run_in_threadpool(json.loads, raw)
            except (ValueError, UnicodeError) as error:
                raise StoredMetadataUnavailableError(
                    "Stored detail is invalid; recollect this catalog"
                ) from error
            if not isinstance(detail, dict):
                raise StoredMetadataUnavailableError(
                    "Stored detail is invalid; recollect this catalog"
                )
        return PortalCatalogDetailDTO(
            catalog_id=record["_id"], detail=detail, **record
        )

    async def list_sources(
        self,
        data_type: CatalogType,
        list_id: int,
        *,
        page: int = 1,
        size: int = 20,
    ) -> CatalogPageDTO[SourceRecordDTO]:
        catalog = await self._catalog(data_type, list_id)
        query = {
            "catalog_id": catalog["_id"],
            "is_active": {"$ne": False},
        }
        total = await self.db.portal_source_records.count_documents(query)
        rows = await (
            self.db.portal_source_records.find(query)
            .sort("_id", 1)
            .skip((page - 1) * size)
            .limit(size)
            .to_list(length=size)
        )
        items = [SourceRecordDTO(source_id=row["_id"], **row) for row in rows]
        return _page(items, total, page, size)

    async def list_resources(
        self,
        data_type: CatalogType,
        list_id: int,
        *,
        page: int = 1,
        size: int = 20,
    ) -> CatalogPageDTO[ResourceDTO]:
        catalog = await self._catalog(data_type, list_id)
        query = {
            "catalog_id": catalog["_id"],
            "is_active": {"$ne": False},
            "$or": [
                {"kind": {"$ne": "reference_document"}},
                {"reference_head": {"$exists": True}},
            ],
        }
        total = await self.db.portal_resources.count_documents(query)
        rows = await (
            self.db.portal_resources.find(query)
            .sort("_id", 1)
            .skip((page - 1) * size)
            .limit(size)
            .to_list(length=size)
        )
        items = [ResourceDTO(resource_id=row["_id"], **row) for row in rows]
        return _page(items, total, page, size)

    async def get_raw_resource(
        self, data_type: CatalogType, list_id: int, resource_id: str
    ) -> bytes:
        catalog = await self._catalog(data_type, list_id)
        resource = await self.db.portal_resources.find_one(
            {
                "_id": resource_id,
                "catalog_id": catalog["_id"],
                "is_active": {"$ne": False},
                "$or": [
                    {"kind": {"$ne": "reference_document"}},
                    {"reference_head": {"$exists": True}},
                ],
            }
        )
        if resource is None:
            raise CatalogNotFoundError("Catalog resource not found")
        validated = ResourceDTO(resource_id=resource["_id"], **resource)
        return await self._raw(validated.raw_id)
