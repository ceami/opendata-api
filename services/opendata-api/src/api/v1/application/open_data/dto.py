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
from typing import Any

from pydantic import AliasGenerator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class UnifiedDataItemDTO(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        alias_generator=AliasGenerator(
            validation_alias=to_camel,
            serialization_alias=to_camel,
        ),
        populate_by_name=True,
    )

    list_id: int
    title: str = ""
    list_title: str | None = None
    description: str | None = None
    department: str | None = None
    category: str | None = None
    data_type: str = "API"
    data_format: str | None = None
    pricing: Any | None = None
    copyright: Any | None = None
    third_party_copyright: Any | None = None
    keywords: list[str] = Field(default_factory=list)
    register_status: str | None = None
    request_cnt: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    use_prmisn_ennc: str | None = None
    title_en: str | None = None
    api_type: str | None = None
    endpoints: Any | None = None
    has_generated_doc: bool = False
    token_count: int = 0
    score: float | None = None
    org_nm: str | None = None


class PaginatedUnifiedDataDTO(BaseModel):
    model_config = ConfigDict(
        alias_generator=AliasGenerator(
            validation_alias=to_camel,
            serialization_alias=to_camel,
        ),
        populate_by_name=True,
    )

    items: list[UnifiedDataItemDTO]
    total: int
    page: int
    size: int
    total_pages: int
    has_next: bool
    has_prev: bool


class DocumentDetailDTO(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        alias_generator=AliasGenerator(
            validation_alias=to_camel,
            serialization_alias=to_camel,
        ),
        populate_by_name=True,
    )

    list_id: int
    data_type: str
    list_title: str | None = None
    detail_url: str
    generated_status: bool
    created_at: str | None = None
    updated_at: str | None = None
    description: str | None = None
    org_nm: str | None = None
    dept_nm: str | None = None
    is_charged: str | None = None
    share_scope_nm: str | None = None
    keywords: list[str] = []
    token_count: int = 0
    generated_at: str | None = None
    markdown: str | None = None


class GeneratedDocumentDTO(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        alias_generator=AliasGenerator(
            validation_alias=to_camel,
            serialization_alias=to_camel,
        ),
        populate_by_name=True,
    )

    list_id: int
    data_type: str
    list_title: str | None = None
    org_nm: str | None = None
    token_count: int = 0
    has_generated_doc: bool
    updated_at: str | None = None


class SuccessRateDTO(BaseModel):
    model_config = ConfigDict(
        alias_generator=AliasGenerator(
            validation_alias=to_camel,
            serialization_alias=to_camel,
        ),
        populate_by_name=True,
    )

    total_open_data: int
    total_std_docs: int
    success_rate: float


class GeneratedDocItemDTO(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        alias_generator=AliasGenerator(
            validation_alias=to_camel,
            serialization_alias=to_camel,
        ),
        populate_by_name=True,
    )

    list_id: int
    data_type: str
    detail_url: str
    markdown: str
    llm_model: str
    token_count: int
    result_json: dict[str, Any] | None = None
    detail: dict[str, Any] | None = None
    generated_at: datetime | None = None
    status: bool | None = None


class SaveRequestDTO(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        alias_generator=AliasGenerator(
            validation_alias=to_camel,
            serialization_alias=to_camel,
        ),
        populate_by_name=True,
    )

    list_id: int | None = None
    url: str | None = None


class CreateCommentDTO(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        alias_generator=AliasGenerator(
            validation_alias=to_camel,
            serialization_alias=to_camel,
        ),
        populate_by_name=True,
    )

    list_id: int
    content: str
