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
# limitations under the License.from typing import Generic, TypeVar, List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict, AliasGenerator
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class BaseModelWithConfig(BaseModel):
    model_config = ConfigDict(
        alias_generator=AliasGenerator(
            validation_alias=to_camel,
            serialization_alias=to_camel,
        ),
        validate_by_name=True,
        from_attributes=True,
        extra="ignore",
    )


class PaginationParams(BaseModelWithConfig):
    page: int = Field(1, ge=1, description="페이지 번호")
    size: int = Field(50, ge=1, le=100, description="페이지 크기")


class PaginatedResponse(BaseModelWithConfig, Generic[T]):
    items: List[T]
    total: int
    page: int
    size: int
    total_pages: int
    has_next: bool
    has_prev: bool


class SearchResult(BaseModelWithConfig):
    list_id: int
    list_title: str
    title: str
    score: Optional[float] = None
    highlight: Optional[Dict[str, List[str]]] = None


class TitleResult(BaseModelWithConfig):
    list_id: int
    list_title: str
    title: str
    category_nm: str
    dept_nm: Optional[str] = None


class SearchWithDocsItem(BaseModelWithConfig):
    list_id: int
    list_title: str
    org_nm: Optional[str] = None
    token_count: int
    has_generated_doc: bool
    updated_at: Optional[str] = None
    data_type: str = "API"
    score: Optional[float] = None


class SearchWithDocsDetailItem(BaseModelWithConfig):
    list_id: int
    list_title: str
    title: Optional[str] = None
    org_nm: Optional[str] = None
    data_type: str
    score: Optional[float] = None
    detail: Optional[Dict[str, Any]] = None


class DocumentWithParsedInfo(BaseModelWithConfig):
    list_id: int
    data_type: str
    list_title: Optional[str] = None
    detail_url: str
    generated_status: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    description: Optional[str] = None
    org_nm: Optional[str] = None
    dept_nm: Optional[str] = None
    is_charged: Optional[str] = None
    share_scope_nm: Optional[str] = None
    keywords: List[str] = []
    token_count: int = 0
    generated_at: Optional[str] = None
    markdown: Optional[str] = None


class SuccessRateResponse(BaseModelWithConfig):
    total_open_data: int
    total_std_docs: int
    success_rate: float


class SearchResponse(BaseModelWithConfig):
    total: int
    page: int
    page_size: int
    results: List[Dict[str, Any]]


class SearchWithDocsDetailResponse(BaseModelWithConfig):
    total: int
    page: int
    page_size: int
    results: List[SearchWithDocsDetailItem]


class IndexStatsResponse(BaseModelWithConfig):
    index_name: str
    total_docs: int
    total_size: int
    indexing_stats: Dict[str, Any]
    search_stats: Dict[str, Any]


class GeneratedDocumentResponse(BaseModelWithConfig):
    listId: int
    detailUrl: str
    markdown: str
    llmModel: str
    tokenCount: int
    dataType: str
    resultJson: Optional[Dict[str, Any]] = None
    detail: Optional[Dict[str, Any]] = None


class UnifiedDataItem(BaseModelWithConfig):
    list_id: int
    title: str
    description: str
    department: str
    category: str
    data_type: Literal["API", "FILE"]
    data_format: str
    pricing: str
    copyright: str
    third_party_copyright: str
    keywords: List[str]
    register_status: str
    request_cnt: int
    download_cnt: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    use_prmisn_ennc: str
    title_en: Optional[str] = None
    api_type: Optional[str] = None
    endpoints: Optional[List[Dict[str, Any]]] = None
    has_generated_doc: bool = False
    token_count: int = 0
    score: Optional[float] = None


class SaveRequestBody(BaseModel):
    list_id: Optional[int] = Field(None, description="저장할 list_id")
    url: Optional[str] = Field(None, description="저장할 url")


def create_paginated_response(
    items: List[Dict[str, Any]], total: int, page: int, size: int
) -> Dict[str, Any]:
    total_pages = (total + size - 1) // size
    has_next = page < total_pages
    has_prev = page > 1

    response_data = {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "total_pages": total_pages,
        "has_next": has_next,
        "has_prev": has_prev,
    }

    return PaginatedResponse(**response_data).model_dump(by_alias=True)


def validate_pagination_params(page: int, size: int) -> tuple[int, int]:
    if page < 1:
        page = 1
    if size < 1:
        size = 1
    elif size > 100:
        size = 100

    return page, size


def calculate_offset(page: int, size: int) -> int:
    return (page - 1) * size


def convert_generated_document_to_camel_case(
    doc: Dict[str, Any], data_type: str
) -> Dict[str, Any]:
    return {
        "listId": doc.get("list_id"),
        "detailUrl": doc.get("detail_url"),
        "markdown": doc.get("markdown"),
        "llmModel": doc.get("llm_model"),
        "tokenCount": doc.get("token_count"),
        "dataType": data_type,
        "resultJson": doc.get("result_json"),
        "detail": doc.get("detail"),
    }
