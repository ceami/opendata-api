"""Deterministically normalize collected portal records before AI processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree

from .parsers import parse_dcat_metadata

PARSER_VERSION = "1"
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
        record = stored.get("record", stored)
        if not isinstance(record, dict):
            continue
        for key, value in record.items():
            if key not in merged and _nonempty(value):
                merged[key] = value
    return merged


def _schema_dataset(detail: dict[str, Any]) -> dict[str, Any]:
    documents = detail.get("schema_org", [])
    if isinstance(documents, dict):
        documents = [documents]
    for value in documents:
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
        return result
    if schema_type == "array" or "items" in schema:
        return {
            "type": schema_type or "array",
            "items": _resolve_schema(spec, schema.get("items", {}), seen),
            "description": schema.get("description", ""),
        }
    for composition in ("allOf", "oneOf", "anyOf"):
        if composition in schema:
            return {
                composition: [
                    _resolve_schema(spec, value, seen) for value in schema.get(composition, [])
                ],
                "description": schema.get("description", ""),
            }
    return {
        "type": schema_type or "object",
        "description": schema.get("description", ""),
        "format": schema.get("format"),
        "enum": schema.get("enum"),
    }


def _parameter(spec: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    schema = value.get("schema", {})
    parameter_type = value.get("type")
    if not parameter_type and isinstance(schema, dict):
        parameter_type = schema.get("type")
    result = {
        "name": str(value.get("name", "")),
        "description": value.get("description", ""),
        "type": parameter_type or "object",
        "required": bool(value.get("required", value.get("in") == "path")),
        "in_": value.get("in", ""),
    }
    if value.get("in") == "body" and isinstance(schema, dict):
        result["schema"] = _resolve_schema(spec, schema)
    return result


def _security_headers(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    schemes = spec.get("securityDefinitions", {})
    if not schemes:
        schemes = spec.get("components", {}).get("securitySchemes", {})
    result = {}
    for value in schemes.values() if isinstance(schemes, dict) else []:
        if (
            not isinstance(value, dict)
            or value.get("type") != "apiKey"
            or value.get("in") != "header"
        ):
            continue
        name = value.get("name")
        if name:
            result[name] = {
                "name": name,
                "description": value.get("description", ""),
                "type": "string",
                "required": True,
                "in_": "header",
            }
    return result


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
    if isinstance(content, dict) and content:
        first_media = next((media for media in content.values() if isinstance(media, dict)), {})
        schema = first_media.get("schema", schema)
        examples = {
            media_type: media.get("example", media.get("examples"))
            for media_type, media in content.items()
            if isinstance(media, dict) and _nonempty(media.get("example", media.get("examples")))
        }
    return {
        "code": str(code),
        "description": value.get("description", ""),
        "data_schema": _resolve_schema(spec, schema),
        "examples": examples if isinstance(examples, dict) else {},
    }


def parse_openapi_endpoints(spec: dict[str, Any], list_id: int) -> list[dict[str, Any]]:
    """Convert OpenAPI 2/3 operations to the legacy parsed endpoint shape."""
    if not isinstance(spec, dict):
        return []
    endpoints = []
    security_headers = _security_headers(spec)
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        path_parameters = path_item.get("parameters", [])
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            request_schema = {
                "headers": dict(security_headers),
                "query_params": {},
                "path_params": {},
                "cookie_params": {},
                "request_body": {},
            }
            parameters = [*path_parameters, *operation.get("parameters", [])]
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
            endpoints.append(
                {
                    "id": f"{list_id}_{path}_{method.upper()}",
                    "path": path,
                    "method": method.upper(),
                    "request_schema": request_schema,
                    "response_schemas": responses,
                    "example_response_data": example,
                    "example_request_string": None,
                }
            )
    return endpoints


def _common(parse_input: ParseInput) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    catalog, detail = parse_input.catalog, parse_input.detail
    source = _official_record(parse_input.source_records)
    metadata = detail.get("metadata", {})
    schema = _schema_dataset(detail)
    summary = catalog.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    title = _first(
        source.get("title"), source.get("list_title"), schema.get("name"), catalog.get("title")
    )
    description = _first(
        source.get("desc"),
        source.get("description"),
        schema.get("description"),
        _metadata_value(metadata, "설명", "데이터 설명", "Description"),
        summary.get("description"),
    )
    department = _first(
        source.get("dept_nm"),
        source.get("org_nm"),
        _metadata_value(metadata, "제공기관", "관리부서명", "기관명"),
        summary.get("org_nm"),
    )
    category = _first(
        source.get("category_nm"),
        source.get("new_category_nm"),
        _metadata_value(metadata, "분류체계", "카테고리"),
    )
    data_format = _first(
        source.get("data_format"),
        source.get("ext"),
        _metadata_value(metadata, "확장자", "데이터포맷", "포맷"),
        detail.get("detail_format"),
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
        "department": department,
        "category": category,
        "data_format": data_format,
        "created_at": _first(source.get("created_at"), source.get("reg_date"), default=None),
        "update_at": _first(source.get("updated_at"), source.get("update_at"), default=None),
        "pricing": _first(source.get("is_charged"), _metadata_value(metadata, "비용부과유무")),
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
            _first(source.get("request_cnt"), source.get("download_cnt"), default=0)
        ),
        "title_en": _first(source.get("title_en"), default=""),
        "register_status": _first(source.get("register_status"), default=""),
        "use_prmisn_ennc": _first(source.get("use_prmisn_ennc"), default=""),
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
        record = stored.get("record", stored)
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


def _normalize_api(parse_input: ParseInput, document: dict[str, Any]) -> ParsedOutput:
    endpoints = []
    for spec in parse_input.detail.get("api_specs", []):
        endpoints.extend(parse_openapi_endpoints(spec, document["list_id"]))
    if not endpoints:
        endpoints.extend(_operation_endpoints(parse_input.detail, document["list_id"]))
    if not endpoints:
        endpoints.extend(_source_endpoints(parse_input.source_records, document["list_id"]))
    document.update(
        {
            "api_type": _first(
                _official_record(parse_input.source_records).get("api_type"), default=""
            ),
            "api_confirm_for_dev": _first(
                _official_record(parse_input.source_records).get("is_confirmed_for_dev"), default=""
            ),
            "api_confirm_for_prod": _first(
                _official_record(parse_input.source_records).get("is_confirmed_for_prod"),
                default="",
            ),
            "endpoints": endpoints,
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
    document.update(
        {
            "api_type": "",
            "endpoints": [
                endpoint
                for spec in detail.get("api_specs", [])
                for endpoint in parse_openapi_endpoints(spec, document["list_id"])
            ],
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
