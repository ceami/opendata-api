"""Select and extract text from official portal reference-document attachments."""

import hashlib
import io
import json
import re
import struct
import zipfile
import zlib
from urllib.parse import urlencode
from xml.etree import ElementTree

import olefile
from pypdf import PdfReader

BASE_URL = "https://www.data.go.kr"
DOWNLOAD_PATH = "/cmm/cmm/fileDownload.do"
SUPPORTED_FORMATS = {"pdf": "PDF", "docx": "DOCX", "hwp": "HWP", "hwpx": "HWPX"}
FILE_ID = re.compile(r"FILE_[A-Za-z0-9_]+$")
POSITIVE_DECIMAL = re.compile(r"[1-9][0-9]*$")
SAFE_DETAIL_ID = re.compile(r"[^\s/\\]+$")
HWP_PARA_HEADER = 66
HWP_PARA_TEXT = 67


def detect_reference_format(name):
    """Return the supported format implied by a registered attachment name."""
    if not isinstance(name, str):
        return None
    _, dot, extension = name.strip().rpartition(".")
    return SUPPORTED_FORMATS.get(extension.lower()) if dot else None


def reference_attachment_identity(
    catalog_id, public_data_pk, public_data_detail_pk, file_id, file_detail_sn
):
    """Return a deterministic identity for one portal attachment version."""
    values = {
        "catalog_id": str(catalog_id),
        "file_detail_sn": str(file_detail_sn),
        "file_id": str(file_id),
        "public_data_detail_pk": str(public_data_detail_pk),
        "public_data_pk": str(public_data_pk),
    }
    encoded = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "reference:" + hashlib.sha256(encoded).hexdigest()


def _positive_decimal(value):
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if POSITIVE_DECIMAL.fullmatch(value) else None


def _attachment_identifiers(item, detail, attachment):
    list_id = _positive_decimal(item.get("list_id"))
    data_type = item.get("data_type")
    catalog_id = item.get("catalog_id")
    if not list_id or not isinstance(data_type, str) or catalog_id != f"{data_type}:{list_id}":
        return None
    hidden = detail.get("hidden_fields") if isinstance(detail.get("hidden_fields"), dict) else {}
    public_data_pk = attachment.get("public_data_pk", hidden.get("publicDataPk", list_id))
    public_data_detail_pk = attachment.get(
        "public_data_detail_pk", hidden.get("publicDataDetailPk")
    )
    file_id = attachment.get("file_id")
    file_detail_sn = attachment.get("file_detail_sn")
    arguments = attachment.get("arguments")
    if arguments is not None:
        if not isinstance(arguments, list) or len(arguments) != 5:
            return None
        public_data_pk, public_data_detail_pk, file_id, file_detail_sn, _ = arguments
    public_data_pk = _positive_decimal(public_data_pk)
    file_detail_sn = _positive_decimal(file_detail_sn)
    if (
        public_data_pk != list_id
        or not isinstance(public_data_detail_pk, str)
        or not SAFE_DETAIL_ID.fullmatch(public_data_detail_pk)
        or not isinstance(file_id, str)
        or not FILE_ID.fullmatch(file_id)
        or file_detail_sn is None
    ):
        return None
    return list_id, public_data_detail_pk, file_id, file_detail_sn


def reference_download_url(file_id, file_detail_sn, name):
    """Build the only official attachment download URL accepted by this collector."""
    return BASE_URL + DOWNLOAD_PATH + "?" + urlencode(
        {"atchFileId": file_id, "fileDetailSn": file_detail_sn, "dataNm": name}
    )


def select_reference_attachments(item, detail):
    """Return supported registered attachments, excluding links and malformed identifiers."""
    if not isinstance(item, dict) or not isinstance(detail, dict):
        return []
    attachments = detail.get("attachments")
    if not isinstance(attachments, list):
        return []
    selected, seen = [], set()
    for attachment in attachments:
        if not isinstance(attachment, dict) or attachment.get("url"):
            continue
        name = attachment.get("name")
        document_format = detect_reference_format(name)
        if not document_format:
            continue
        identifiers = _attachment_identifiers(item, detail, attachment)
        if identifiers is None:
            continue
        public_data_pk, public_data_detail_pk, file_id, file_detail_sn = identifiers
        attachment_id = reference_attachment_identity(
            item["catalog_id"], public_data_pk, public_data_detail_pk, file_id, file_detail_sn
        )
        if attachment_id in seen:
            continue
        seen.add(attachment_id)
        selected.append(
            {
                "catalog_id": item["catalog_id"],
                "name": name.strip(),
                "format": document_format,
                "public_data_pk": public_data_pk,
                "public_data_detail_pk": public_data_detail_pk,
                "file_id": file_id,
                "file_detail_sn": file_detail_sn,
                "url": reference_download_url(file_id, file_detail_sn, name.strip()),
                "attachment_id": attachment_id,
            }
        )
    return selected


def _result(status, text="", error=None):
    return {"status": status, "text": text, "char_count": len(text), "error": error}


def _bounded_text(parts, max_chars):
    text = "\n\n".join(part for part in parts if part)
    if len(text) > max_chars:
        return _result("TRUNCATED", text[:max_chars])
    return _result("EXTRACTED", text)


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _xml_paragraphs(content):
    root = ElementTree.fromstring(content)
    paragraphs = []
    for paragraph in root.iter():
        if _local_name(paragraph.tag) != "p":
            continue
        chunks = []
        for node in paragraph.iter():
            name = _local_name(node.tag)
            if name in {"t", "text"} and node.text:
                chunks.append(node.text)
            elif name in {"br", "lineBreak"}:
                chunks.append("\n")
        value = "".join(chunks).strip()
        if value:
            paragraphs.append(value)
    return paragraphs


def _zip_xml(payload, document_format):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        if document_format == "DOCX":
            names = ["word/document.xml"] if "word/document.xml" in names else []
        else:
            names = sorted(
                name
                for name in names
                if re.fullmatch(r"Contents/section[0-9]+\.xml", name, re.IGNORECASE)
            )
        if not names:
            raise ValueError(f"Malformed {document_format} archive")
        paragraphs = []
        for name in names:
            paragraphs.extend(_xml_paragraphs(archive.read(name)))
        return paragraphs


def extract_hwp_paragraph_stream(stream, *, compressed):
    """Decode HWP BodyText paragraph records from one compressed or plain section stream."""
    if not isinstance(stream, (bytes, bytearray)):
        raise ValueError("Malformed HWP paragraph stream")
    try:
        data = zlib.decompress(bytes(stream), -15) if compressed else bytes(stream)
    except zlib.error:
        raise ValueError("Malformed HWP paragraph stream") from None
    paragraphs, chunks, position = [], [], 0
    while position < len(data):
        if len(data) - position < 4:
            raise ValueError("Malformed HWP paragraph stream")
        header = struct.unpack_from("<I", data, position)[0]
        position += 4
        tag, size = header & 0x3FF, header >> 20
        if size == 0xFFF:
            if len(data) - position < 4:
                raise ValueError("Malformed HWP paragraph stream")
            size = struct.unpack_from("<I", data, position)[0]
            position += 4
        if size > len(data) - position:
            raise ValueError("Malformed HWP paragraph stream")
        record = data[position : position + size]
        position += size
        if tag == HWP_PARA_HEADER:
            value = "".join(chunks).strip()
            if value:
                paragraphs.append(value)
            chunks = []
        elif tag == HWP_PARA_TEXT:
            try:
                text = record.decode("utf-16le")
            except UnicodeDecodeError:
                raise ValueError("Malformed HWP paragraph stream") from None
            chunks.append("".join(char for char in text if char >= " " or char in "\n\t"))
    value = "".join(chunks).strip()
    if value:
        paragraphs.append(value)
    return paragraphs


def _hwp_paragraphs(payload):
    if not olefile.isOleFile(io.BytesIO(payload)):
        raise ValueError("Malformed HWP document")
    with olefile.OleFileIO(io.BytesIO(payload)) as document:
        if not document.exists("FileHeader"):
            raise ValueError("Malformed HWP document")
        header = document.openstream("FileHeader").read()
        if len(header) < 40:
            raise ValueError("Malformed HWP document")
        compressed = bool(struct.unpack_from("<I", header, 36)[0] & 1)
        sections = sorted(
            "/".join(path)
            for path in document.listdir()
            if len(path) == 2
            and path[0].lower() == "bodytext"
            and path[1].lower().startswith("section")
        )
        if not sections:
            raise ValueError("Malformed HWP document")
        paragraphs = []
        for section in sections:
            paragraphs.extend(
                extract_hwp_paragraph_stream(
                    document.openstream(section).read(), compressed=compressed
                )
            )
        return paragraphs


def extract_reference_text(payload, name, *, max_chars):
    """Extract bounded text, reporting malformed and unsupported documents without parser errors."""
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 0:
        return _result("MALFORMED", error="Invalid extraction limit")
    if not isinstance(payload, (bytes, bytearray)):
        return _result("MALFORMED", error="Reference content must be bytes")
    document_format = detect_reference_format(name)
    if not document_format:
        return _result("UNSUPPORTED", error="Unsupported reference format")
    try:
        if document_format == "PDF":
            reader = PdfReader(io.BytesIO(payload))
            paragraphs = [page.extract_text() or "" for page in reader.pages]
        elif document_format in {"DOCX", "HWPX"}:
            paragraphs = _zip_xml(payload, document_format)
        else:
            paragraphs = _hwp_paragraphs(payload)
    except ValueError as error:
        message = str(error)
        if message.startswith("Malformed "):
            return _result("MALFORMED", error=message)
        return _result("MALFORMED", error=f"Malformed {document_format} document")
    except (ElementTree.ParseError, OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
        if document_format in {"DOCX", "HWPX"}:
            return _result("MALFORMED", error=f"Malformed {document_format} archive")
        return _result("MALFORMED", error=f"Malformed {document_format} document")
    except Exception:
        return _result("MALFORMED", error=f"Malformed {document_format} document")
    return _bounded_text(paragraphs, max_chars)
