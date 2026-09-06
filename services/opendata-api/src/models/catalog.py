"""The common collected catalog and metadata shared by legacy API models."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from beanie import Document
from pydantic import BaseModel, Field, model_validator

CatalogType = Literal["FILE", "API", "STD", "LINKED"]
CATALOG_TYPES = {"FILE", "API", "STD", "LINKED"}
DetailFormat = Literal["LINK", "SWAGGER", "TABLE", "ERROR"]


def file_data_format(record: Mapping[str, Any]) -> str | None:
    """Read both new explicit formats and the old format-in-data_type field."""
    for name in ("data_format", "data_type", "ext"):
        value = record.get(name)
        if isinstance(value, str) and value.strip():
            value = value.strip()
            if value.upper() not in CATALOG_TYPES:
                return value
    return None


class CollectedMetadata(BaseModel):
    source_catalog_id: str | None = None
    collected_at: datetime | None = None
    detail_url: str | None = None
    contact: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    operations: list[dict[str, Any]] = Field(default_factory=list)
    detail_format: DetailFormat | None = None


class PortalCatalogFields(BaseModel):
    schema_version: int = Field(default=1, ge=1)
    data_type: CatalogType
    list_id: int = Field(ge=1)
    title: str
    detail_url: str
    data_format: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_seen_run: str | None = None
    is_active: bool = True
    removed_at: datetime | None = None
    detail_collected_at: datetime | None = None
    detail_status: Literal["pending", "partial", "completed", "failed"] = (
        "pending"
    )
    detail_format: DetailFormat | None = None
    detail_errors: list[dict[str, Any]] = Field(default_factory=list)
    parsed_detail_ref: str | None = None
    representative_source_id: str | None = None
    api_spec_count: int = 0
    attachment_count: int = 0
    parse_status: Literal["completed", "partial", "failed"] | None = None
    parse_errors: list[dict[str, Any]] = Field(default_factory=list)
    parsed_at: datetime | None = None
    parser_version: str | None = None
    source_fingerprint: str | None = None

    @model_validator(mode="before")
    @classmethod
    def read_previous_catalog_shape(cls, value: Any) -> Any:
        if not isinstance(value, Mapping) or value.get("data_format"):
            return value
        result = dict(value)
        metadata = value.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            return result
        names = (
            ("파일 확장자", "확장자", "데이터 포맷", "데이터포맷")
            if value.get("data_type") == "FILE"
            else ("데이터 포맷", "데이터포맷", "데이터 형식")
        )
        for name in names:
            found = metadata.get(name)
            if isinstance(found, list):
                found = ", ".join(str(entry) for entry in found if entry)
            if isinstance(found, str) and found.strip():
                result["data_format"] = found.strip()
                break
        return result


class PortalCatalog(Document, PortalCatalogFields):
    id: str = Field(alias="_id")

    class Settings:
        name = "portal_catalog"
