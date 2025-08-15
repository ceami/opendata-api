from typing import Generic, TypeVar, List, Optional
from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1, description="페이지 번호")
    size: int = Field(50, ge=1, le=100, description="페이지 크기")


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T] = Field(..., description="아이템 목록")
    total: int = Field(..., description="전체 아이템 수")
    page: int = Field(..., description="현재 페이지 번호")
    size: int = Field(..., description="페이지 크기")
    pages: int = Field(..., description="전체 페이지 수")
    has_next: bool = Field(..., description="다음 페이지 존재 여부")
    has_prev: bool = Field(..., description="이전 페이지 존재 여부")


class SearchResult(BaseModel):
    list_id: int = Field(..., description="리스트 ID")
    list_title: str = Field(..., description="리스트 제목")
    title: str = Field(..., description="제목")
    category_nm: str = Field(..., description="카테고리명")
    dept_nm: str = Field(..., description="부서명")
    score: Optional[float] = Field(None, description="검색 점수")
    highlight: Optional[dict] = Field(None, description="하이라이트 정보")


class TitleResult(BaseModel):
    list_id: int = Field(..., description="리스트 ID")
    list_title: str = Field(..., description="리스트 제목")
    title: str = Field(..., description="제목")
    category_nm: str = Field(..., description="카테고리명")
    dept_nm: str = Field(..., description="부서명")
