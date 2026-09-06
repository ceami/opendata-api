"""Validate the official monthly catalog snapshot and discover its CSV download."""

import csv
import io
import json
import re
from urllib.parse import urlencode, urlsplit

from bs4 import BeautifulSoup

BASE_URL = "https://www.data.go.kr"
SNAPSHOT_DATA_ID = "15062804"
SNAPSHOT_DETAIL_URL = f"{BASE_URL}/data/{SNAPSHOT_DATA_ID}/fileData.do"
SNAPSHOT_DESCRIPTOR_URL = f"{BASE_URL}/tcs/dss/selectFileDataDownload.do"
REQUIRED_HEADERS = ("목록키", "목록유형", "목록명", "목록 URL")
DETAIL_SUFFIXES = {"FILE": "fileData", "API": "openapi", "STD": "standard"}
TYPE_ALIASES = {
    "FILE": "FILE",
    "파일": "FILE",
    "파일데이터": "FILE",
    "API": "API",
    "오픈API": "API",
    "오픈 API": "API",
    "STD": "STD",
    "표준": "STD",
    "표준데이터": "STD",
    "표준 데이터": "STD",
    "표준데이터셋": "STD",
}
DETAIL_PATH = re.compile(r"/data/([0-9]+)/(fileData|openapi|standard)\.do$")
SNAPSHOT_MAX_BYTES = 256 * 1024 * 1024
ATTACHMENT_CALL = re.compile(r"\bfileDetailObj\.fn_fileDataDown\s*\((.*?)\)", re.S)


def _decode_csv(payload):
    if not isinstance(payload, (bytes, bytearray)):
        raise ValueError("Snapshot CSV must be bytes")
    try:
        return bytes(payload).decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return bytes(payload).decode("cp949")
        except UnicodeDecodeError:
            raise ValueError("Snapshot CSV has unsupported encoding") from None


def _normalize_type(value):
    if not isinstance(value, str) or value.strip() not in TYPE_ALIASES:
        raise ValueError("Snapshot row has unsupported catalog type")
    return TYPE_ALIASES[value.strip()]


def _list_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value.strip()) or int(value) < 1:
        raise ValueError("Snapshot row has invalid catalog ID")
    return int(value)


def _detail_identity(url, list_id, data_type):
    if not isinstance(url, str):
        raise ValueError("Snapshot row has invalid catalog URL")
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"data.go.kr", "www.data.go.kr"}
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Snapshot row has invalid catalog URL")
    match = DETAIL_PATH.fullmatch(parsed.path)
    if not match:
        raise ValueError("Snapshot row has invalid catalog URL")
    url_id, suffix = match.groups()
    if int(url_id) != list_id or DETAIL_SUFFIXES[data_type] != suffix:
        raise ValueError("Snapshot row URL disagrees with catalog identity")
    return BASE_URL + parsed.path


def parse_snapshot_csv(payload):
    """Return normalized catalog rows after validating the entire CSV structure."""
    try:
        reader = csv.DictReader(io.StringIO(_decode_csv(payload), newline=""), strict=True)
        fieldnames = reader.fieldnames
        if (
            not fieldnames
            or any(not isinstance(name, str) or not name.strip() for name in fieldnames)
            or len(set(fieldnames)) != len(fieldnames)
            or not set(REQUIRED_HEADERS).issubset(fieldnames)
        ):
            raise ValueError("Snapshot CSV is missing required headers")
        seen = set()
        items = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Snapshot CSV row has an unexpected number of columns")
            list_id = _list_id(row["목록키"])
            data_type = _normalize_type(row["목록유형"])
            detail_url = _detail_identity(row["목록 URL"], list_id, data_type)
            title = row["목록명"].strip()
            if not title:
                raise ValueError("Snapshot row has no catalog title")
            catalog_id = f"{data_type}:{list_id}"
            if catalog_id in seen:
                raise ValueError("Snapshot CSV has duplicate catalog identity")
            seen.add(catalog_id)
            items.append(
                {
                    "catalog_id": catalog_id,
                    "data_type": data_type,
                    "list_id": list_id,
                    "detail_url": detail_url,
                    "title": title,
                    "source_id": f"snapshot:{catalog_id}",
                    "source_record": dict(row),
                }
            )
        if not items:
            raise ValueError("Snapshot CSV has no catalog rows")
        return items

    except csv.Error:
        raise ValueError("Snapshot CSV has malformed quoting or structure") from None


def _snapshot_attachment(html):
    soup = BeautifulSoup(html, "html.parser")
    attachments = []
    for node in soup.select("[onclick]"):
        match = ATTACHMENT_CALL.search(node.get("onclick", ""))
        if not match:
            continue
        values = re.findall(r"['\"]([^'\"]*)['\"]", match.group(1))
        if len(values) != 5:
            raise ValueError("Snapshot download attachment is malformed")
        public_data_pk, public_data_detail_pk, atch_file_id, file_detail_sn, _ = values
        if public_data_pk != SNAPSHOT_DATA_ID or not public_data_detail_pk or not file_detail_sn:
            raise ValueError("Snapshot download attachment has invalid identity")
        attachments.append((public_data_detail_pk, atch_file_id, file_detail_sn))
    if len(attachments) != 1:
        raise ValueError("Snapshot page has missing or ambiguous download attachment")
    return attachments[0]


def _positive_ascii_decimal(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value) and int(value) > 0:
        return value
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return str(value)
    return None


def discover_snapshot_download(http):
    """Return the official CSV name and URL after validating its read-only descriptor."""
    detail = http.get(SNAPSHOT_DETAIL_URL, kind="snapshot_detail")
    public_data_detail_pk, atch_file_id, file_detail_sn = _snapshot_attachment(detail.text)
    descriptor = http.request(
        "POST",
        SNAPSHOT_DESCRIPTOR_URL,
        kind="snapshot_descriptor",
        data={
            "publicDataDetailPk": public_data_detail_pk,
            "publicDataPk": SNAPSHOT_DATA_ID,
            "atchFileId": atch_file_id,
            "fileDetailSn": file_detail_sn,
            "publicDataTyCode": "PR0051",
        },
    )
    try:
        payload = json.loads(descriptor.text)
    except (TypeError, ValueError):
        raise ValueError("Snapshot download descriptor is not JSON") from None
    if not isinstance(payload, dict) or payload.get("status") is not True:
        raise ValueError("Snapshot download descriptor is invalid")
    info = payload.get("dataSetFileDetailInfo")
    atch_file_id = payload.get("atchFileId")
    file_detail_sn = _positive_ascii_decimal(payload.get("fileDetailSn"))
    name = info.get("dataNm") if isinstance(info, dict) else None
    public_data_pk = (
        _positive_ascii_decimal(info.get("publicDataPk")) if isinstance(info, dict) else None
    )
    returned_detail_pk = info.get("publicDataDetailPk") if isinstance(info, dict) else None
    if (
        public_data_pk != SNAPSHOT_DATA_ID
        or returned_detail_pk != public_data_detail_pk
        or not isinstance(atch_file_id, str)
        or not atch_file_id.strip()
        or file_detail_sn is None
        or not isinstance(name, str)
        or not name.strip()
    ):
        raise ValueError("Snapshot download descriptor is invalid")
    atch_file_id = atch_file_id.strip()
    return {
        "name": name.strip(),
        "url": BASE_URL
        + "/cmm/cmm/fileDownload.do?"
        + urlencode(
            {
                "atchFileId": atch_file_id,
                "fileDetailSn": str(file_detail_sn),
                "dataNm": name.strip(),
            }
        ),
    }


class SnapshotPipeline:
    """Validate a complete monthly CSV before publishing its current rows."""

    def __init__(self, store):
        self.store = store

    def run(self, payload, *, source):
        rows = parse_snapshot_csv(payload)
        return self.store.persist(rows, source=source, raw_content=bytes(payload))
