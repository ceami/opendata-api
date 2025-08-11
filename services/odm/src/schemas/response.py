from typing import Generic, TypeVar, List, Dict, Any, Optional
from pydantic import BaseModel, Field

T = TypeVar('T')


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1, description="페이지 번호")
    size: int = Field(50, ge=1, le=100, description="페이지 크기")


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    size: int
    total_pages: int
    has_next: bool
    has_prev: bool


class SearchResult(BaseModel):
    list_id: int
    list_title: str
    title: str
    score: Optional[float] = None
    highlight: Optional[Dict[str, List[str]]] = None


class TitleResult(BaseModel):
    list_id: int
    list_title: str
    title: str
    category_nm: str
    dept_nm: Optional[str] = None


class CrossCollectionItem(BaseModel):
    list_id: int
    list_title: str
    org_nm: str
    token_count: int
    has_generated_doc: bool


class SearchWithDocsItem(BaseModel):
    list_id: int
    list_title: str
    title: str
    score: Optional[float] = None
    token_count: int
    has_generated_doc: bool


class DocumentWithParsedInfo(BaseModel):
    id: str
    list_id: int
    title: Optional[str] = None
    description: Optional[str] = None
    detail_url: str
    markdown: str
    llm_model: str
    token_count: int


def create_paginated_response(
    items: List[Dict[str, Any]],
    total: int,
    page: int,
    size: int
) -> Dict[str, Any]:
    total_pages = (total + size - 1) // size
    has_next = page < total_pages
    has_prev = page > 1

    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "total_pages": total_pages,
        "has_next": has_next,
        "has_prev": has_prev
    }


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
