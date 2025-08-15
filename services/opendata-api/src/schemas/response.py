from typing import Generic, TypeVar, List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict, AliasGenerator
from pydantic.alias_generators import to_camel

T = TypeVar('T')


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


class CrossCollectionItem(BaseModelWithConfig):
    list_id: int
    list_title: str
    org_nm: str
    token_count: int
    has_generated_doc: bool
    updated_at: Optional[str] = None
    data_type: str


class SearchWithDocsItem(BaseModelWithConfig):
    list_id: int
    list_title: str
    org_nm: Optional[str] = None
    token_count: int
    has_generated_doc: bool
    updated_at: Optional[str] = None
    data_type: str = "API"
    score: Optional[float] = None


class DocumentWithParsedInfo(BaseModelWithConfig):
    list_id: int
    list_title: Optional[str] = None
    detail_url: str
    generated_status: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    org_nm: Optional[str] = None
    dept_nm: Optional[str] = None
    phone_number: Optional[str] = None
    is_charged: Optional[str] = None
    traffic: Optional[str] = None
    permission: Optional[str] = None
    docs: Optional[str] = None
    keywords: List[str] = []
    description: Optional[str] = None
    token_count: int
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


class IndexStatsResponse(BaseModelWithConfig):
    index_name: str
    total_docs: int
    total_size: int
    indexing_stats: Dict[str, Any]
    search_stats: Dict[str, Any]


class APIStdDocumentResponse(BaseModelWithConfig):
    id: str
    listId: int
    detailUrl: str
    markdown: str
    llmModel: str
    tokenCount: int


def create_paginated_response(
    items: List[Dict[str, Any]],
    total: int,
    page: int,
    size: int
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
        "has_prev": has_prev
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


def convert_api_std_document_to_camel_case(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc.get("id"),
        "listId": doc.get("list_id"),
        "detailUrl": doc.get("detail_url"),
        "markdown": doc.get("markdown"),
        "llmModel": doc.get("llm_model"),
        "tokenCount": doc.get("token_count")
    }
