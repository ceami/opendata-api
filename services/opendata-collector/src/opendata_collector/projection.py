"""Projection from canonical portal records to the API's legacy collections.

The collector keeps the complete portal response separately.  This module only
creates the compact documents consumed by the existing API, and deliberately
does not manufacture unknown source flags or parser state.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")
_AI_STATE_FIELDS = {"_id", "id", "is_parsed", "parsed_at", "ai_state"}
_SPLIT_RE = re.compile(r"[,;/|\n]+")
_DATE_ONLY_RE = re.compile(r"^(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})\.?$")

_PORTAL_ALIASES = {
    "title": ("데이터명", "OpenAPI 명", "오픈API 명"),
    "list_title": ("데이터명", "OpenAPI 명"),
    "desc": ("설명", "데이터 설명"),
    "description": ("설명", "데이터 설명"),
    "org_nm": ("제공기관", "제공 기관"),
    "org_cd": ("제공기관 코드",),
    "dept_nm": ("관리부서명", "관리부서", "담당부서"),
    "contact": ("관리부서 전화번호", "담당자 전화번호", "연락처"),
    "keywords": ("키워드",),
    "keyword": ("키워드",),
    "category_nm": ("분류체계", "카테고리"),
    "new_category_nm": ("분류체계", "카테고리"),
    "created_at": ("등록일", "등록일자"),
    "updated_at": ("수정일", "수정일자"),
    "api_type": ("API 유형", "API유형"),
    "data_format": ("데이터 포맷", "데이터포맷", "데이터 형식"),
    "request_cnt": ("활용신청 수", "활용신청수"),
    "use_prmisn_ennc": ("이용허락범위", "이용 허락 범위"),
    "share_scope_nm": ("이용허락범위", "이용 허락 범위"),
    "link_url": ("URL", "상세페이지 URL"),
    "meta_url": ("URL", "상세페이지 URL"),
    "end_point_url": ("서비스URL", "서비스 URL", "API URL"),
    "guide_url": ("가이드 URL", "참고문서"),
    "update_cycle": ("갱신주기", "수정주기"),
    "ext": ("파일 확장자", "확장자"),
    "download_cnt": ("다운로드 수", "다운로드수"),
}
_SCHEMA_FIELDS = {
    "title": ("name",),
    "list_title": ("name",),
    "desc": ("description",),
    "description": ("description",),
    "org_nm": ("creator", "publisher", "provider"),
    "contact": ("contactPoint",),
    "created_at": ("datePublished", "dateCreated"),
    "updated_at": ("dateModified",),
    "data_format": ("encodingFormat",),
    "keywords": ("keywords",),
    "keyword": ("keywords",),
    "use_prmisn_ennc": ("license",),
    "share_scope_nm": ("license",),
    "link_url": ("url", "contentUrl"),
    "meta_url": ("url",),
    "end_point_url": ("contentUrl", "url"),
}


def project_legacy(
    item: dict,
    detail: dict,
    collected_at: datetime,
    source_record: dict | None = None,
) -> tuple[str, dict] | None:
    """Return the legacy collection and document for one catalog item.

    ``source_record`` is the official catalog-list row and wins over portal
    detail metadata when it has a value.  Unknown values remain ``None`` for
    nullable fields, especially source Y/N flags.
    """
    data_type = _text(item.get("data_type")).upper()
    if data_type in {"STD", "LINKED"}:
        return None
    if data_type == "FILE":
        return "open_file_info", _file_document(item, detail, collected_at, source_record or {})
    if data_type == "API":
        return "open_data_info", _api_document(item, detail, collected_at, source_record or {})
    return None


def _api_document(item: dict, detail: dict, collected_at: datetime, source: dict) -> dict:
    operations = _operations(detail.get("api_specs"))
    endpoint = _text(_pick(source, detail, "end_point_url", "endpoint", "api_url"))
    if not endpoint:
        endpoint = _endpoint_from_specs(detail.get("api_specs"))
    document = {
        "api_type": _text(_pick(source, detail, "api_type")),
        "category_nm": _text(_pick(source, detail, "category_nm", "category", "new_category_nm")),
        "core_data_nm": _optional_text(_pick(source, detail, "core_data_nm")),
        "created_at": _date(
            _pick(source, detail, "created_at", "registration_date", "regist_date")
        ),
        "data_format": _text(_pick(source, detail, "data_format", "data_type")),
        "dept_nm": _optional_text(_pick(source, detail, "dept_nm", "department", "contact_dept")),
        "contact": _optional_text(
            _pick(source, detail, "contact", "contact_info", "contact_tel", "contact_email")
        ),
        "desc": _description(item, detail, source),
        "end_point_url": endpoint,
        "guide_url": _optional_text(_pick(source, detail, "guide_url", "manual_url")),
        "is_charged": _text(_pick(source, detail, "is_charged", "charged")),
        "is_confirmed_for_dev": _flag(_pick(source, detail, "is_confirmed_for_dev")),
        "is_confirmed_for_dev_nm": _text(_pick(source, detail, "is_confirmed_for_dev_nm")),
        "is_confirmed_for_prod": _flag(_pick(source, detail, "is_confirmed_for_prod")),
        "is_confirmed_for_prod_nm": _text(_pick(source, detail, "is_confirmed_for_prod_nm")),
        "is_copyrighted": _flag(_pick(source, detail, "is_copyrighted")),
        "is_core_data": _flag(_pick(source, detail, "is_core_data")),
        "is_deleted": _flag(_pick(source, detail, "is_deleted")),
        "is_list_deleted": _flag(_pick(source, detail, "is_list_deleted")),
        "is_std_data": _flag(_pick(source, detail, "is_std_data")),
        "is_third_party_copyrighted": _optional_text(
            _pick(source, detail, "is_third_party_copyrighted")
        ),
        "keywords": _split(_pick(source, detail, "keywords", "keyword")),
        "link_url": _text(
            _pick(source, detail, "link_url", "detail_url") or item.get("detail_url")
        ),
        "list_id": _int(_pick(source, detail, "list_id") or item.get("list_id")) or 0,
        "list_title": _text(_pick(source, detail, "list_title") or item.get("title")),
        "list_type": _text(_pick(source, detail, "list_type") or item.get("data_type")),
        "meta_url": _text(_pick(source, detail, "meta_url") or item.get("detail_url")),
        "new_category_cd": _text(_pick(source, detail, "new_category_cd")),
        "new_category_nm": _text(
            _pick(source, detail, "new_category_nm", "category_nm", "category")
        ),
        "operation_nm": _optional_text(_pick(source, detail, "operation_nm")),
        "operation_seq": _int(_pick(source, detail, "operation_seq")),
        "operation_url": _optional_text(_pick(source, detail, "operation_url")),
        "org_cd": _text(_pick(source, detail, "org_cd", "organization_code")),
        "org_nm": _text(
            _pick(source, detail, "org_nm", "organization", "provider") or _summary(item, "org_nm")
        ),
        "ownership_grounds": _optional_text(_pick(source, detail, "ownership_grounds")),
        "register_status": _optional_text(_pick(source, detail, "register_status")),
        "request_cnt": _int(_pick(source, detail, "request_cnt", "request_count")) or 0,
        "request_param_nm": _split(_pick(source, detail, "request_param_nm")),
        "request_param_nm_en": _split(_pick(source, detail, "request_param_nm_en")),
        "response_param_nm": _split(_pick(source, detail, "response_param_nm")),
        "response_param_nm_en": _split(_pick(source, detail, "response_param_nm_en")),
        "share_scope_cd": _optional_text(_pick(source, detail, "share_scope_cd")),
        "share_scope_nm": _optional_text(_pick(source, detail, "share_scope_nm")),
        "share_scope_reason": _text(_pick(source, detail, "share_scope_reason")),
        "soap_url": _text(_pick(source, detail, "soap_url")),
        "title": _title(item, detail, source),
        "title_en": _text(_pick(source, detail, "title_en")),
        "updated_at": _date(_pick(source, detail, "updated_at", "update_date", "modified_at")),
        "upper_category_cd": _text(_pick(source, detail, "upper_category_cd")),
        "use_prmisn_ennc": _text(_pick(source, detail, "use_prmisn_ennc", "use_conditions")),
        "sequences": _int_list(_pick(source, detail, "sequences", "sequence")),
    }
    return _legacy_extras(document, item, detail, collected_at, operations)


def _file_document(item: dict, detail: dict, collected_at: datetime, source: dict) -> dict:
    document = {
        "core_data_nm": _optional_text(_pick(source, detail, "core_data_nm")),
        "cost_unit": _optional_text(_pick(source, detail, "cost_unit")),
        "created_at": _date(
            _pick(source, detail, "created_at", "registration_date", "regist_date")
        ),
        "data_limit": _optional_text(_pick(source, detail, "data_limit")),
        "data_type": "FILE",
        "data_format": _file_format(source, detail),
        "dept_nm": _optional_text(_pick(source, detail, "dept_nm", "department", "contact_dept")),
        "contact": _optional_text(
            _pick(source, detail, "contact", "contact_info", "contact_tel", "contact_email")
        ),
        "desc": _optional_text(_description(item, detail, source)),
        "download_cnt": _int(_pick(source, detail, "download_cnt", "download_count")),
        "etc": _optional_text(_pick(source, detail, "etc")),
        "ext": _optional_text(_pick(source, detail, "ext", "file_extension")),
        "is_charged": _optional_text(_pick(source, detail, "is_charged", "charged")),
        "is_copyrighted": _optional_text(_pick(source, detail, "is_copyrighted")),
        "is_core_data": _optional_text(_pick(source, detail, "is_core_data")),
        "is_deleted": _optional_text(_pick(source, detail, "is_deleted")),
        "is_list_deleted": _optional_text(_pick(source, detail, "is_list_deleted")),
        "is_std_data": _optional_text(_pick(source, detail, "is_std_data")),
        "is_third_party_copyrighted": _optional_text(
            _pick(source, detail, "is_third_party_copyrighted")
        ),
        "keywords": _split(_pick(source, detail, "keywords", "keyword")) or None,
        "list_id": _int(_pick(source, detail, "list_id") or item.get("list_id")),
        "list_title": _optional_text(_pick(source, detail, "list_title") or item.get("title")),
        "media_cnt": _optional_text(_pick(source, detail, "media_cnt")),
        "media_type": _optional_text(_pick(source, detail, "media_type")),
        "meta_url": _optional_text(_pick(source, detail, "meta_url") or item.get("detail_url")),
        "new_category_cd": _optional_text(_pick(source, detail, "new_category_cd")),
        "new_category_nm": _optional_text(
            _pick(source, detail, "new_category_nm", "category_nm", "category")
        ),
        "next_registration_date": _optional_text(_pick(source, detail, "next_registration_date")),
        "org_cd": _optional_text(_pick(source, detail, "org_cd", "organization_code")),
        "org_nm": _optional_text(
            _pick(source, detail, "org_nm", "organization", "provider") or _summary(item, "org_nm")
        ),
        "ownership_grounds": _optional_text(_pick(source, detail, "ownership_grounds")),
        "regist_type": _optional_text(_pick(source, detail, "regist_type")),
        "register_status": _optional_text(_pick(source, detail, "register_status")),
        "share_scope_nm": _optional_text(_pick(source, detail, "share_scope_nm")),
        "title": _optional_text(_title(item, detail, source)),
        "update_cycle": _optional_text(_pick(source, detail, "update_cycle")),
        "updated_at": _date(_pick(source, detail, "updated_at", "update_date", "modified_at")),
    }
    return _legacy_extras(
        document, item, detail, collected_at, _operations(detail.get("api_specs"))
    )


def _file_format(source: dict, detail: dict) -> str | None:
    kinds = {"API", "FILE", "STD", "LINKED"}
    # A source's legacy data_type may describe CSV; the catalog kind never does.
    for value in (
        source.get("data_format"),
        source.get("data_type"),
        _pick(source, detail, "ext", "file_extension"),
        _pick(source, detail, "data_format"),
    ):
        text = _optional_text(value)
        if text and text.upper() not in kinds:
            return text
    return None


def _legacy_extras(
    document: dict, item: dict, detail: dict, collected_at: datetime, operations: list
) -> dict:
    result = dict(document)
    result.update(
        {
            "source_catalog_id": _optional_text(item.get("catalog_id")),
            "detail_url": _optional_text(item.get("detail_url")),
            "summary": item.get("summary") if isinstance(item.get("summary"), dict) else {},
            "attachments": detail.get("attachments")
            if isinstance(detail.get("attachments"), list)
            else [],
            "operations": operations,
            "detail_format": _detail_format(item, detail),
            "collected_at": collected_at,
        }
    )
    if "data_type" not in result:
        result["data_type"] = _optional_text(item.get("data_type"))
    return {key: value for key, value in result.items() if key not in _AI_STATE_FIELDS}


def _pick(source: dict, detail: dict, *keys: str) -> Any:
    candidates = _candidate_keys(keys)
    value = _from_mapping(source, candidates)
    if value is not None:
        return value
    metadata = detail.get("metadata") if isinstance(detail.get("metadata"), dict) else {}
    value = _from_mapping(metadata, candidates)
    if value is not None:
        return value
    value = _schema_value(detail.get("schema_org"), keys)
    if value is not None:
        return value
    return _from_mapping(detail, candidates)


def _candidate_keys(keys: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(key for name in keys for key in (name, *_PORTAL_ALIASES.get(name, ())))
    )


def _schema_value(schema_documents: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(schema_documents, list):
        return None
    for document in schema_documents:
        if not isinstance(document, dict):
            continue
        for key in keys:
            for field in _SCHEMA_FIELDS.get(key, ()):
                raw_value = _from_mapping(document, (field,))
                value = raw_value if field == "keywords" else _schema_scalar(raw_value, field)
                if value is not None:
                    return value
    return None


def _schema_scalar(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        fields = (
            ("telephone", "email", "name", "url")
            if field == "contactPoint"
            else ("name", "url", "@id", "contentUrl")
        )
        return next(
            (_schema_scalar(value.get(name), name) for name in fields if value.get(name)), None
        )
    if isinstance(value, (list, tuple)):
        return next(
            (_schema_scalar(entry, field) for entry in value if entry not in (None, "")), None
        )
    return value if value not in (None, "") else None


def _from_mapping(mapping: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, "", []):
            return mapping[key]
    normalized = {_normalize(key): value for key, value in mapping.items()}
    for key in keys:
        value = normalized.get(_normalize(key))
        if value not in (None, "", []):
            return value
    return None


def _normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9가-힣]", "", str(value).lower())


def _summary(item: dict, key: str) -> Any:
    summary = item.get("summary")
    return summary.get(key) if isinstance(summary, dict) else None


def _title(item: dict, detail: dict, source: dict) -> str:
    return _text(_pick(source, detail, "title", "list_title") or item.get("title"))


def _description(item: dict, detail: dict, source: dict) -> str:
    return _text(
        _pick(source, detail, "desc", "description", "summary")
        or _summary(item, "description")
        or _summary(item, "desc")
    )


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        value = next((entry for entry in value if entry not in (None, "")), None)
    return str(value).strip() if value is not None else ""


def _split(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    for entry in values:
        result.extend(part.strip() for part in _SPLIT_RE.split(str(entry)) if part.strip())
    return list(dict.fromkeys(result))


def _int(value: Any) -> int | None:
    if isinstance(value, (list, tuple)):
        value = next((entry for entry in value if entry not in (None, "")), None)
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _int_list(value: Any) -> list[int] | None:
    values = _split(value)
    parsed = [_int(entry) for entry in values]
    return [entry for entry in parsed if entry is not None] or None


def _flag(value: Any) -> str | None:
    text = _optional_text(value)
    return text if text in {"Y", "N"} else None


def _date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _optional_text(value)
        if text is None:
            return None
        match = _DATE_ONLY_RE.fullmatch(text)
        if match:
            try:
                parsed = datetime(*(int(part) for part in match.groups()))
            except ValueError:
                return None
        else:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_KST)
    return parsed.astimezone(timezone.utc)


def _endpoint_from_specs(specs: Any) -> str:
    if not isinstance(specs, list):
        return ""
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        servers = spec.get("servers")
        if isinstance(servers, list):
            for server in servers:
                if isinstance(server, dict) and _text(server.get("url")):
                    return _text(server["url"])
        host = _text(spec.get("host"))
        if host:
            scheme = _text((spec.get("schemes") or ["https"])[0]) or "https"
            base_path = _text(spec.get("basePath")).rstrip("/")
            return f"{scheme}://{host}{base_path}"
    return ""


def _operations(specs: Any) -> list[dict]:
    if not isinstance(specs, list):
        return []
    result: list[dict] = []
    methods = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    for spec in specs:
        paths = spec.get("paths") if isinstance(spec, dict) else None
        if not isinstance(paths, dict):
            continue
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method.lower() not in methods or not isinstance(operation, dict):
                    continue
                entry = {"path": str(path), "method": method.upper()}
                if _text(operation.get("operationId")):
                    entry["operation_id"] = _text(operation["operationId"])
                if _text(operation.get("summary")):
                    entry["summary"] = _text(operation["summary"])
                result.append(entry)
    return result


def _detail_format(item: dict, detail: dict) -> str:
    if isinstance(detail.get("api_specs"), list) and detail["api_specs"]:
        return "SWAGGER"
    if isinstance(detail.get("tables"), list) and detail["tables"]:
        return "TABLE"
    if _text(detail.get("detail_format")) == "ERROR":
        return "ERROR"
    return "LINK" if _text(item.get("detail_url")) else "ERROR"
