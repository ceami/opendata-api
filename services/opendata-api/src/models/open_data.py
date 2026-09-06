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
from datetime import datetime
from typing import Any, Literal

import pymongo
from beanie import Document
from pydantic import BaseModel, Field, model_validator

from .catalog import CollectedMetadata, file_data_format


class ParsedEndpoint(BaseModel):
    id: str
    path: str
    method: str
    request_schema: dict | None = Field(default=None)
    response_schemas: dict | None = Field(default=None)
    example_response_data: Any | None = Field(default=None)
    example_request_string: str | None = Field(default=None)
    name: str | None = None
    description: str | None = None
    operation_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    servers: list[dict[str, Any]] = Field(default_factory=list)
    security: list[dict[str, Any]] = Field(default_factory=list)
    deprecated: bool | None = None
    absolute_url: str | None = None
    consumes: list[str] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)
    raw_tables: list[dict[str, Any]] = Field(default_factory=list)


class OpenFileInfo(Document, CollectedMetadata):
    """OpenFileInfo 모델"""

    id: str = Field(default_factory=lambda: "")
    core_data_nm: str | None
    cost_unit: str | None
    created_at: datetime | None = None
    data_limit: str | None
    data_type: Literal["FILE"] = "FILE"
    data_format: str | None = None
    dept_nm: str | None
    desc: str | None
    download_cnt: int | None
    etc: str | None
    ext: str | None
    is_charged: str | None
    is_copyrighted: str | None
    is_core_data: str | None
    is_deleted: str | None
    is_list_deleted: str | None
    is_std_data: str | None
    is_third_party_copyrighted: str | None
    keywords: list[str] | None
    list_id: int | None
    list_title: str | None
    media_cnt: str | None
    media_type: str | None
    meta_url: str | None
    new_category_cd: str | None
    new_category_nm: str | None
    next_registration_date: str | None
    org_cd: str | None
    org_nm: str | None
    ownership_grounds: str | None
    regist_type: str | None
    register_status: str | None
    share_scope_nm: str | None
    title: str | None
    update_cycle: str | None
    updated_at: datetime | None = None
    is_parsed: Literal["Y", "N", "ERROR"] = "N"
    parsed_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_file_format(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return {
            **value,
            "data_type": "FILE",
            "data_format": file_data_format(value),
        }

    class Settings:
        name = "open_file_info"
        indexes = [
            "title",
            "list_id",
            "org_nm",
            [("list_id", pymongo.ASCENDING)],
            [("download_cnt", pymongo.DESCENDING)],
            [("updated_at", pymongo.DESCENDING)],
            [("list_title", pymongo.ASCENDING)],
            [("org_nm", pymongo.ASCENDING)],
            [
                ("list_id", pymongo.ASCENDING),
                ("download_cnt", pymongo.DESCENDING),
            ],
            [
                ("list_id", pymongo.ASCENDING),
                ("updated_at", pymongo.DESCENDING),
            ],
        ]


class OpenAPIInfo(Document, CollectedMetadata):
    """OpenAPIInfo 모델"""

    id: str = Field(default_factory=lambda: "")
    data_type: Literal["API"] = "API"
    api_type: str
    category_nm: str
    core_data_nm: str | None
    created_at: datetime | None = None
    data_format: str
    dept_nm: str | None
    desc: str
    end_point_url: str
    guide_url: str | None
    is_charged: str
    is_confirmed_for_dev: Literal["Y", "N"] | None
    is_confirmed_for_dev_nm: str
    is_confirmed_for_prod: Literal["Y", "N"] | None
    is_confirmed_for_prod_nm: str
    is_copyrighted: Literal["Y", "N"] | None
    is_core_data: Literal["Y", "N"] | None
    is_deleted: Literal["Y", "N"] | None
    is_list_deleted: Literal["Y", "N"] | None
    is_std_data: Literal["Y", "N"] | None
    is_third_party_copyrighted: str | None
    keywords: list[str]
    link_url: str
    list_id: int
    list_title: str
    list_type: str
    meta_url: str
    new_category_cd: str
    new_category_nm: str
    operation_nm: str | None = None
    operation_seq: int | None = None
    operation_url: str | None = None
    org_cd: str
    org_nm: str
    ownership_grounds: str | None = None
    register_status: str | None = None
    request_cnt: int
    request_param_nm: list[str] | None = None
    request_param_nm_en: list[str] | None = None
    response_param_nm: list[str] | None = None
    response_param_nm_en: list[str] | None = None
    share_scope_cd: str | None = None
    share_scope_nm: str | None = None
    share_scope_reason: str
    soap_url: str
    title: str
    title_en: str
    updated_at: datetime | None = None
    upper_category_cd: str
    use_prmisn_ennc: str
    sequences: list[int] | None = None
    detail_html: str | None = None
    detail_html_updated_at: datetime | None = None
    detail_format: Literal["LINK", "SWAGGER", "TABLE", "ERROR"] | None = None
    is_parsed: Literal["Y", "N", "ERROR"] = "N"
    parsed_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_api_kind(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return {**value, "data_type": "API"}

    class Settings:
        name = "open_data_info"
        indexes = [
            "title",
            "list_id",
            "detail_format",
            "is_parsed",
            [("list_id", pymongo.ASCENDING)],
            [("request_cnt", pymongo.DESCENDING)],
            [("updated_at", pymongo.DESCENDING)],
            [("list_title", pymongo.ASCENDING)],
            [("org_nm", pymongo.ASCENDING)],
            [
                ("list_id", pymongo.ASCENDING),
                ("request_cnt", pymongo.DESCENDING),
            ],
            [
                ("list_id", pymongo.ASCENDING),
                ("updated_at", pymongo.DESCENDING),
            ],
            [
                ("request_cnt", pymongo.DESCENDING),
                ("updated_at", pymongo.DESCENDING),
            ],
        ]


class ParsedMetadata(BaseModel):
    """Source context plus revision metadata shared by deterministic parser outputs."""

    source_catalog_id: str | None = None
    source_fingerprint: str | None = None
    parser_version: str | None = None
    parse_status: Literal["completed", "partial", "failed"] | None = None
    parse_errors: list[dict[str, Any]] = Field(default_factory=list)
    monthly_snapshot: dict[str, Any] = Field(default_factory=dict)
    snapshot_run_id: str | None = None
    snapshot_source: Any | None = None
    snapshot_raw_sha256: str | None = None
    source_url: str = ""
    published_at: datetime | None = None
    organization: str = ""
    license: Any | None = None
    ownership_grounds: str = ""
    collection_method: str = ""
    update_cycle: str = ""
    next_registration_date: datetime | str | None = None
    media_type: str = ""
    row_count: int | None = None
    data_limit: str = ""
    notes: str = ""
    spatial_coverage: Any | None = None
    temporal_coverage: Any | None = None
    pricing_basis: str = ""
    contact: dict[str, Any] = Field(default_factory=dict)
    is_core_data: Any | None = None
    view_count: int = 0
    provision_type: str = ""
    is_standard_data: Any | None = None
    traffic_limit: str = ""
    review_status: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_org: dict[str, Any] = Field(default_factory=dict)
    schema_org_raw: list[dict[str, Any]] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    base_urls: list[str] = Field(default_factory=list)
    service_urls: list[str] = Field(default_factory=list)
    security_schemes: dict[str, Any] = Field(default_factory=dict)
    specifications: list[dict[str, Any]] = Field(default_factory=list)


class ParsedAPIInfo(Document, ParsedMetadata):
    """OpenDataInfo를 파서를 거쳐서 만들게 되는 최종 생성물"""

    id: str = Field(default_factory=lambda: "")
    api_confirm_for_dev: str
    api_confirm_for_prod: str
    api_type: str
    category: str
    copyright: str
    created_at: datetime | None = None
    data_format: str
    data_type: str
    department: str
    description: str
    endpoints: list[ParsedEndpoint] | None = None
    keywords: list[str]
    list_id: int
    parsed_at: datetime
    pricing: str
    register_status: str
    request_cnt: int
    third_party_copyright: str
    title: str
    title_en: str
    update_at: datetime | None = None
    use_prmisn_ennc: str

    class Settings:
        name = "parsed_api_info"
        indexes = [
            [
                ("title", pymongo.TEXT),
            ],
        ]


class ParsedFileInfo(Document, ParsedMetadata):
    """OpenFileInfo를 파서를 거쳐서 만들게 되는 최종 생성물"""

    id: str = Field(default_factory=lambda: "")
    api_confirm_for_dev: str | None = None
    api_confirm_for_prod: str | None = None
    api_type: str
    category: str
    created_at: datetime | None = None
    data_format: str
    data_type: str
    department: str
    description: str
    endpoints: list[ParsedEndpoint] | None = None
    keywords: list[str]
    list_id: int
    parsed_at: datetime
    pricing: str
    register_status: str | None = None
    request_cnt: int
    third_party_copyright: str
    title: str
    title_en: str | None = None
    update_at: datetime | None = None
    use_prmisn_ennc: str
    copyright: str = ""
    distributions: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[dict[str, Any]] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    class Settings:
        name = "parsed_file_info"
        indexes = [
            [
                ("title", pymongo.TEXT),
            ],
        ]


class ParsedSTDInfo(Document, ParsedMetadata):
    """Parsed standard dataset summary; member rows live separately."""

    id: str = Field(default_factory=lambda: "")
    list_id: int
    data_type: Literal["STD"] = "STD"
    title: str = ""
    description: str = ""
    department: str = ""
    category: str = ""
    data_format: str = ""
    created_at: datetime | str | None = None
    update_at: datetime | str | None = None
    pricing: str = ""
    copyright: str = ""
    third_party_copyright: str = ""
    keywords: list[str] = Field(default_factory=list)
    request_cnt: int = 0
    title_en: str = ""
    register_status: str = ""
    use_prmisn_ennc: str = ""
    member_count: int = 0
    collected_member_count: int = 0
    parsed_member_count: int = 0
    columns: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    parsed_at: datetime

    class Settings:
        name = "parsed_std_info"
        indexes = ["list_id", "source_catalog_id"]


class ParsedLinkedInfo(Document, ParsedMetadata):
    """Parsed linked-data metadata from schema.org and DCAT resources."""

    id: str = Field(default_factory=lambda: "")
    list_id: int
    data_type: Literal["LINKED"] = "LINKED"
    title: str = ""
    description: str = ""
    department: str = ""
    category: str = ""
    data_format: str = ""
    created_at: datetime | str | None = None
    update_at: datetime | str | None = None
    pricing: str = ""
    copyright: str = ""
    third_party_copyright: str = ""
    keywords: list[str] = Field(default_factory=list)
    request_cnt: int = 0
    title_en: str = ""
    register_status: str = ""
    use_prmisn_ennc: str = ""
    publishers: list[str] = Field(default_factory=list)
    licenses: list[str] = Field(default_factory=list)
    access_urls: list[str] = Field(default_factory=list)
    schema_org: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    parsed_at: datetime

    class Settings:
        name = "parsed_linked_info"
        indexes = ["list_id", "source_catalog_id"]


class ParsedSTDMember(Document):
    """One provider-specific member of a standard dataset."""

    id: str = Field(alias="_id")
    source_catalog_id: str
    list_id: int
    public_data_detail_pk: str
    title: str = ""
    provider: str | None = None
    registered_at: str | None = None
    source_record: dict[str, Any] = Field(default_factory=dict)
    detail_status: Literal["completed", "missing"] = "missing"
    metadata: dict[str, Any] = Field(default_factory=dict)
    columns: list[dict[str, Any]] = Field(default_factory=list)
    distributions: list[dict[str, Any]] = Field(default_factory=list)
    source_fingerprint: str
    parser_version: str
    parsed_at: datetime
    is_active: bool = True
    removed_at: datetime | None = None

    class Settings:
        name = "parsed_std_members"
        indexes = ["source_catalog_id", "list_id"]


class APIStdDocument(Document):
    """API 표준 문서 모델"""

    id: str = Field(default_factory=lambda: "")
    list_id: int
    detail_url: str
    markdown: str
    llm_model: str
    token_count: int

    class Settings:
        name = "generated_std_docs"
        indexes = [
            "list_id",
        ]


class GeneratedAPIDocs(Document):
    """생성된 API 문서 모델"""

    list_id: int
    detail_url: str
    markdown: str
    llm_model: str
    token_count: int
    result_json: dict[str, Any] | None = None
    detail: dict[str, Any] | None = None
    generated_at: datetime | None = None

    class Settings:
        name = "generated_api_docs"
        indexes = [
            "list_id",
            [("list_id", pymongo.ASCENDING)],
            [("token_count", pymongo.DESCENDING)],
            [("generated_at", pymongo.DESCENDING)],
            [
                ("list_id", pymongo.ASCENDING),
                ("token_count", pymongo.DESCENDING),
            ],
        ]


class GeneratedFileDocs(Document):
    """생성된 파일 문서 모델"""

    list_id: int
    detail_url: str
    markdown: str
    llm_model: str
    token_count: int
    status: bool | None = None
    result_json: dict[str, Any] | None = None
    detail: dict[str, Any] | None = None
    generated_at: datetime | None = None

    class Settings:
        name = "generated_file_docs"
        indexes = [
            "list_id",
            [("list_id", pymongo.ASCENDING)],
            [("token_count", pymongo.DESCENDING)],
            [("generated_at", pymongo.DESCENDING)],
            [
                ("list_id", pymongo.ASCENDING),
                ("token_count", pymongo.DESCENDING),
            ],
        ]


class SavedRequest(Document):
    """저장된 요청 모델"""

    list_id: int | None = None
    url: str | None = None
    created_at: datetime | None = None

    class Settings:
        name = "saved_requests"
        indexes = [
            "list_id",
            "created_at",
        ]


class RankBase(Document):
    """정렬 스냅샷 공통 모델"""

    list_id: int
    data_type: str
    list_title: str | None = None
    org_nm: str | None = None
    token_count: int | None = None
    has_generated_doc: bool | None = None
    updated_at: datetime | None = None
    generated_at: datetime | None = None
    popularity_score: float | None = None
    trending_score: float | None = None
    rank: int


class RankLatest(RankBase):
    class Settings:
        name = "rank_latest"
        indexes = [
            [
                ("rank", pymongo.ASCENDING),
            ],
            [
                ("list_id", pymongo.ASCENDING),
            ],
        ]


class RankPopular(RankBase):
    class Settings:
        name = "rank_popular"
        indexes = [
            [
                ("rank", pymongo.ASCENDING),
            ],
            [
                ("list_id", pymongo.ASCENDING),
            ],
        ]


class RankTrending(RankBase):
    class Settings:
        name = "rank_trending"
        indexes = [
            [
                ("rank", pymongo.ASCENDING),
            ],
            [
                ("list_id", pymongo.ASCENDING),
            ],
        ]


class RankMetadata(Document):
    """랭크 스냅샷 메타데이터"""

    sort_type: str
    total_count: int
    last_updated: datetime

    class Settings:
        name = "rank_metadata"
        indexes = [
            [
                ("sort_type", pymongo.ASCENDING),
            ],
        ]


class RecommendationItem(BaseModel):
    """추천 아이템 모델"""

    doc_id: str
    doc_type: str
    similarity_score: float
    rank: int


class DocRecommendation(Document):
    """문서 추천 모델"""

    target_doc_id: str
    target_doc_type: str
    recommendations: list[RecommendationItem]
    created_at: datetime
    updated_at: datetime
    version: int = 1

    class Settings:
        name = "doc_recommendations"
        indexes = [
            [
                ("target_doc_id", pymongo.ASCENDING),
            ],
            [
                ("created_at", pymongo.ASCENDING),
            ],
            [
                ("target_doc_type", pymongo.ASCENDING),
            ],
        ]
