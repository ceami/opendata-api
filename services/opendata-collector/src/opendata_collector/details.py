"""Collect published metadata exports and read-only detail fragments."""

import json
from urllib.parse import urlencode
from xml.etree import ElementTree

from .http import FetchError
from .parsers import (
    load_json_metadata,
    parse_dcat_metadata,
    parse_detail,
    parse_metadata_fragment,
    parse_standard_members,
)


class DetailCollector:
    def __init__(self, http, *, max_member_pages=None):
        if max_member_pages is not None and max_member_pages < 1:
            raise ValueError("Member page limit must be positive")
        self.http, self.max_member_pages = http, max_member_pages

    def collect(self, item, heartbeat=lambda: None):
        resources, errors = [], []

        def fetch(url, kind, *, method="GET", data=None):
            heartbeat()
            resource = self.http.request(method, url, kind=kind, data=data)
            resources.append(resource)
            return resource

        raw = fetch(item["detail_url"], "detail_html")
        try:
            detail = parse_detail(raw.text, item, raw.url)
        except ValueError as error:
            return (
                {"metadata": {}, "detail_format": "ERROR"},
                resources,
                [{"kind": "detail", "error": str(error)}],
            )
        errors.extend(detail.pop("parse_errors", []))
        for link in detail.get("resource_links", []):
            kind = link["kind"]
            try:
                resource = fetch(link["url"], kind)
                if kind in {"schema_org", "openapi_spec"}:
                    payload, repair_count = load_json_metadata(resource.text)
                    if repair_count:
                        detail.setdefault("metadata_repairs", []).append(
                            {
                                "kind": kind,
                                "method": "escape_unescaped_json_quotes",
                                "count": repair_count,
                            }
                        )
                    if not isinstance(payload, dict):
                        raise ValueError("Metadata export is not a JSON object")
                    if kind == "schema_org":
                        if not payload.get("name") or payload.get("@type") != "Dataset":
                            raise ValueError("Metadata export is not a schema.org Dataset")
                        detail["schema_org"].append(payload)
                    else:
                        if not (payload.get("swagger") or payload.get("openapi")) or not isinstance(
                            payload.get("paths"), dict
                        ):
                            raise ValueError("Metadata export is not an OpenAPI specification")
                        detail["api_specs"].append(payload)
                elif kind == "dcat":
                    root, repaired = parse_dcat_metadata(resource.content, resource.text)
                    if repaired:
                        detail.setdefault("metadata_repairs", []).append(
                            {"kind": "dcat", "method": "escape_invalid_xml_literals"}
                        )
                    if root.tag != "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF":
                        raise ValueError("Metadata export is not DCAT RDF XML")
            except (ValueError, FetchError, ElementTree.ParseError) as error:
                errors.append({"kind": kind, "url": link["url"], "error": str(error)})
        if detail.get("api_specs"):
            detail["detail_format"] = "SWAGGER"

        popups = []
        for operation in detail.get("api_operations", []):
            try:
                resource = fetch(
                    operation["url"], "api_operation", method="POST", data=operation["params"]
                )
                detail.setdefault("operation_details", []).append(
                    {
                        "operation": operation,
                        "data": parse_metadata_fragment(resource.text),
                    }
                )
            except (ValueError, FetchError) as error:
                errors.append(
                    {"kind": "api_operation", "error": str(error), "operation": operation}
                )

        history = detail.get("file_history")
        if history:
            try:
                url = history["url"]
                if history.get("params"):
                    url += ("&" if "?" in url else "?") + urlencode(history["params"])
                resource = fetch(url, "file_history")
                detail["file_history_data"] = parse_metadata_fragment(resource.text)
                popups.extend(detail["file_history_data"].get("detail_popups", []))
            except (ValueError, FetchError) as error:
                errors.append({"kind": "file_history", "error": str(error)})

        members = detail.get("standard_members")
        if members:
            seen = {row["public_data_detail_pk"] for row in members["items"]}
            rows = list(members["items"])
            for page in range(2, members["pages"] + 1):
                if self.max_member_pages is not None and page > self.max_member_pages:
                    errors.append(
                        {"kind": "standard_members", "error": "Member page limit reached"}
                    )
                    break
                try:
                    url = (
                        members["list_url"]
                        + "&"
                        + urlencode({"pageIndex": page, "searchKeyword2": ""})
                    )
                    resource = fetch(url, "standard_members")
                    result = parse_standard_members(resource.text)
                    if not result["items"]:
                        raise ValueError("Unexpected empty standard member page")
                    for row in result["items"]:
                        if row["public_data_detail_pk"] in seen:
                            raise ValueError("Repeated standard member across pages")
                        seen.add(row["public_data_detail_pk"])
                        rows.append(row)
                except (ValueError, FetchError) as error:
                    errors.append({"kind": "standard_members", "page": page, "error": str(error)})
                    break
            members["items"] = rows
            members["collected_count"] = len(rows)
            if len(rows) != members["total"]:
                errors.append(
                    {"kind": "standard_members", "error": "Standard member count mismatch"}
                )
            popups.extend(
                {
                    "url": "https://www.data.go.kr/tcs/dss/selectDpkDetailInfo.do",
                    "params": {"publicDataDetailPk": row["public_data_detail_pk"]},
                }
                for row in rows
            )
        seen_popups = set()
        for popup in popups:
            identity = json.dumps(popup, sort_keys=True)
            if identity in seen_popups:
                continue
            seen_popups.add(identity)
            try:
                resource = fetch(
                    popup["url"], "file_version_detail", method="POST", data=popup["params"]
                )
                detail.setdefault("detail_popups", []).append(
                    {
                        "request": popup,
                        "data": parse_metadata_fragment(resource.text),
                    }
                )
            except (ValueError, FetchError) as error:
                errors.append(
                    {"kind": "file_version_detail", "error": str(error), "request": popup}
                )
        return detail, resources, errors
