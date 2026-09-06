"""Deterministically normalize collected portal records before AI processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

from .parsers import parse_dcat_metadata

PARSER_VERSION = "3"
HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}


@dataclass(slots=True)
class ParseInput:
    catalog: dict[str, Any]
    detail: dict[str, Any]
    source_records: list[dict[str, Any]] = field(default_factory=list)
    resources: list[dict[str, Any]] = field(default_factory=list)
    source_fingerprint: str = ""
    input_errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ParsedOutput:
    collection: str
    document: dict[str, Any]
    members: list[dict[str, Any]] = field(default_factory=list)


def _nonempty(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _first(*values: Any, default: Any = "") -> Any:
    return next((value for value in values if _nonempty(value)), default)


def _integer(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _optional_integer(value: Any) -> int | None:
    if not _nonempty(value) or isinstance(value, bool):
        return None
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if not _nonempty(value):
        return None
    raw = str(value).strip()
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
    if parsed is None:
        for date_format in ("%Y.%m.%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, date_format)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def _first_date(*values: Any) -> datetime | None:
    for value in values:
        parsed = _date(value)
        if parsed is not None:
            return parsed
    return None


def _schema_annotations(schema: dict[str, Any]) -> dict[str, Any]:
    annotations = {}
    for key in (
        "title",
        "default",
        "example",
        "examples",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "nullable",
        "readOnly",
        "writeOnly",
        "deprecated",
        "discriminator",
    ):
        if key not in schema:
            continue
        value = schema[key]
        if _nonempty(value) or value in (False, 0):
            annotations[key] = value
    return annotations


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    result = []
    for item in values:
        result.extend(str(item).replace("|", ",").split(","))
    return [item.strip() for item in result if item.strip()]


def _unique(values: list[Any]) -> list[Any]:
    result = []
    for value in values:
        if _nonempty(value) and value not in result:
            result.append(value)
    return result


def _metadata_value(metadata: dict[str, Any], *labels: str) -> Any:
    for label in labels:
        value = metadata.get(label)
        if isinstance(value, list):
            value = next((item for item in value if _nonempty(item)), "")
        if _nonempty(value):
            return value
    return ""


def _official_record(source_records: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for stored in source_records:
        if stored.get("source") == "monthly_snapshot":
            continue
        record = _source_record(stored)
        if not isinstance(record, dict):
            continue
        for key, value in record.items():
            if key not in merged and _nonempty(value):
                merged[key] = value
    return merged


MONTHLY_SOURCE_FIELDS = {
    "id": ("목록키",),
    "title": ("목록명",),
    "list_title": ("목록명",),
    "meta_url": ("목록 URL",),
    "org_nm": ("제공기관", "제공 기관", "제공기관명"),
    "dept_nm": ("관리부서명", "관리부서", "담당부서"),
    "contact_name": ("담당자명", "담당자"),
    "contact_tel": (
        "관리부서 전화번호",
        "관리부서전화번호",
        "담당자 전화번호",
        "담당자전화번호",
        "담당자 연락처",
        "연락처",
    ),
    "contact_email": ("담당자 이메일", "이메일"),
    "category_nm": ("분류체계", "카테고리", "카테고리명"),
    "data_format": ("확장자", "데이터포맷", "데이터 형식", "파일형식"),
    "created_at": ("등록일", "생성일"),
    "updated_at": ("수정일", "최종수정일", "갱신일"),
    "published_at": ("공개일", "게시일"),
    "share_scope_nm": ("이용허락범위", "이용 허락 범위", "라이선스"),
    "download_cnt": ("다운로드수",),
    "request_cnt": ("활용신청수", "활용 신청수"),
    "view_count": ("조회수", "열람수"),
    "provision_type": ("제공유형", "서비스유형"),
    "is_standard_data": ("표준데이터 여부", "표준데이터여부"),
    "spatial_coverage": ("공간범위",),
    "temporal_coverage": ("시간범위",),
    "end_point_url": ("서비스URL", "서비스 URL", "API URL"),
    "api_type": ("API 유형", "API유형"),
    "is_confirmed_for_dev": ("개발계정 자동승인", "개발계정자동승인", "개발계정 승인 여부"),
    "is_confirmed_for_prod": ("운영계정 자동승인", "운영계정자동승인", "운영계정 승인 여부"),
    "traffic_limit": ("일일 트래픽", "일일트래픽", "트래픽"),
    "review_status": ("심의 여부", "심의여부", "검토 여부", "검토여부"),
}


def _monthly_record(stored: dict[str, Any]) -> dict[str, Any]:
    record = stored.get("record", stored)
    if not isinstance(record, dict):
        return {}
    result = dict(record)
    for output_field, labels in MONTHLY_SOURCE_FIELDS.items():
        if _nonempty(result.get(output_field)):
            continue
        result[output_field] = _first(*(record.get(label) for label in labels), default="")
    return result


def _source_record(stored: dict[str, Any]) -> dict[str, Any]:
    if stored.get("source") == "monthly_snapshot":
        return _monthly_record(stored)
    record = stored.get("record", stored)
    return record if isinstance(record, dict) else {}


def _monthly_snapshot(source_records: list[dict[str, Any]]) -> dict[str, Any]:
    for stored in reversed(source_records):
        if stored.get("source") == "monthly_snapshot":
            return stored
    return {}


def _schema_documents(detail: dict[str, Any]) -> list[dict[str, Any]]:
    documents = detail.get("schema_org", [])
    if isinstance(documents, dict):
        documents = [documents]
    if not isinstance(documents, list):
        return []
    return [dict(value) for value in documents if isinstance(value, dict)]


def _schema_dataset(detail: dict[str, Any]) -> dict[str, Any]:
    for value in _schema_documents(detail):
        if not isinstance(value, dict):
            continue
        graph = value.get("@graph")
        candidates = graph if isinstance(graph, list) else [value]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            kind = candidate.get("@type", "")
            kinds = kind if isinstance(kind, list) else [kind]
            if any(str(item).lower().endswith("dataset") for item in kinds):
                return candidate
    return {}


def _resolve_ref(spec: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        return None
    current: Any = spec
    for component in ref[2:].split("/"):
        component = component.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or component not in current:
            return None
        current = current[component]
    return current


def _resolve_schema(
    spec: dict[str, Any], schema: Any, seen: frozenset[str] = frozenset()
) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    ref = schema.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            return {"$ref": ref, "recursive": True}
        target = _resolve_ref(spec, ref)
        if not isinstance(target, dict):
            return {"$ref": ref}
        return _resolve_schema(spec, target, seen | {ref})

    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        result: dict[str, Any] = {
            "type": schema_type or "object",
            "required": list(schema.get("required", [])),
            "properties": {
                name: _resolve_schema(spec, value, seen)
                for name, value in schema.get("properties", {}).items()
                if isinstance(name, str)
            },
            "description": schema.get("description", ""),
        }
        if "additionalProperties" in schema:
            additional = schema["additionalProperties"]
            result["additionalProperties"] = (
                _resolve_schema(spec, additional, seen)
                if isinstance(additional, dict)
                else additional
            )
        result.update(_schema_annotations(schema))
        return result
    if schema_type == "array" or "items" in schema:
        result = {
            "type": schema_type or "array",
            "items": _resolve_schema(spec, schema.get("items", {}), seen),
            "description": schema.get("description", ""),
        }
        result.update(_schema_annotations(schema))
        return result
    for composition in ("allOf", "oneOf", "anyOf"):
        if composition in schema:
            result = {
                composition: [
                    _resolve_schema(spec, value, seen) for value in schema.get(composition, [])
                ],
                "description": schema.get("description", ""),
            }
            result.update(_schema_annotations(schema))
            return result
    result = {
        "type": schema_type or "object",
        "description": schema.get("description", ""),
        "format": schema.get("format"),
        "enum": schema.get("enum"),
    }
    result.update(_schema_annotations(schema))
    return result


def _parameter(spec: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    schema = value.get("schema", {})
    if not isinstance(schema, dict):
        schema = {}
    parameter_type = _first(value.get("type"), schema.get("type"), default="object")
    result = {
        "name": str(value.get("name", "")),
        "description": value.get("description", ""),
        "type": parameter_type,
        "required": bool(value.get("required", value.get("in") == "path")),
        "in_": value.get("in", ""),
    }
    for key in (
        "format",
        "default",
        "example",
        "examples",
        "enum",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "nullable",
        "style",
        "explode",
        "allowEmptyValue",
        "deprecated",
    ):
        field_value = value[key] if key in value else schema.get(key)
        if _nonempty(field_value) or field_value in (False, 0):
            result[key] = field_value
    if value.get("in") == "body" and schema:
        result["schema"] = _resolve_schema(spec, schema)
    return result


def _security_schemes(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    schemes = spec.get("securityDefinitions", {})
    if not schemes and isinstance(spec.get("components"), dict):
        schemes = spec["components"].get("securitySchemes", {})
    if not isinstance(schemes, dict):
        return {}
    return {name: dict(value) for name, value in schemes.items() if isinstance(value, dict)}


def _security_requirements(spec: dict[str, Any], operation: dict[str, Any]) -> list[dict[str, Any]]:
    raw = operation["security"] if "security" in operation else spec.get("security", [])
    if not isinstance(raw, list):
        return []
    return [dict(requirement) for requirement in raw if isinstance(requirement, dict)]


def _security_parameters(
    spec: dict[str, Any], requirements: list[dict[str, Any]]
) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {
        "header": {},
        "query": {},
        "cookie": {},
    }
    referenced = {name for requirement in requirements for name in requirement}
    for scheme_name, value in _security_schemes(spec).items():
        if (
            scheme_name not in referenced
            or value.get("type") != "apiKey"
            or value.get("in") not in result
        ):
            continue
        name = value.get("name")
        if not name:
            continue
        result[value["in"]][str(name)] = {
            "name": str(name),
            "description": value.get("description", ""),
            "type": "string",
            "required": all(scheme_name in requirement for requirement in requirements),
            "in_": value["in"],
            "security_scheme": scheme_name,
        }
    return result


def _spec_servers(spec: dict[str, Any]) -> list[dict[str, Any]]:
    servers = spec.get("servers", [])
    if isinstance(servers, list):
        valid = [
            dict(server) for server in servers if isinstance(server, dict) and server.get("url")
        ]
        if valid:
            return valid
    host = spec.get("host")
    if not host:
        return []
    base_path = str(spec.get("basePath", "")).strip("/")
    schemes = _strings(spec.get("schemes")) or ["https"]
    return [
        {"url": f"{scheme}://{host}" + (f"/{base_path}" if base_path else "")} for scheme in schemes
    ]


def _absolute_url(path: Any, servers: list[dict[str, Any]]) -> str:
    path_value = str(path or "")
    if urlsplit(path_value).scheme or len(servers) != 1:
        return path_value if urlsplit(path_value).scheme else ""
    base_url = str(servers[0].get("url", "")).strip()
    if not base_url:
        return ""
    return f"{base_url.rstrip('/')}/{path_value.lstrip('/')}"


def _request_body(spec: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return {}
    ref = body.get("$ref")
    if isinstance(ref, str):
        resolved = _resolve_ref(spec, ref)
        body = resolved if isinstance(resolved, dict) else body
    content = {}
    for media_type, media in body.get("content", {}).items():
        if not isinstance(media, dict):
            continue
        normalized = dict(media)
        if isinstance(media.get("schema"), dict):
            normalized["schema"] = _resolve_schema(spec, media["schema"])
        content[media_type] = normalized
    return {"required": bool(body.get("required")), "content": content}


def _response(spec: dict[str, Any], code: Any, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    ref = value.get("$ref")
    if isinstance(ref, str):
        resolved = _resolve_ref(spec, ref)
        value = resolved if isinstance(resolved, dict) else value
    schema = value.get("schema")
    examples = value.get("examples", {})
    content = value.get("content", {})
    content_types: list[str] = []
    if isinstance(content, dict) and content:
        content_types = list(content)
        first_media = next((media for media in content.values() if isinstance(media, dict)), {})
        schema = first_media.get("schema", schema)
        examples = {
            media_type: media.get("example", media.get("examples"))
            for media_type, media in content.items()
            if isinstance(media, dict) and _nonempty(media.get("example", media.get("examples")))
        }
    result = {
        "code": str(code),
        "description": value.get("description", ""),
        "data_schema": _resolve_schema(spec, schema),
        "examples": examples if isinstance(examples, dict) else {},
    }
    if content_types:
        result["content_types"] = content_types
    if isinstance(value.get("headers"), dict) and value["headers"]:
        result["headers"] = value["headers"]
    if isinstance(value.get("links"), dict) and value["links"]:
        result["links"] = value["links"]
    return result


def parse_openapi_endpoints(spec: dict[str, Any], list_id: int) -> list[dict[str, Any]]:
    """Convert OpenAPI 2/3 operations without dropping document-generation context."""
    if not isinstance(spec, dict):
        return []
    endpoints = []
    default_servers = _spec_servers(spec)
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        path_parameters = path_item.get("parameters", [])
        if not isinstance(path_parameters, list):
            path_parameters = []
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            security = _security_requirements(spec, operation)
            security_parameters = _security_parameters(spec, security)
            request_schema = {
                "headers": dict(security_parameters["header"]),
                "query_params": dict(security_parameters["query"]),
                "path_params": {},
                "cookie_params": dict(security_parameters["cookie"]),
                "request_body": {},
            }
            operation_parameters = operation.get("parameters", [])
            if not isinstance(operation_parameters, list):
                operation_parameters = []
            parameters = [*path_parameters, *operation_parameters]
            for raw_parameter in parameters:
                if not isinstance(raw_parameter, dict):
                    continue
                if isinstance(raw_parameter.get("$ref"), str):
                    resolved = _resolve_ref(spec, raw_parameter["$ref"])
                    if isinstance(resolved, dict):
                        raw_parameter = resolved
                location = raw_parameter.get("in")
                parameter = _parameter(spec, raw_parameter)
                name = parameter["name"]
                if location == "header" and name:
                    request_schema["headers"][name] = parameter
                elif location == "query" and name:
                    request_schema["query_params"][name] = parameter
                elif location == "path" and name:
                    request_schema["path_params"][name] = parameter
                elif location == "cookie" and name:
                    request_schema["cookie_params"][name] = parameter
                elif location == "body" and name:
                    request_schema["request_body"][name] = parameter
            if isinstance(operation.get("requestBody"), dict):
                request_schema["request_body"] = _request_body(spec, operation)

            responses = {
                str(code): _response(spec, code, value)
                for code, value in operation.get("responses", {}).items()
            }
            example = None
            for response in responses.values():
                if response["examples"]:
                    example = next(iter(response["examples"].values()))
                    break
            servers = operation.get("servers", path_item.get("servers", default_servers))
            if not isinstance(servers, list):
                servers = default_servers
            servers = [dict(server) for server in servers if isinstance(server, dict)]
            endpoint = {
                "id": f"{list_id}_{path}_{method.upper()}",
                "path": path,
                "method": method.upper(),
                "request_schema": request_schema,
                "response_schemas": responses,
                "example_response_data": example,
                "example_request_string": None,
            }
            optional_fields = {
                "name": _first(operation.get("summary"), operation.get("operationId")),
                "description": operation.get("description"),
                "operation_id": operation.get("operationId"),
                "tags": operation.get("tags"),
                "servers": servers,
                "security": security,
                "consumes": operation.get("consumes", spec.get("consumes")),
                "produces": operation.get("produces", spec.get("produces")),
                "absolute_url": _absolute_url(path, servers),
            }
            if "deprecated" in operation:
                optional_fields["deprecated"] = bool(operation["deprecated"])
            endpoint.update(
                {key: value for key, value in optional_fields.items() if _nonempty(value)}
            )
            if "security" in operation or "security" in spec:
                endpoint["security"] = security
            endpoints.append(endpoint)
    return endpoints


def _schema_creator(schema: dict[str, Any]) -> str:
    creators = schema.get("creator")
    if not isinstance(creators, list):
        creators = [creators]
    for creator in creators:
        if isinstance(creator, dict):
            value = _first(creator.get("name"), creator.get("legalName"))
        else:
            value = creator
        if _nonempty(value):
            return str(value)
    return ""


def _contact_parts(value: Any) -> dict[str, Any]:
    values = value if isinstance(value, list) else [value]
    result: dict[str, Any] = {}
    for item in values:
        if isinstance(item, dict):
            aliases = {
                "name": ("name", "contactName"),
                "phone": ("telephone", "phone", "contact_tel"),
                "email": ("email", "contact_email"),
                "type": ("contactType", "type"),
            }
            for output_key, source_keys in aliases.items():
                candidate = _first(*(item.get(key) for key in source_keys), default="")
                if _nonempty(candidate) and not _nonempty(result.get(output_key)):
                    result[output_key] = candidate
        elif _nonempty(item):
            key = "email" if "@" in str(item) else "phone"
            result.setdefault(key, str(item))
    return {key: value for key, value in result.items() if _nonempty(value)}


def _contact(
    metadata: dict[str, Any],
    source: dict[str, Any],
    schema: dict[str, Any],
    department: str,
    monthly: dict[str, Any],
) -> dict[str, Any]:
    source_contact = _contact_parts([source.get("contact"), source.get("contact_info")])
    schema_contact = _contact_parts(schema.get("contactPoint"))
    contact = {
        "department": department,
        "name": _first(
            source.get("contact_name"),
            source_contact.get("name"),
            schema_contact.get("name"),
            _metadata_value(metadata, "담당자명", "담당자"),
            monthly.get("contact_name"),
        ),
        "phone": _first(
            source.get("contact_tel"),
            source_contact.get("phone"),
            schema_contact.get("phone"),
            _metadata_value(
                metadata,
                "관리부서 전화번호",
                "관리부서전화번호",
                "담당자 연락처",
                "연락처",
            ),
            monthly.get("contact_tel"),
        ),
        "email": _first(
            source.get("contact_email"),
            source_contact.get("email"),
            schema_contact.get("email"),
            _metadata_value(metadata, "담당자 이메일", "이메일"),
            monthly.get("contact_email"),
        ),
        "type": _first(source_contact.get("type"), schema_contact.get("type")),
    }
    return {key: value for key, value in contact.items() if _nonempty(value)}


def _common(parse_input: ParseInput) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    catalog, detail = parse_input.catalog, parse_input.detail
    source = _official_record(parse_input.source_records)
    snapshot = _monthly_snapshot(parse_input.source_records)
    monthly = _monthly_record(snapshot)
    metadata = detail.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    schema = _schema_dataset(detail)
    summary = catalog.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    title = _first(
        source.get("title"),
        source.get("list_title"),
        schema.get("name"),
        _metadata_value(metadata, "목록명", "데이터명"),
        monthly.get("title"),
        monthly.get("list_title"),
        catalog.get("title")
    )
    description = _first(
        source.get("desc"),
        source.get("description"),
        schema.get("description"),
        _metadata_value(metadata, "설명", "데이터 설명", "Description"),
        summary.get("description"),
    )
    organization = _first(
        source.get("org_nm"),
        _schema_creator(schema),
        _metadata_value(metadata, "제공기관", "소관기관", "기관명"),
        monthly.get("org_nm"),
        summary.get("org_nm"),
    )
    department = _first(
        source.get("dept_nm"),
        _metadata_value(metadata, "관리부서명", "담당부서", "부서명"),
        monthly.get("dept_nm"),
        organization,
    )
    category = _first(
        source.get("category_nm"),
        source.get("new_category_nm"),
        _metadata_value(metadata, "분류체계", "카테고리"),
        monthly.get("category_nm"),
    )
    data_format = _first(
        source.get("data_format"),
        source.get("ext"),
        _metadata_value(metadata, "확장자", "데이터포맷", "포맷"),
        detail.get("detail_format"),
        monthly.get("data_format"),
        monthly.get("ext"),
    )
    created_at = _first_date(
        source.get("created_at"),
        source.get("reg_date"),
        schema.get("dateCreated"),
        _metadata_value(metadata, "등록일", "생성일"),
        monthly.get("created_at"),
        monthly.get("reg_date"),
    )
    published_at = _first_date(
        source.get("published_at"),
        schema.get("datePublished"),
        _metadata_value(metadata, "공개일", "게시일"),
        monthly.get("published_at"),
    )
    update_at = _first_date(
        source.get("updated_at"),
        source.get("update_at"),
        schema.get("dateModified"),
        _metadata_value(metadata, "수정일", "최종수정일", "갱신일"),
        monthly.get("updated_at"),
        monthly.get("update_at"),
    )
    pricing = _first(source.get("is_charged"), _metadata_value(metadata, "비용부과유무"))
    license_value = _first(
        schema.get("license"),
        source.get("share_scope_nm"),
        source.get("share_scope_reason"),
        source.get("use_prmisn_ennc"),
        _metadata_value(metadata, "이용허락범위", "이용 허락 범위", "라이선스"),
        monthly.get("share_scope_nm"),
        monthly.get("share_scope_reason"),
        monthly.get("use_prmisn_ennc"),
    )
    status = (
        "completed"
        if catalog.get("detail_status") == "completed" and not parse_input.input_errors
        else "partial"
    )
    parsed_at = datetime.now(timezone.utc)
    document = {
        "id": str(_first(source.get("id"), catalog.get("_id"))),
        "list_id": _integer(catalog.get("list_id")),
        "data_type": catalog.get("data_type"),
        "title": title,
        "description": description,
        "organization": organization,
        "department": department,
        "category": category,
        "data_format": data_format,
        "created_at": created_at,
        "published_at": published_at,
        "update_at": update_at,
        "source_url": _first(catalog.get("detail_url"), source.get("meta_url")),
        "license": license_value,
        "ownership_grounds": _first(
            source.get("ownership_grounds"), _metadata_value(metadata, "보유근거")
        ),
        "collection_method": _first(
            source.get("collection_method"), _metadata_value(metadata, "수집방법")
        ),
        "update_cycle": _first(
            source.get("update_cycle"), _metadata_value(metadata, "업데이트 주기", "갱신주기")
        ),
        "next_registration_date": _first_date(
            source.get("next_registration_date"),
            _metadata_value(metadata, "차기 등록 예정일", "차기등록예정일"),
        ),
        "media_type": _first(source.get("media_type"), _metadata_value(metadata, "매체유형")),
        "row_count": _optional_integer(
            _first(
                source.get("row_count"),
                source.get("media_cnt"),
                _metadata_value(metadata, "전체 행", "전체행", "데이터수"),
                default=None,
            )
        ),
        "data_limit": _first(
            source.get("data_limit"), _metadata_value(metadata, "데이터 한계", "데이터한계")
        ),
        "notes": _first(source.get("etc"), _metadata_value(metadata, "기타 유의사항", "유의사항")),
        "spatial_coverage": _first(
            schema.get("spatialCoverage"),
            _metadata_value(metadata, "공간범위"),
            source.get("spatial_coverage"),
            monthly.get("spatial_coverage"),
        ),
        "temporal_coverage": _first(
            schema.get("temporalCoverage"),
            _metadata_value(metadata, "시간범위"),
            source.get("temporal_coverage"),
            monthly.get("temporal_coverage"),
        ),
        "pricing_basis": _first(
            source.get("cost_unit"),
            _metadata_value(metadata, "비용부과기준 및 단위", "비용 부과기준 및 단위"),
        ),
        "contact": _contact(metadata, source, schema, str(department), monthly),
        "is_core_data": _first(source.get("is_core_data"), source.get("core_data_nm")),
        "pricing": pricing,
        "copyright": _first(source.get("is_copyrighted"), _metadata_value(metadata, "저작권")),
        "third_party_copyright": _first(
            source.get("is_third_party_copyrighted"),
            _metadata_value(metadata, "제3자 권리 포함 여부"),
        ),
        "keywords": _unique(
            [
                *_strings(source.get("keywords")),
                *_strings(schema.get("keywords")),
                *_strings(_metadata_value(metadata, "키워드")),
            ]
        ),
        "request_cnt": _integer(
            _first(
                source.get("request_cnt"),
                source.get("download_cnt"),
                monthly.get("request_cnt"),
                monthly.get("download_cnt"),
                default=0,
            )
        ),
        "view_count": _integer(
            _first(source.get("view_count"), monthly.get("view_count"), default=0)
        ),
        "provision_type": _first(
            source.get("provision_type"), monthly.get("provision_type"), default=""
        ),
        "is_standard_data": _first(
            source.get("is_standard_data"),
            source.get("is_std_data"),
            monthly.get("is_standard_data"),
            monthly.get("is_std_data"),
            default=None
        ),
        "title_en": _first(source.get("title_en"), default=""),
        "register_status": _first(source.get("register_status"), default=""),
        "use_prmisn_ennc": _first(source.get("use_prmisn_ennc"), default=""),
        "monthly_snapshot": dict(snapshot.get("record", {})),
        "snapshot_run_id": snapshot.get("snapshot_run_id"),
        "snapshot_source": snapshot.get("snapshot_source"),
        "snapshot_raw_sha256": snapshot.get("snapshot_raw_sha256"),
        "metadata": dict(metadata),
        "schema_org": dict(schema),
        "schema_org_raw": _schema_documents(detail),
        "attachments": [
            dict(item) for item in detail.get("attachments", []) if isinstance(item, dict)
        ],
        "source_catalog_id": catalog.get("_id"),
        "source_fingerprint": parse_input.source_fingerprint,
        "parser_version": PARSER_VERSION,
        "parse_status": status,
        "parse_errors": [
            *catalog.get("detail_errors", []),
            *parse_input.input_errors,
        ],
        "parsed_at": parsed_at,
    }
    return document, metadata, schema


def _popup_map(detail: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for popup in detail.get("detail_popups", []):
        if not isinstance(popup, dict):
            continue
        descriptor = popup.get("descriptor") or popup.get("request", {})
        params = descriptor.get("params", {}) if isinstance(descriptor, dict) else {}
        key = _first(
            params.get("publicDataDetailPk"),
            params.get("public_data_detail_pk"),
            popup.get("public_data_detail_pk"),
        )
        sequence = _first(
            params.get("publicDataHistSn"),
            params.get("public_data_hist_sn"),
            popup.get("public_data_detail_sn"),
        )
        if key:
            result[(str(key), str(sequence))] = (
                popup.get("data", {}) if isinstance(popup.get("data"), dict) else {}
            )
    return result


def _table_rows(table: dict[str, Any]):
    headers = [str(value).strip() for value in table.get("headers", [])]
    for values in table.get("rows", []):
        if not isinstance(values, list):
            continue
        yield {
            header: values[index] if index < len(values) else ""
            for index, header in enumerate(headers)
        }


def _row_value(row: dict[str, Any], *tokens: str) -> Any:
    for header, value in row.items():
        normalized = header.replace(" ", "").lower()
        if any(token.replace(" ", "").lower() in normalized for token in tokens):
            if _nonempty(value):
                return value
    return ""


def _required(value: Any) -> bool:
    return str(value).strip().upper() in {
        "1",
        "Y",
        "YES",
        "TRUE",
        "필수",
        "필수항목",
    }


def _operation_endpoints(detail: dict[str, Any], list_id: int) -> list[dict[str, Any]]:
    endpoints = []
    for index, entry in enumerate(detail.get("operation_details", []), 1):
        if not isinstance(entry, dict):
            continue
        operation = entry.get("operation", {})
        data = entry.get("data", {})
        if not isinstance(operation, dict) or not isinstance(data, dict):
            continue
        metadata = data.get("metadata", {})
        path = _first(
            _metadata_value(metadata, "요청주소", "서비스URL", "서비스 URL", "End Point"),
            operation.get("url"),
            default=f"operation:{index}",
        )
        method = str(
            _first(_metadata_value(metadata, "요청방식", "HTTP Method"), default="GET")
        ).upper()
        if method not in {value.upper() for value in HTTP_METHODS}:
            method = "GET"
        query_params = {}
        properties = {}
        for table in data.get("tables", []):
            if not isinstance(table, dict):
                continue
            identity = " ".join(
                [str(table.get("caption", "")), *map(str, table.get("headers", []))]
            )
            is_request = "요청" in identity
            is_response = any(token in identity for token in ("출력", "응답", "결과"))
            for row in _table_rows(table):
                name = str(
                    _first(
                        _row_value(row, "영문", "변수명", "컬럼명", "항목명"),
                        default="",
                    )
                ).strip()
                if not name:
                    continue
                description = str(_row_value(row, "설명", "항목내용"))
                if is_request:
                    query_params[name] = {
                        "name": name,
                        "name_ko": str(_row_value(row, "국문", "한글")),
                        "description": description,
                        "type": "string",
                        "size": str(_row_value(row, "크기", "길이")),
                        "required": _required(_row_value(row, "구분", "필수")),
                        "in_": "query",
                        "example": _row_value(row, "샘플", "예시", "기본값"),
                    }
                elif is_response:
                    properties[name] = {
                        "type": "string",
                        "description": description,
                        "format": None,
                        "enum": None,
                    }
        params = operation.get("params", {})
        if not isinstance(params, dict):
            params = {}
        sequence = params.get("oprtinSeqNo", index)
        endpoints.append(
            {
                "id": f"{list_id}_{sequence}_{method}",
                "path": path,
                "method": method,
                "name": operation.get("name", ""),
                "request_schema": {
                    "headers": {},
                    "query_params": query_params,
                    "path_params": {},
                    "cookie_params": {},
                    "request_body": {},
                },
                "response_schemas": {
                    "200": {
                        "code": "200",
                        "description": "",
                        "data_schema": {
                            "type": "object",
                            "required": [],
                            "properties": properties,
                            "description": "",
                        },
                        "examples": {},
                    }
                },
                "example_response_data": None,
                "example_request_string": None,
                "raw_tables": list(data.get("tables", [])),
            }
        )
    return endpoints


def _source_endpoints(source_records: list[dict[str, Any]], list_id: int) -> list[dict[str, Any]]:
    endpoints = []
    for index, stored in enumerate(source_records, 1):
        record = _source_record(stored)
        if not isinstance(record, dict):
            continue
        path = _first(
            record.get("operation_url"),
            record.get("end_point_url"),
            record.get("link_url"),
        )
        if not path:
            continue
        names = _strings(_first(record.get("request_param_nm_en"), record.get("request_param_nm")))
        query_params = {
            name: {
                "name": name,
                "description": "",
                "type": "string",
                "required": False,
                "in_": "query",
            }
            for name in names
        }
        sequence = _first(record.get("operation_seq"), index)
        endpoints.append(
            {
                "id": f"{list_id}_{sequence}_GET",
                "path": path,
                "method": "GET",
                "name": record.get("operation_nm", ""),
                "request_schema": {
                    "headers": {},
                    "query_params": query_params,
                    "path_params": {},
                    "cookie_params": {},
                    "request_body": {},
                },
                "response_schemas": {},
                "example_response_data": None,
                "example_request_string": None,
            }
        )
    return endpoints


def _path_only(value: Any) -> str:
    path = urlsplit(str(value or "")).path.rstrip("/")
    return path or "/"


def _url_identity(value: Any) -> str:
    parsed = urlsplit(str(value or ""))
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/') or '/'}"


def _matching_endpoint(
    endpoint: dict[str, Any], candidates: list[dict[str, Any]]
) -> dict[str, Any] | None:
    endpoint_method = str(endpoint.get("method", "GET")).upper()
    same_method = [
        candidate
        for candidate in candidates
        if str(candidate.get("method", "GET")).upper() == endpoint_method
    ]
    absolute_identity = _url_identity(endpoint.get("absolute_url"))
    exact_urls = [
        candidate
        for candidate in same_method
        if absolute_identity and _url_identity(candidate.get("path")) == absolute_identity
    ]
    if len(exact_urls) == 1:
        return exact_urls[0]

    endpoint_path = _path_only(endpoint.get("path"))
    exact_paths = [
        candidate
        for candidate in same_method
        if (not absolute_identity or not _url_identity(candidate.get("path")))
        and _path_only(candidate.get("path")) == endpoint_path
    ]
    if len(exact_paths) == 1:
        return exact_paths[0]

    suffix_matches = []
    if endpoint_path != "/":
        suffix_matches = [
            candidate
            for candidate in same_method
            if (not absolute_identity or not _url_identity(candidate.get("path")))
            and (candidate_path := _path_only(candidate.get("path"))) != "/"
            and (candidate_path.endswith(endpoint_path) or endpoint_path.endswith(candidate_path))
        ]
    return suffix_matches[0] if len(suffix_matches) == 1 else None


def _merge_missing(target: Any, supplemental: Any) -> Any:
    if isinstance(target, dict) and isinstance(supplemental, dict):
        for key, value in supplemental.items():
            if key in target:
                target[key] = _merge_missing(target[key], value)
            elif _nonempty(value) or value in (False, 0):
                target[key] = value
        return target
    if not _nonempty(target) and (_nonempty(supplemental) or supplemental in (False, 0)):
        return supplemental
    return target


def _enrich_descriptive_fields(target: dict[str, Any], supplemental: dict[str, Any]) -> None:
    for key in ("description", "example", "examples", "default", "name_ko", "size"):
        if key in supplemental:
            target[key] = _merge_missing(target.get(key), supplemental[key])


def _enrich_request_schema(target: dict[str, Any], supplemental: dict[str, Any]) -> None:
    for location in ("headers", "query_params", "path_params", "cookie_params"):
        target_parameters = target.get(location, {})
        supplemental_parameters = supplemental.get(location, {})
        if not isinstance(target_parameters, dict) or not isinstance(supplemental_parameters, dict):
            continue
        for name, parameter in target_parameters.items():
            other = supplemental_parameters.get(name)
            if isinstance(parameter, dict) and isinstance(other, dict):
                _enrich_descriptive_fields(parameter, other)


def _schema_properties(schema: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return {}
    return {name: value for name, value in properties.items() if isinstance(value, dict)}


def _enrich_schema_properties(
    target: Any, supplemental_properties: dict[str, dict[str, Any]]
) -> None:
    if not isinstance(target, dict):
        return
    properties = target.get("properties", {})
    if isinstance(properties, dict):
        for name, value in properties.items():
            if not isinstance(value, dict):
                continue
            other = supplemental_properties.get(name)
            if isinstance(other, dict):
                _enrich_descriptive_fields(value, other)
            _enrich_schema_properties(value, supplemental_properties)
    _enrich_schema_properties(target.get("items"), supplemental_properties)
    for composition in ("allOf", "oneOf", "anyOf"):
        values = target.get(composition, [])
        if isinstance(values, list):
            for value in values:
                _enrich_schema_properties(value, supplemental_properties)


def _enrich_response_schemas(target: dict[str, Any], supplemental: dict[str, Any]) -> None:
    for code, response in target.items():
        other = supplemental.get(code)
        if not isinstance(response, dict) or not isinstance(other, dict):
            continue
        _enrich_descriptive_fields(response, other)
        supplemental_properties = _schema_properties(other.get("data_schema"))
        _enrich_schema_properties(response.get("data_schema"), supplemental_properties)


def _merge_endpoint(primary: dict[str, Any], supplemental: dict[str, Any]) -> None:
    supplemental_path = str(supplemental.get("path", ""))
    if urlsplit(supplemental_path).scheme:
        primary["absolute_url"] = supplemental_path
    for key in (
        "name",
        "description",
        "operation_id",
        "tags",
        "servers",
        "security",
        "deprecated",
        "consumes",
        "produces",
        "raw_tables",
    ):
        if key in supplemental:
            primary[key] = _merge_missing(primary.get(key), supplemental[key])
    request_schema = primary.get("request_schema", {})
    supplemental_request = supplemental.get("request_schema", {})
    if isinstance(request_schema, dict) and isinstance(supplemental_request, dict):
        _enrich_request_schema(request_schema, supplemental_request)
    response_schemas = primary.get("response_schemas", {})
    supplemental_responses = supplemental.get("response_schemas", {})
    if isinstance(response_schemas, dict) and isinstance(supplemental_responses, dict):
        _enrich_response_schemas(response_schemas, supplemental_responses)
    if primary.get("example_response_data") is None:
        primary["example_response_data"] = supplemental.get("example_response_data")
    if primary.get("example_request_string") is None:
        primary["example_request_string"] = supplemental.get("example_request_string")


def _specification_context(spec: dict[str, Any]) -> dict[str, Any]:
    info = spec.get("info", {})
    result = {
        "version": _first(spec.get("openapi"), spec.get("swagger")),
        "info": dict(info) if isinstance(info, dict) else {},
        "servers": _spec_servers(spec),
        "host": spec.get("host"),
        "base_path": spec.get("basePath"),
        "schemes": spec.get("schemes"),
        "security": spec.get("security"),
        "external_docs": spec.get("externalDocs"),
        "tags": spec.get("tags"),
        "consumes": spec.get("consumes"),
        "produces": spec.get("produces"),
    }
    return {key: value for key, value in result.items() if _nonempty(value)}


def _api_context(
    detail: dict[str, Any], source_records: list[dict[str, Any]], endpoints: list[dict[str, Any]]
) -> dict[str, Any]:
    specs = [spec for spec in detail.get("api_specs", []) if isinstance(spec, dict)]
    base_urls = _unique([server.get("url") for spec in specs for server in _spec_servers(spec)])
    security_schemes: dict[str, Any] = {}
    for spec in specs:
        for name, value in _security_schemes(spec).items():
            security_schemes.setdefault(name, value)
    service_urls: list[Any] = []
    for stored in source_records:
        record = _source_record(stored)
        if not isinstance(record, dict):
            continue
        service_urls.extend(
            [record.get("end_point_url"), record.get("operation_url"), record.get("soap_url")]
        )
    service_urls.extend(
        endpoint.get("absolute_url", endpoint.get("path"))
        for endpoint in endpoints
        if urlsplit(str(endpoint.get("absolute_url", endpoint.get("path", "")))).scheme
    )
    return {
        "base_urls": _unique(base_urls),
        "service_urls": _unique(service_urls),
        "security_schemes": security_schemes,
        "specifications": [_specification_context(spec) for spec in specs],
    }


def _normalize_api(parse_input: ParseInput, document: dict[str, Any]) -> ParsedOutput:
    detail = parse_input.detail
    endpoints = [
        endpoint
        for spec in detail.get("api_specs", [])
        if isinstance(spec, dict)
        for endpoint in parse_openapi_endpoints(spec, document["list_id"])
    ]
    operation_endpoints = _operation_endpoints(detail, document["list_id"])
    if endpoints:
        unmatched = list(operation_endpoints)
        for endpoint in endpoints:
            supplemental = _matching_endpoint(endpoint, unmatched)
            if supplemental is None:
                continue
            _merge_endpoint(endpoint, supplemental)
            unmatched.remove(supplemental)
        endpoints.extend(
            endpoint
            for endpoint in unmatched
            if not str(endpoint.get("path", "")).startswith("operation:")
        )
    else:
        endpoints = operation_endpoints
    if not endpoints:
        endpoints.extend(_source_endpoints(parse_input.source_records, document["list_id"]))
    source = _official_record(parse_input.source_records)
    monthly = _monthly_record(_monthly_snapshot(parse_input.source_records))
    document.update(
        {
            "api_type": _first(source.get("api_type"), monthly.get("api_type"), default=""),
            "api_confirm_for_dev": _first(
                source.get("is_confirmed_for_dev"), monthly.get("is_confirmed_for_dev"), default=""
            ),
            "api_confirm_for_prod": _first(
                source.get("is_confirmed_for_prod"),
                monthly.get("is_confirmed_for_prod"),
                default=""
            ),
            "traffic_limit": _first(
                source.get("traffic_limit"), monthly.get("traffic_limit"), default=""
            ),
            "review_status": _first(
                source.get("review_status"), monthly.get("review_status"), default=""
            ),
            "endpoints": endpoints,
            **_api_context(detail, parse_input.source_records, endpoints),
        }
    )
    return ParsedOutput("parsed_api_info", document)


def _normalize_file(
    parse_input: ParseInput, document: dict[str, Any], metadata: dict[str, Any]
) -> ParsedOutput:
    detail = parse_input.detail
    popups = _popup_map(detail)
    history = []
    for item in detail.get("file_history_data", {}).get("file_details", []):
        if not isinstance(item, dict):
            continue
        key = _first(item.get("public_data_detail_pk"), item.get("publicDataDetailPk"))
        sequence = _first(
            item.get("public_data_detail_sn"),
            item.get("public_data_hist_sn"),
            item.get("publicDataHistSn"),
        )
        popup = popups.get((str(key), str(sequence)), {})
        history.append({**item, **popup})
    endpoints = [
        endpoint
        for spec in detail.get("api_specs", [])
        if isinstance(spec, dict)
        for endpoint in parse_openapi_endpoints(spec, document["list_id"])
    ]
    document.update(
        {
            "api_type": "",
            "endpoints": endpoints,
            **_api_context(detail, parse_input.source_records, endpoints),
            "distributions": list(detail.get("attachments", [])),
            "columns": list(detail.get("tables", [])),
            "history": history,
            "metadata": metadata,
        }
    )
    return ParsedOutput("parsed_file_info", document)


def _normalize_standard(
    parse_input: ParseInput, document: dict[str, Any], metadata: dict[str, Any]
) -> ParsedOutput:
    detail = parse_input.detail
    standard = detail.get("standard_members", {})
    popups = _popup_map(detail)
    members = []
    parsed_members = 0
    for item in standard.get("items", []):
        if not isinstance(item, dict):
            continue
        key = str(_first(item.get("public_data_detail_pk"), item.get("publicDataDetailPk")))
        popup_key = (key, "")
        has_popup = popup_key in popups
        popup = popups.get(popup_key, {})
        if has_popup:
            parsed_members += 1
        listing_metadata = item.get("metadata", {})
        if not isinstance(listing_metadata, dict):
            listing_metadata = {}
        popup_metadata = popup.get("metadata", {})
        if not isinstance(popup_metadata, dict):
            popup_metadata = {}
        members.append(
            {
                "_id": f"{parse_input.catalog['_id']}:{key}",
                "source_catalog_id": parse_input.catalog["_id"],
                "list_id": document["list_id"],
                "public_data_detail_pk": key,
                "title": item.get("title", ""),
                "provider": item.get("provider"),
                "registered_at": item.get("registered_at"),
                "source_record": dict(item),
                "detail_status": "completed" if has_popup else "missing",
                "metadata": {**listing_metadata, **popup_metadata},
                "columns": popup.get("tables", []),
                "distributions": popup.get("attachments", []),
                "source_fingerprint": parse_input.source_fingerprint,
                "parser_version": PARSER_VERSION,
                "parsed_at": document["parsed_at"],
                "is_active": True,
            }
        )
    document.update(
        {
            "member_count": _integer(standard.get("total"), len(members)),
            "collected_member_count": _integer(standard.get("collected_count"), len(members)),
            "parsed_member_count": parsed_members,
            "columns": list(detail.get("tables", [])),
            "metadata": metadata,
        }
    )
    return ParsedOutput("parsed_std_info", document, members)


def _rdf_values(root: Any, names: set[str]) -> list[str]:
    values = []
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1]
        if local_name not in names:
            continue
        resource = next(
            (
                value
                for key, value in element.attrib.items()
                if key.rsplit("}", 1)[-1] in {"resource", "about"}
            ),
            "",
        )
        value = _first(resource, " ".join("".join(element.itertext()).split()))
        if value:
            values.append(str(value))
    return values


def _normalize_linked(
    parse_input: ParseInput,
    document: dict[str, Any],
    metadata: dict[str, Any],
    schema: dict[str, Any],
) -> ParsedOutput:
    publishers: list[str] = []
    licenses = _strings(schema.get("license"))
    access_urls = _strings(_metadata_value(metadata, "URL", "접근URL", "접근 URL"))
    access_urls.extend(_strings(schema.get("url")))
    distributions = schema.get("distribution", [])
    if isinstance(distributions, dict):
        distributions = [distributions]
    for distribution in distributions:
        if isinstance(distribution, dict):
            access_urls.extend(_strings(distribution.get("contentUrl")))
            access_urls.extend(_strings(distribution.get("url")))
    for resource in parse_input.resources:
        if resource.get("kind") != "dcat" or not isinstance(resource.get("content"), bytes):
            continue
        content = resource["content"]
        try:
            root, _ = parse_dcat_metadata(content, content.decode("utf-8", errors="replace"))
        except (ValueError, UnicodeError, ElementTree.ParseError):
            document["parse_status"] = "partial"
            document["parse_errors"].append(
                {
                    "kind": "dcat",
                    "url": resource.get("url"),
                    "error": "Cannot parse DCAT resource",
                }
            )
            continue
        publishers.extend(_rdf_values(root, {"publisher"}))
        licenses.extend(_rdf_values(root, {"license"}))
        access_urls.extend(_rdf_values(root, {"accessURL", "downloadURL"}))
    document.update(
        {
            "publishers": _unique(publishers),
            "licenses": _unique(licenses),
            "access_urls": _unique(access_urls),
            "schema_org": schema,
            "metadata": metadata,
        }
    )
    return ParsedOutput("parsed_linked_info", document)


def normalize_catalog(parse_input: ParseInput) -> ParsedOutput:
    """Normalize one canonical catalog record into its parsed collection shape."""
    document, metadata, schema = _common(parse_input)
    kind = parse_input.catalog.get("data_type")
    if kind == "API":
        return _normalize_api(parse_input, document)
    if kind == "FILE":
        return _normalize_file(parse_input, document, metadata)
    if kind == "STD":
        return _normalize_standard(parse_input, document, metadata)
    if kind == "LINKED":
        return _normalize_linked(parse_input, document, metadata, schema)
    raise ValueError(f"Unsupported catalog type: {kind}")
