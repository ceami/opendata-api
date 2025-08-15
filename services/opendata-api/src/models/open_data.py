from beanie import Document
from datetime import datetime
from typing import Literal
import pymongo

from schemas import ParsedEndpoint


class OpenDataInfo(Document):
    """
    OpenDataInfo 모델
    공공데이터 포털에서 제공하는 API 응답 정보를 담는 모델
    응답 정보 외에 추가 필드는 파싱 전 HTML 코드 저장 및 분류를 위한 필드
    """

    id: str
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
    is_confirmed_for_dev: Literal["Y", "N"]
    is_confirmed_for_dev_nm: str
    is_confirmed_for_prod: Literal["Y", "N"]
    is_confirmed_for_prod_nm: str
    is_copyrighted: Literal["Y", "N"]
    is_core_data: Literal["Y", "N"]
    is_deleted: Literal["Y", "N"]
    is_list_deleted: Literal["Y", "N"]
    is_std_data: Literal["Y", "N"]
    is_third_party_copyrighted: str
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

    class Settings:
        name = "open_data_info"
        indexes = [
            "title",
            "list_id",
            "detail_format",
            "is_parsed",
        ]


class ParsedAPIInfo(Document):
    """
    OpenDataInfo를 파서를 거쳐서 만들게 되는 최종 생성물
    주석처리된 각 필드는 OpenDataInfo의 필드를 그대로 가져옴
    """

    id: str
    list_id: int
    title: str
    description: str
    department: str
    category: str
    data_format: str
    update_at: datetime
    pricing: str
    copyright: str
    third_party_copyright: str
    endpoints: list[ParsedEndpoint] | None = None
    api_type: str
    created_at: datetime
    api_confirm_for_dev: str
    api_confirm_for_prod: str
    keywords: list[str]
    register_status: str
    request_cnt: int
    title_en: str
    use_prmisn_ennc: str
    parsed_at: datetime

    class Settings:
        name = "parsed_api_info"
        indexes = [
            [
                ("title", pymongo.TEXT),
            ],
        ]


class APIStdDocument(Document):
    """API 표준 문서 모델"""

    id: str
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
