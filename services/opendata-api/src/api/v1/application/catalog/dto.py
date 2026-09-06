"""Public responses for collected metadata, independent of AI documents."""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from models.catalog import CatalogType, PortalCatalogFields


class CatalogResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PortalCatalogDTO(PortalCatalogFields, CatalogResponse):
    catalog_id: str


class PortalCatalogDetailDTO(PortalCatalogDTO):
    detail: dict[str, Any] | None = None


class SourceRecordDTO(CatalogResponse):
    source_id: str
    catalog_id: str
    data_type: CatalogType
    source: str
    record: dict[str, Any] = Field(default_factory=dict)
    collected_at: datetime | None = None
    is_active: bool = True
    removed_at: datetime | None = None


class ResourceDTO(CatalogResponse):
    resource_id: str
    catalog_id: str
    kind: str
    url: str
    raw_id: str
    content_type: str
    fetched_at: datetime | None = None
    is_active: bool = True
    removed_at: datetime | None = None


Item = TypeVar("Item")


class CatalogPageDTO(CatalogResponse, Generic[Item]):
    items: list[Item]
    total: int
    page: int
    size: int
    total_pages: int
    has_next: bool
    has_prev: bool
