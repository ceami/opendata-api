"""Parse public data.go.kr pages without executing scripts or following actions.

ValueError prevents unexpected layouts or error/login pages becoming checkpoints.
"""

import json
import re
from html import unescape as html_unescape
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree
from xml.sax.saxutils import escape as xml_escape

from bs4 import BeautifulSoup, Tag

BASE_URL = "https://www.data.go.kr"
DETAIL_TYPES = {"openapi": "API", "fileData": "FILE", "standard": "STD", "linkedData": "LINKED"}
TYPE_LABELS = {
    "API": "오픈API",
    "FILE": "파일데이터",
    "STD": "표준데이터셋",
    "LINKED": "연계데이터",
}
DETAIL_PATH = re.compile(r"/data/(\d+)/(openapi|fileData|standard|linkedData)\.do$")
JS_LITERAL = r"""(?P<quote>["'`])(?P<body>(?:\\[\s\S]|(?!(?P=quote))[\s\S])*?)(?P=quote)"""
IDENTITY_FIELDS = {
    "publicDataPk",
    "publicDataDetailPk",
    "publicDataLinkedPk",
    "stdPublicDataPk",
    "updtDt",
    "isCoreData",
    "natCoreDataSe",
    "coreDataAt",
    "publicDataTy",
    "publicDataTyDetailCode",
    "dataSe",
}


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _integer(value: str) -> int:
    return int(value.replace(",", ""))


def _dataset_link(href: str, title: str = "") -> dict | None:
    url = urlsplit(urljoin(BASE_URL, href))
    if url.scheme not in {"http", "https"} or url.hostname not in {"data.go.kr", "www.data.go.kr"}:
        return None
    match = DETAIL_PATH.fullmatch(url.path)
    if not match:
        return None
    pk, suffix = match.groups()
    kind = DETAIL_TYPES[suffix]
    return {
        "catalog_id": f"{kind}:{int(pk)}",
        "data_type": kind,
        "list_id": int(pk),
        "detail_url": BASE_URL + url.path,
        "title": title,
    }


def _add_metadata(metadata: dict, label: str, value: str) -> None:
    if label:
        metadata.setdefault(label, []).append(value)


def parse_listing(html: str, data_type: str, requested_page: int, requested_page_size: int) -> dict:
    """Read a catalog page and validate its type, counts and echoed pagination."""
    if data_type not in TYPE_LABELS:
        raise ValueError(f"Unsupported dataset type: {data_type}")
    if requested_page < 1 or requested_page_size < 1:
        raise ValueError("Invalid requested pagination")
    soup = BeautifulSoup(html, "html.parser")
    for name, expected in (("currentPage", requested_page), ("perPage", requested_page_size)):
        values = [node.get("value", "") for node in soup.select(f'input[name="{name}"]')]
        if not values or any(not v.isdigit() or int(v) != expected for v in values):
            raise ValueError(f"Response pagination {name} does not match request {expected}")
    heading = _text(soup.select_one(".data-result-tit"))
    if TYPE_LABELS[data_type] not in heading.replace(" ", ""):
        raise ValueError("Missing or wrong catalog result heading")
    member_total = None
    if data_type == "STD":
        match = re.search(r"([\d,]+)\s*개\s*\(\s*([\d,]+)\s*건\s*\)", heading)
        if match:
            total, member_total = map(_integer, match.groups())
    else:
        match = re.search(r"\(\s*([\d,]+)\s*건\s*\)", heading)
        if match:
            total = _integer(match.group(1))
    if not match:
        raise ValueError("Missing or malformed catalog count")
    items, seen = [], set()
    for node in soup.select(".data-list-group .apply-result-item"):
        anchors = node.select(".apply-result-link a")
        if len(anchors) != 1:
            raise ValueError("Catalog item has missing or ambiguous detail link")
        title = _text(anchors[0])
        item = _dataset_link(anchors[0].get("href", ""), title)
        if not item or not title or item["data_type"] != data_type:
            raise ValueError("Catalog item has malformed identity, title or type")
        if item["catalog_id"] in seen:
            raise ValueError(f"Duplicate catalog item: {item['catalog_id']}")
        seen.add(item["catalog_id"])
        metadata = {}
        for li in node.select("li"):
            label = li.find("strong")
            if label:
                _add_metadata(metadata, _text(label), _text(li).removeprefix(_text(label)).strip())
        item["summary"] = {
            "description": _text(node.select_one(".apply-result-summary")),
            "badges": [_text(b) for b in node.select(".krds-badge")],
            "metadata": metadata,
            # Preserve text outside malformed li tags in linked listings.
            "text": _text(node.select_one(".in-result-item") or node),
        }
        items.append(item)
    if not items and (total != 0 or requested_page != 1):
        raise ValueError("Unexpected empty catalog page")
    expected_count = min(
        requested_page_size, max(total - (requested_page - 1) * requested_page_size, 0)
    )
    if len(items) != expected_count:
        raise ValueError("Catalog item count conflicts with pagination/total")
    return {
        "items": items,
        "total": total,
        "page": requested_page,
        "page_size": requested_page_size,
        "member_total": member_total,
    }


def _decode_js_literal(body: str, quote: str) -> str:
    """Decode one string-literal layer, never JavaScript expressions."""
    if quote == "`" and re.search(r"(?<!\\)\$\{", body):
        raise ValueError("Dynamic template interpolation in metadata")
    escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}

    def replace(match):
        value = match.group(0)[1:]
        if value.startswith(("u", "x")) and len(value) > 1:
            return chr(int(value[1:], 16))
        if value in {"\n", "\r\n"}:
            return ""
        return escapes.get(value, value)

    return re.sub(r"\\(?:u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|\r?\n|[\s\S])", replace, body)


def _literal_after(pattern: str, script: str):
    match = re.search(pattern + r"\s*" + JS_LITERAL, script)
    return _decode_js_literal(match["body"], match["quote"]) if match else None


def _statement_literal_after(pattern: str, script: str):
    """Recover a template literal only when its closing delimiter ends the assignment."""
    initial = _literal_after(pattern, script)
    assignment = re.search(pattern + r"\s*", script)
    if not assignment or assignment.end() >= len(script) or script[assignment.end()] != "`":
        return initial
    start = assignment.end() + 1
    cursor = start
    while True:
        end = script.find("`", cursor)
        if end < 0:
            return initial
        cursor = end + 1
        if _is_escaped_quote(script, end):
            continue
        if re.match(r"\s*;", script[cursor:]):
            return _decode_js_literal(script[start:end], "`")


def _is_escaped_quote(value: str, index: int) -> bool:
    backslashes, previous = 0, index - 1
    while previous >= 0 and value[previous] == "\\":
        backslashes += 1
        previous -= 1
    return bool(backslashes % 2)


def _escape_unescaped_quotes(value: str) -> tuple[str, int]:
    output, repairs = [], 0
    for index, character in enumerate(value):
        if character != '"' or _is_escaped_quote(value, index):
            output.append(character)
        else:
            output.append('\\"')
            repairs += 1
    return "".join(output), repairs


def _has_json_sequence_boundary(value: str) -> bool:
    candidates = re.finditer(r'"\s*,\s*"', value)
    return any(not _is_escaped_quote(value, match.start()) for match in candidates)


def _normalize_metadata_text(value: str) -> str:
    soup = BeautifulSoup(value, "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split())


def load_json_metadata(value: str, *, expected_descriptions=()) -> tuple[object, int]:
    """Parse JSON, accepting ambiguous description quotes only after DOM cross-check."""
    expected = {
        _normalize_metadata_text(description)
        for description in expected_descriptions
        if isinstance(description, str) and description.strip()
    }
    try:
        return json.loads(value, strict=False), 0
    except json.JSONDecodeError as original_error:
        normalized = value.replace("\r\n", "\n").replace("\r", "\\r")
        pattern = re.compile(r'^(\s*"(?:[^"\\]|\\.)+"\s*:\s*")(.*)("\s*,?\s*)$')
        repaired_lines, repair_count = [], 0
        for line in normalized.splitlines(keepends=True):
            ending = "\n" if line.endswith("\n") else ""
            content = line[:-1] if ending else line
            match = pattern.match(content)
            if match:
                body, count = _escape_unescaped_quotes(match.group(2))
                if _has_json_sequence_boundary(match.group(2)):
                    is_description = bool(re.fullmatch(r'\s*"description"\s*:\s*"', match.group(1)))
                    try:
                        candidate = json.loads(f'"{body}"', strict=False)
                    except json.JSONDecodeError:
                        candidate = None
                    if (
                        not is_description
                        or not expected
                        or not isinstance(candidate, str)
                        or _normalize_metadata_text(candidate) not in expected
                    ):
                        repaired_lines.append(content + ending)
                        continue
                content = match.group(1) + body + match.group(3)
                repair_count += count
            repaired_lines.append(content + ending)
        if not repair_count:
            raise original_error
        try:
            return json.loads("".join(repaired_lines), strict=False), repair_count
        except json.JSONDecodeError:
            raise original_error from None


_DCAT_LITERAL_TAGS = (
    "dct:title",
    "dct:description",
    "dct:accessURL",
    "dct:conformsTo",
    "dcat:keyword",
    "vcard:fn",
    "vcard:organization-name",
    "vcard:organization-unit",
    "skos:prefLabel",
    "rdfs:label",
)


def parse_dcat_metadata(value: bytes, text: str) -> tuple[ElementTree.Element, bool]:
    """Parse DCAT, repairing markup only inside known RDF literal fields."""
    xml_text = text.upper()
    xml_bytes = value.replace(b"\x00", b"").upper()
    if any(
        marker in xml_text or marker.encode() in xml_bytes for marker in ("<!DOCTYPE", "<!ENTITY")
    ):
        raise ValueError("Unsupported XML declarations in DCAT")
    try:
        return ElementTree.fromstring(value), False
    except ElementTree.ParseError as original_error:
        repaired = text.replace("\r\n", "\n")
        namespaces = {}
        declaration = re.compile(
            r"\b(?P<name>xmlns(?::[A-Za-z_][\w.-]*)?)\s*=\s*"
            r"(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
            re.S,
        )
        for match in declaration.finditer(repaired):
            namespaces[match["name"]] = match["value"]
        namespace_attributes = ""
        for name, uri in namespaces.items():
            escaped_uri = xml_escape(html_unescape(uri), {'"': "&quot;"})
            namespace_attributes += f' {name}="{escaped_uri}"'
        repair_count = 0

        def repair_literal(match):
            nonlocal repair_count
            body = match["body"]
            try:
                ElementTree.fromstring(f"<repair-root{namespace_attributes}>{body}</repair-root>")
                return match.group(0)
            except ElementTree.ParseError:
                pass
            body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
            body = "".join(
                character for character in body if character in "\t\n\r" or ord(character) >= 0x20
            )
            body = xml_escape(html_unescape(body), {'"': "&quot;"})
            repair_count += 1
            return match["open"] + body + match["close"]

        for tag in _DCAT_LITERAL_TAGS:
            pattern = re.compile(
                rf"(?P<open><{re.escape(tag)}(?:\s[^>]*)?>)"
                rf"(?P<body>.*?)(?P<close></{re.escape(tag)}>)",
                re.I | re.S,
            )
            repaired = pattern.sub(repair_literal, repaired)
        if not repair_count:
            raise original_error
        try:
            return ElementTree.fromstring(repaired.encode()), True
        except ElementTree.ParseError:
            raise original_error from None


def _schema_documents(soup: BeautifulSoup, expected_descriptions=()) -> tuple[list, list, list]:
    documents, errors, repairs = [], [], []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value, repair_count = load_json_metadata(
                script.string or script.get_text(),
                expected_descriptions=expected_descriptions,
            )
        except (json.JSONDecodeError, TypeError):
            errors.append({"kind": "schema_org", "error": "Malformed embedded schema.org JSON"})
            continue
        values = value if isinstance(value, list) else [value]
        if any(not isinstance(v, dict) for v in values):
            errors.append(
                {"kind": "schema_org", "error": "Embedded schema.org JSON must contain objects"}
            )
            continue
        documents.extend(values)
        if repair_count:
            repairs.append(
                {
                    "kind": "schema_org",
                    "method": "escape_unescaped_json_quotes",
                    "count": repair_count,
                }
            )
    return documents, errors, repairs


def _schema_datasets(documents: list):
    for document in documents:
        types = document.get("@type", [])
        if types == "Dataset" or (isinstance(types, list) and "Dataset" in types):
            yield document
        graph = document.get("@graph", [])
        if isinstance(graph, list):
            yield from _schema_datasets([d for d in graph if isinstance(d, dict)])


def _tables(soup: BeautifulSoup) -> list:
    tables = []
    for table in soup.select("table"):
        header_rows, rows, spans = [], [], []
        for tr in table.find_all("tr"):
            if tr.find_parent("table") is not table:
                continue
            cells = tr.find_all(["th", "td"], recursive=False)
            values = [_text(cell) for cell in cells]
            if cells and all(cell.name == "th" for cell in cells):
                header_rows.append(values)
            elif cells:
                rows.append(values)
            spans.append(
                [{k: cell[k] for k in ("rowspan", "colspan") if cell.has_attr(k)} for cell in cells]
            )
        tables.append(
            {
                "caption": _text(table.find("caption")),
                "headers": header_rows,
                "rows": rows,
                "cell_spans": spans,
            }
        )
    return tables


def _resource_link(href: str) -> dict | None:
    url = urljoin(BASE_URL, href)
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "data.go.kr",
        "www.data.go.kr",
    }:
        return None
    if re.fullmatch(r"/catalog/\d+/[A-Za-z]+\.json", parsed.path):
        return {"kind": "schema_org", "url": url}
    if re.fullmatch(r"/biz/dcat/metadata/(?:linked/)?\d+\.do", parsed.path):
        return {"kind": "dcat", "url": url}
    return None


def _attachments(soup: BeautifulSoup) -> list:
    attachments = []
    for node in soup.select("a[href], [onclick]"):
        action = node.get("onclick", "")
        href = node.get("href", "")
        reference = node.find_parent(class_="file-info")
        name = _text(reference.select_one(".file-name")) if reference else ""
        attachment = {"name": name or _text(node) or node.get("title", "")}
        args = re.search(
            r"\bfn_fileDownload\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)", action
        )
        file_data = re.search(r"\bfn_fileDataDown\((.*?)\)", action, re.S)
        if args:
            attachment.update(file_id=args[1], file_detail_sn=args[2])
        elif file_data:
            values = re.findall(r"['\"]([^'\"]*)['\"]", file_data[1])
            if len(values) != 5:
                raise ValueError("Malformed file download identifiers")
            attachment["arguments"] = values
            attachment.update(
                zip(
                    ("public_data_pk", "public_data_detail_pk", "file_id", "file_detail_sn"),
                    values[:4],
                )
            )
            if "fileDetailObj.fn_fileDataDown" in action:
                attachment["public_data_hist_sn"] = values[4]
            elif values[4].lower() in {"csv", "json", "xml", "xlsx", "xls", "zip", "txt"}:
                attachment["format"] = values[4]
        else:
            if not href or href.startswith(("#", "javascript:")):
                href = _literal_after(r"window\.open\(", action) or ""
            parsed = urlsplit(urljoin(BASE_URL, href))
            if (
                not href
                or parsed.scheme not in {"https", "http"}
                or not re.search(r"(?:/download/|fileDownload\.do$)", parsed.path, re.I)
            ):
                continue
            attachment["url"] = urljoin(BASE_URL, href)
        if attachment not in attachments:
            attachments.append(attachment)
    return attachments


def parse_standard_members(html: str) -> dict:
    """Read a stdFileList fragment; member identifiers may be opaque UDDIs."""
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("#tab-layer-std-03") or soup
    tables = [
        table
        for table in section.select("table")
        if table.select_one(".openFileDetailPopup")
        or {"데이터명", "제공기관", "등록일"}.issubset({_text(th) for th in table.select("th")})
    ]
    if len(tables) != 1:
        raise ValueError("Missing or ambiguous standard member table")
    items, seen = [], set()
    for row in tables[0].select("tbody tr"):
        link = row.select_one("a.openFileDetailPopup")
        if not link:
            if "데이터가 없습니다" in _text(row):
                continue
            raise ValueError("Missing standard member identity")
        pk = link.get("data-public-pk", "")
        if not pk or pk in seen:
            raise ValueError("Missing or duplicate standard member identity")
        seen.add(pk)
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            raise ValueError("Malformed standard member row")
        title_node = BeautifulSoup(str(link), "html.parser")
        for badge in title_node.select(".krds-badge"):
            badge.decompose()
        items.append(
            {
                "public_data_detail_pk": pk,
                "title": _text(title_node),
                "provider": _text(cells[1]),
                "registered_at": _text(cells[2]),
                "metadata": {"row": [_text(cell) for cell in cells]},
            }
        )
    pages = [
        int(match[1])
        for link in section.select(".krds-pagination a")
        if (
            match := re.search(
                r"fn_page\(\s*(\d+)\s*\)", link.get("href", "") + link.get("onclick", "")
            )
        )
    ]
    return {"items": items, "pages": max(pages, default=1)}


def _metadata(soup: BeautifulSoup) -> dict:
    metadata = {}
    for li in soup.select(".info-ul li"):
        key, value = li.select_one("strong.key"), li.select_one("div.value")
        if key and value is not None:
            text_value = _text(value)
            if not text_value and "전화" in _text(key):
                for script in value.select("script"):
                    phone = _literal_after(
                        r"\b(?:var|let|const)\s+\w*TelNo\s*=", script.string or ""
                    )
                    if phone:
                        text_value = phone
            _add_metadata(metadata, _text(key), text_value)
    for row in soup.select("table tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        for index, cell in enumerate(cells[:-1]):
            if cell.name == "th" and cells[index + 1].name == "td":
                _add_metadata(metadata, _text(cell), _text(cells[index + 1]))
    return metadata


def parse_detail(html: str, item: dict, source_url: str | None = None) -> dict:
    """Preserve detail metadata, embedded specs, tables and public resource links."""
    soup = BeautifulSoup(html, "html.parser")
    metadata = _metadata(soup)
    schema, parse_errors, metadata_repairs = _schema_documents(
        soup, expected_descriptions=metadata.get("설명", [])
    )
    hidden = {
        node.get("name") or node.get("id"): node.get("value", "")
        for node in soup.select("input")
        if (node.get("name") or node.get("id")) in IDENTITY_FIELDS
    }
    expected = item["catalog_id"]
    schema_ids = {
        link["catalog_id"]
        for d in _schema_datasets(schema)
        if isinstance(d.get("url"), str) and (link := _dataset_link(d["url"]))
    }
    hidden_id = hidden.get(
        "publicDataLinkedPk" if item["data_type"] == "LINKED" else "publicDataPk"
    )
    if schema_ids and expected not in schema_ids:
        raise ValueError("Detail schema identity does not match requested dataset")
    page_title = _text(soup.title).partition("|")[0].strip()
    response_url = urlsplit(source_url or "")
    expected_url = urlsplit(item["detail_url"])
    response_identity_matches = (
        response_url.scheme == expected_url.scheme == "https"
        and response_url.hostname == expected_url.hostname
        and response_url.port == expected_url.port
        and response_url.path == expected_url.path
    )
    standard_title_fallback = (
        item["data_type"] == "STD"
        and bool(parse_errors)
        and bool(hidden_id and hidden_id.isdigit())
        and response_identity_matches
        and "표준데이터" in page_title
        and page_title == item.get("title")
    )
    if (
        hidden_id != str(item["list_id"])
        and not (item["data_type"] == "STD" and expected in schema_ids)
        and not standard_title_fallback
    ):
        if hidden_id or expected not in schema_ids:
            raise ValueError("Missing or mismatched detail identity")
    resources, related, api_specs = [], [], []
    for anchor in soup.select("a[href]"):
        resource = _resource_link(anchor["href"])
        if resource and resource not in resources:
            resources.append(resource)
        dataset = _dataset_link(anchor["href"], _text(anchor))
        if (
            dataset
            and dataset["catalog_id"] != expected
            and dataset["catalog_id"] not in {d["catalog_id"] for d in related}
        ):
            related.append(dataset)
    for script in soup.select("script:not([type='application/ld+json'])"):
        source = script.string or script.get_text()
        spec = _statement_literal_after(r"\b(?:const|let|var)\s+swaggerJson\s*=", source)
        if spec == "undefined":
            pass
        elif spec:
            try:
                document = json.loads(spec, strict=False)
            except json.JSONDecodeError as exc:
                raise ValueError("Malformed embedded swaggerJson") from exc
            if not isinstance(document, dict):
                raise ValueError("swaggerJson must be an object")
            api_specs.append(document)
        elif spec is None and re.search(r"\b(?:const|let|var)\s+swaggerJson\s*=", source):
            raise ValueError("Unsupported embedded swaggerJson expression")
        for pattern in (
            r"\b(?:const|let|var)\s+swaggerUrl\s*=",
            r"SwaggerUIBundle\(\s*\{\s*url\s*:",
        ):
            url = _literal_after(pattern, source)
            if url:
                url = urljoin(BASE_URL, url)
                if url.startswith("http://infuser.odcloud.kr/oas/"):
                    url = "https://" + url.removeprefix("http://")
                if urlsplit(url).scheme not in {"http", "https"}:
                    raise ValueError("Invalid OpenAPI spec URL")
                resource = {"kind": "openapi_spec", "url": url}
                if resource not in resources:
                    resources.append(resource)
    tables = _tables(soup)
    if api_specs or any(r["kind"] == "openapi_spec" for r in resources):
        detail_format = "SWAGGER"
    elif tables:
        detail_format = "TABLE"
    elif item["data_type"] == "LINKED" or metadata.get("URL"):
        detail_format = "LINK"
    else:
        detail_format = "METADATA"
    result = {
        "metadata": metadata,
        "schema_org": schema,
        "api_specs": api_specs,
        "resource_links": resources,
        "attachments": _attachments(soup),
        "related_datasets": related,
        "detail_format": detail_format,
        "tables": tables,
        "hidden_fields": hidden,
        "parse_errors": parse_errors,
        "metadata_repairs": metadata_repairs,
    }
    if soup.select_one("#fileHistAndCsvData") and soup.select_one(
        'script[src="/js/biz/datset/script_fileDetail.js"]'
    ):
        if not hidden.get("publicDataPk") or not hidden.get("publicDataDetailPk"):
            raise ValueError("Missing file history identifiers")
        result["file_history"] = {
            "url": BASE_URL + "/tcs/dss/selectHistAndCsvData.do",
            "params": {
                "publicDataPk": hidden["publicDataPk"],
                "publicDataDetailPk": hidden["publicDataDetailPk"],
            },
        }
    operation_select = soup.select_one("#open_api_detail_select")
    if operation_select and "/tcs/dss/selectApiDetailFunction.do" in html:
        operation_public_data_pk = (
            hidden.get("stdPublicDataPk")
            if hidden.get("natCoreDataSe") == "Y"
            else hidden.get("publicDataPk")
        )
        if not hidden.get("publicDataDetailPk") or not operation_public_data_pk:
            raise ValueError("Missing API operation detail identifier")
        operations = []
        for option in operation_select.select("option[value]"):
            sequence = option["value"].strip()
            if not sequence:
                continue
            operations.append(
                {
                    "name": _text(option),
                    "url": BASE_URL + "/tcs/dss/selectApiDetailFunction.do",
                    "params": {
                        "oprtinSeqNo": sequence,
                        "publicDataDetailPk": hidden["publicDataDetailPk"],
                        "publicDataPk": operation_public_data_pk,
                    },
                }
            )
        if operations:
            result["api_operations"] = operations
    form = soup.select_one("#standDataVO")
    if item["data_type"] == "STD" and form:
        section = soup.select_one("#tab-layer-std-03")
        heading = _text(section.select_one("h3")) if section else ""
        count = re.search(r"총\s*([\d,]+)\s*건", heading)
        pk = form.select_one('input[name="publicDataPk"]')
        if not count or not pk or not pk.get("value", "").isdigit():
            raise ValueError("Missing standard member count or identity")
        result["standard_members"] = {
            **parse_standard_members(str(section)),
            "total": _integer(count[1]),
            "list_url": BASE_URL + "/tcs/dss/stdFileList.do?publicDataPk=" + pk["value"],
        }
    return result


def parse_metadata_fragment(html: str) -> dict:
    """Parse read-only history, member popup or operation metadata fragments.

    Known portal section wrappers allow legitimately empty history/preview
    responses. An unrecognized login, maintenance, or error shell is rejected.
    Only declared file popup identifiers become follow-up request descriptors.
    """
    soup = BeautifulSoup(html, "html.parser")
    tags = soup.find_all(True)
    has_non_script_text = any(
        str(node).strip()
        for node in soup.find_all(string=True)
        if node.find_parent("script") is None
    )
    script_only = (
        bool(tags) and all(tag.name == "script" for tag in tags) and not has_non_script_text
    )
    empty_history = script_only and any(
        "/tcs/dss/selectDpkDetailInfo.do" in source
        and ".openFileDetailPopup" in source
        and "fileDetailPopup" in source
        for script in soup.select("script")
        if (source := script.string or script.get_text())
    )
    if not empty_history and not soup.select_one(
        ".info-ul, table th, #tab-layer-file-04, #tab-layer-file-05, "
        "#file-detail-popup, #open-api-detail-result"
    ):
        raise ValueError("Unrecognized metadata fragment")
    file_details, popups = [], []
    for link in soup.select("a.openFileDetailPopup"):
        pk = link.get("data-public-pk", "")
        if not pk:
            raise ValueError("Missing file popup identity")
        detail = {"name": _text(link), "public_data_detail_pk": pk}
        params = {"publicDataDetailPk": pk}
        history_sn = link.get("data-public-detail-sn")
        if history_sn:
            detail["public_data_detail_sn"] = history_sn
            params["publicDataHistSn"] = history_sn
        file_details.append(detail)
        descriptor = {"url": BASE_URL + "/tcs/dss/selectDpkDetailInfo.do", "params": params}
        if descriptor not in popups:
            popups.append(descriptor)
    return {
        "metadata": _metadata(soup),
        "tables": _tables(soup),
        "attachments": _attachments(soup),
        "text": _text(soup),
        "file_details": file_details,
        "detail_popups": popups,
    }
