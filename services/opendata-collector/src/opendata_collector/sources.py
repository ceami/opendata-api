"""Official catalog API and public portal listing adapters."""

import hashlib
import json
from urllib.parse import urlencode

TYPES = ("FILE", "API", "STD", "LINKED")
SUFFIXES = {"FILE": "fileData", "API": "openapi", "STD": "standard", "LINKED": "linkedData"}
ENDPOINTS = {"FILE": "file-data-list", "API": "open-data-list", "STD": "standard-data-list"}


def _integer(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"Invalid {name}")
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid {name}") from None
    if number < minimum:
        raise ValueError(f"Invalid {name}")
    return number


def parse_api_page(payload, data_type, page, page_size):
    if data_type not in ENDPOINTS or not isinstance(payload, dict):
        raise ValueError("Invalid official catalog response")
    total = _integer(payload.get("matchCount"), "matchCount")
    overall = _integer(payload.get("totalCount"), "totalCount")
    current = _integer(payload.get("currentCount"), "currentCount")
    if (
        _integer(payload.get("page"), "page", 1) != page
        or _integer(payload.get("perPage"), "perPage", 1) != page_size
    ):
        raise ValueError("Catalog API did not honor requested pagination")
    rows = payload.get("data")
    expected = min(page_size, max(0, total - (page - 1) * page_size))
    if not isinstance(rows, list) or len(rows) != current or current != expected or total > overall:
        raise ValueError("Catalog API count and records disagree")
    items, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            raise ValueError("Catalog record has no source identifier")
        list_id = _integer(row.get("list_id"), "list_id", 1)
        identity = json.dumps(
            [str(row["id"]), str(row.get("operation_seq") or "")],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        source_id = f"api:{data_type}:" + hashlib.sha256(identity.encode()).hexdigest()
        if source_id in seen:
            raise ValueError("Repeated source record within a catalog page")
        seen.add(source_id)
        items.append(
            {
                "catalog_id": f"{data_type}:{list_id}",
                "data_type": data_type,
                "list_id": list_id,
                "detail_url": f"https://www.data.go.kr/data/{list_id}/{SUFFIXES[data_type]}.do",
                "title": row.get("list_title") or row.get("title") or "",
                "summary": {},
                "source_id": source_id,
                "source_record": row,
            }
        )
    return {
        "items": items,
        "total": total,
        "overall_total": overall,
        "page": page,
        "page_size": page_size,
        "member_total": None,
        "source": "api",
    }


class CatalogSource:
    def __init__(self, http, *, mode="auto"):
        if mode not in {"auto", "api", "portal"}:
            raise ValueError("Unknown catalog source")
        if mode == "api" and not http.service_key:
            raise ValueError("API source requires ODP_SERVICE_KEY")
        self.http = http
        self.mode = (
            "api" if mode == "auto" and http.service_key else ("portal" if mode == "auto" else mode)
        )

    def page(self, data_type, page, page_size):
        if data_type not in TYPES or page < 1 or not 1 <= page_size <= 1000:
            raise ValueError("Invalid catalog type or pagination")
        if self.mode == "api" and data_type in ENDPOINTS:
            url = "https://api.odcloud.kr/api/15077093/v1/" + ENDPOINTS[data_type]
            raw = self.http.get(
                url + "?" + urlencode({"page": page, "perPage": page_size}),
                auth=True,
                kind="catalog_api",
            )
            try:
                payload = json.loads(raw.text)
            except ValueError:
                raise ValueError("Official catalog returned invalid JSON") from None
            return parse_api_page(payload, data_type, page, page_size), raw
        from .parsers import parse_listing

        url = "https://www.data.go.kr/tcs/dss/selectDataSetList.do?" + urlencode(
            {
                "dType": data_type,
                "keyword": "",
                "currentPage": page,
                "perPage": page_size,
                "sort": "date",
            }
        )
        raw = self.http.get(url, kind="catalog_html")
        parsed = parse_listing(raw.text, data_type, page, page_size)
        for item in parsed["items"]:
            item["source_id"] = "portal:" + item["catalog_id"]
            item["source_record"] = dict(item["summary"])
        parsed["source"] = "portal"
        return parsed, raw
