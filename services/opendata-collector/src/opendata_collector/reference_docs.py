"""Select and extract bounded text from official portal reference-document attachments."""

import hashlib
import io
import json
import re
import struct
import threading
import zipfile
import zlib
from contextlib import contextmanager
from urllib.parse import urlencode
from xml.etree import ElementTree

import olefile
from pypdf import PdfReader, filters
from pypdf.errors import LimitReachedError

from .http import FetchError

BASE_URL = "https://www.data.go.kr"
DOWNLOAD_PATH = "/cmm/cmm/fileDownload.do"
SUPPORTED_FORMATS = {"pdf": "PDF", "docx": "DOCX", "hwp": "HWP", "hwpx": "HWPX"}
FILE_ID = re.compile(r"FILE_[A-Za-z0-9_]+$")
POSITIVE_DECIMAL = re.compile(r"[1-9][0-9]*$")
SAFE_DETAIL_ID = re.compile(r"[^\s/\\]+$")
HWP_SECTION = re.compile(r"Section([0-9]+)$")
HWP_SIGNATURE = b"HWP Document File" + b"\0" * 15
HWP_PARA_HEADER = 66
HWP_PARA_TEXT = 67

# Extraction is deliberately bounded before parser libraries receive attacker-controlled content.
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_PDF_PAGES = 500
MAX_PDF_PAGE_STREAM_BYTES = 8 * 1024 * 1024
MAX_ZIP_MEMBERS = 200
MAX_ZIP_TOTAL_BYTES = 64 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 16 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100
MAX_HWP_HEADER_BYTES = 1024
MAX_HWP_SECTIONS = 200
MAX_HWP_STREAM_BYTES = 16 * 1024 * 1024
MAX_HWP_DECOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_HWP_RECORD_BYTES = 4 * 1024 * 1024
MAX_HWP_COMPRESSION_RATIO = 100
READ_CHUNK_BYTES = 64 * 1024
PDF_FILTER_LIMITS = (
    "ZLIB_MAX_OUTPUT_LENGTH",
    "LZW_MAX_OUTPUT_LENGTH",
    "RUN_LENGTH_MAX_OUTPUT_LENGTH",
    "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH",
    "MAX_DECLARED_STREAM_LENGTH",
    "JBIG2_MAX_OUTPUT_LENGTH",
    "ZLIB_MAX_RECOVERY_INPUT_LENGTH",
    "FLATE_MAX_BUFFER_SIZE",
    "FLATE_MAX_COLUMNS",
    "FLATE_MAX_ROW_LENGTH",
)
_PDF_FILTER_LOCK = threading.RLock()


class _Malformed(ValueError):
    pass


class _Unsupported(ValueError):
    pass


class _TextAccumulator:
    def __init__(self, max_chars):
        self.max_chars = max_chars
        self.parts = []
        self.char_count = 0
        self.truncated = False

    @property
    def full(self):
        return self.truncated or self.char_count >= self.max_chars

    def add(self, value):
        if not value:
            return self.full
        prefix = "\n\n" if self.parts else ""
        combined = prefix + value
        remaining = self.max_chars - self.char_count
        if len(combined) > remaining:
            self.parts.append(combined[:remaining])
            self.char_count = self.max_chars
            self.truncated = True
        else:
            self.parts.append(combined)
            self.char_count += len(combined)
            if self.char_count == self.max_chars:
                self.truncated = True
        return self.full

    def result(self):
        return _result("TRUNCATED" if self.truncated else "EXTRACTED", "".join(self.parts))


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
    return (
        BASE_URL
        + DOWNLOAD_PATH
        + "?"
        + urlencode({"atchFileId": file_id, "fileDetailSn": file_detail_sn, "dataNm": name})
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


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _attribute(element, name):
    for key, value in element.attrib.items():
        if _local_name(key) == name:
            return value
    return None


def _limited_read(stream, limit):
    parts, total = [], 0
    while True:
        chunk = stream.read(min(READ_CHUNK_BYTES, limit - total + 1))
        if not chunk:
            return b"".join(parts)
        total += len(chunk)
        if total > limit:
            raise _Malformed("resource limit")
        parts.append(chunk)


def _zip_error(document_format):
    raise _Malformed(f"Malformed {document_format} archive")


def _validate_zip_info(infos, document_format):
    if len(infos) > MAX_ZIP_MEMBERS:
        _zip_error(document_format)
    total = 0
    for info in infos:
        path = info.filename
        if not path or path.startswith("/") or "\\" in path or ".." in path.split("/"):
            _zip_error(document_format)
        if info.flag_bits & 1 or info.file_size > MAX_ZIP_MEMBER_BYTES:
            _zip_error(document_format)
        if info.file_size and (
            info.file_size > max(1, info.compress_size) * MAX_ZIP_COMPRESSION_RATIO
        ):
            _zip_error(document_format)
        total += info.file_size
        if total > MAX_ZIP_TOTAL_BYTES:
            _zip_error(document_format)


class _BoundedZipMember:
    def __init__(self, archive, info, document_format, consumed):
        self.document_format, self.consumed = document_format, consumed
        self.size = 0
        try:
            self.stream = archive.open(info)
        except (OSError, RuntimeError, zipfile.BadZipFile):
            _zip_error(document_format)

    def read(self, size=-1):
        requested = READ_CHUNK_BYTES if size is None or size < 0 else min(size, READ_CHUNK_BYTES)
        try:
            content = self.stream.read(min(requested, MAX_ZIP_MEMBER_BYTES - self.size + 1))
        except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
            _zip_error(self.document_format)
        self.size += len(content)
        self.consumed[0] += len(content)
        if self.size > MAX_ZIP_MEMBER_BYTES or self.consumed[0] > MAX_ZIP_TOTAL_BYTES:
            _zip_error(self.document_format)
        return content

    def close(self):
        self.stream.close()


def _zip_member(archive, name, document_format, consumed):
    try:
        info = archive.getinfo(name)
    except KeyError:
        _zip_error(document_format)
    if info.flag_bits & 1:
        _zip_error(document_format)
    return _BoundedZipMember(archive, info, document_format, consumed)


def _zip_read(archive, name, document_format, consumed):
    member = _zip_member(archive, name, document_format, consumed)
    try:
        return _limited_read(member, MAX_ZIP_MEMBER_BYTES)
    except _Malformed:
        _zip_error(document_format)
    finally:
        member.close()


def _xml_root(content, document_format):
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError:
        _zip_error(document_format)


def _valid_docx(archive, consumed):
    names = {info.filename for info in archive.infolist()}
    required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
    if not required.issubset(names):
        _zip_error("DOCX")
    content_types = _xml_root(_zip_read(archive, "[Content_Types].xml", "DOCX", consumed), "DOCX")
    relationships = _xml_root(_zip_read(archive, "_rels/.rels", "DOCX", consumed), "DOCX")
    if (
        _local_name(content_types.tag) != "Types"
        or _local_name(relationships.tag) != "Relationships"
    ):
        _zip_error("DOCX")
    main_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    has_document_type = any(
        _local_name(node.tag) == "Override"
        and _attribute(node, "PartName") == "/word/document.xml"
        and _attribute(node, "ContentType") == main_type
        for node in content_types
    )
    has_document_relation = any(
        _local_name(node.tag) == "Relationship"
        and _attribute(node, "Type")
        == "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
        and _attribute(node, "Target") in {"word/document.xml", "/word/document.xml"}
        for node in relationships
    )
    if not has_document_type or not has_document_relation:
        _zip_error("DOCX")


def _valid_hwpx(archive, consumed):
    names = {info.filename for info in archive.infolist()}
    required = {"mimetype", "META-INF/manifest.xml", "Contents/content.hpf"}
    if not required.issubset(names):
        _zip_error("HWPX")
    if _zip_read(archive, "mimetype", "HWPX", consumed).strip() != b"application/hwp+zip":
        _zip_error("HWPX")
    manifest = _xml_root(_zip_read(archive, "META-INF/manifest.xml", "HWPX", consumed), "HWPX")
    container = _xml_root(_zip_read(archive, "Contents/content.hpf", "HWPX", consumed), "HWPX")
    if _local_name(manifest.tag) != "manifest" or _local_name(container.tag) != "package":
        _zip_error("HWPX")
    section_names = (
        name for name in names if re.fullmatch(r"Contents/section[0-9]+\.xml", name, re.IGNORECASE)
    )
    sections = sorted(section_names, key=lambda name: int(re.search(r"[0-9]+", name).group()))
    if not sections:
        _zip_error("HWPX")
    manifest_sections = {
        _attribute(node, "full-path")
        for node in manifest.iter()
        if _local_name(node.tag) == "file-entry"
    }
    if not set(sections).issubset(manifest_sections):
        _zip_error("HWPX")
    return sections


def _xml_into(content, accumulator, document_format):
    try:
        source = content if hasattr(content, "read") else io.BytesIO(content)
        parser = ElementTree.iterparse(source, events=("end",))
        for _, element in parser:
            if _local_name(element.tag) != "p":
                continue
            chunks = []
            for node in element.iter():
                name = _local_name(node.tag)
                if name in {"t", "text"} and node.text:
                    chunks.append(node.text)
                elif name in {"br", "lineBreak"}:
                    chunks.append("\n")
            if accumulator.add("".join(chunks).strip()):
                return
            element.clear()
    except ElementTree.ParseError:
        _zip_error(document_format)


def _zip_into(payload, document_format, accumulator):
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            _validate_zip_info(infos, document_format)
            consumed = [0]
            if document_format == "DOCX":
                _valid_docx(archive, consumed)
                sections = ["word/document.xml"]
            else:
                sections = _valid_hwpx(archive, consumed)
            for name in sections:
                member = _zip_member(archive, name, document_format, consumed)
                try:
                    _xml_into(member, accumulator, document_format)
                finally:
                    member.close()
                if accumulator.full:
                    return
    except _Malformed:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
        _zip_error(document_format)


def _decompress_hwp(stream):
    decompressor = zlib.decompressobj(-15)
    parts, compressed_size, decompressed_size = [], 0, 0
    while True:
        chunk = stream.read(min(READ_CHUNK_BYTES, MAX_HWP_STREAM_BYTES - compressed_size + 1))
        if not chunk:
            break
        compressed_size += len(chunk)
        if compressed_size > MAX_HWP_STREAM_BYTES:
            raise _Malformed("Malformed HWP document")
        try:
            output = decompressor.decompress(
                chunk, MAX_HWP_DECOMPRESSED_BYTES - decompressed_size + 1
            )
        except zlib.error:
            raise _Malformed("Malformed HWP document") from None
        decompressed_size += len(output)
        if decompressed_size > MAX_HWP_DECOMPRESSED_BYTES:
            raise _Malformed("Malformed HWP document")
        if decompressed_size > max(1, compressed_size) * MAX_HWP_COMPRESSION_RATIO:
            raise _Malformed("Malformed HWP document")
        parts.append(output)
        if decompressor.unconsumed_tail:
            raise _Malformed("Malformed HWP document")
    try:
        output = decompressor.flush(MAX_HWP_DECOMPRESSED_BYTES - decompressed_size + 1)
    except zlib.error:
        raise _Malformed("Malformed HWP document") from None
    decompressed_size += len(output)
    if not decompressor.eof or decompressed_size > MAX_HWP_DECOMPRESSED_BYTES:
        raise _Malformed("Malformed HWP document")
    parts.append(output)
    return b"".join(parts)


def _hwp_stream_data(stream, compressed):
    if compressed:
        return _decompress_hwp(stream)
    try:
        return _limited_read(stream, MAX_HWP_STREAM_BYTES)
    except (_Malformed, OSError):
        raise _Malformed("Malformed HWP document") from None


def _iter_hwp_paragraphs(data):
    chunks, position = [], 0
    while position < len(data):
        if len(data) - position < 4:
            raise _Malformed("Malformed HWP document")
        header = struct.unpack_from("<I", data, position)[0]
        position += 4
        tag, size = header & 0x3FF, header >> 20
        if size == 0xFFF:
            if len(data) - position < 4:
                raise _Malformed("Malformed HWP document")
            size = struct.unpack_from("<I", data, position)[0]
            position += 4
        if size > MAX_HWP_RECORD_BYTES or size > len(data) - position:
            raise _Malformed("Malformed HWP document")
        record = data[position : position + size]
        position += size
        if tag == HWP_PARA_HEADER:
            value = "".join(chunks).strip()
            if value:
                yield value
            chunks = []
        elif tag == HWP_PARA_TEXT:
            try:
                text = record.decode("utf-16le")
            except UnicodeDecodeError:
                raise _Malformed("Malformed HWP document") from None
            chunks.append("".join(char for char in text if char >= " " or char in "\n\t"))
    value = "".join(chunks).strip()
    if value:
        yield value


class _HwpAccumulatorParser:
    """Parse HWP records incrementally and stop as soon as the text budget is full."""

    def __init__(self, accumulator):
        self.accumulator = accumulator
        self.buffer = bytearray()
        self.chunks = []
        self.chunk_chars = 0

    def _emit_paragraph(self):
        if not self.chunks:
            return False
        value = "".join(self.chunks).strip()
        self.chunks, self.chunk_chars = [], 0
        return self.accumulator.add(value)

    def _add_text(self, record):
        try:
            value = record.decode("utf-16le")
        except UnicodeDecodeError:
            raise _Malformed("Malformed HWP document") from None
        value = "".join(char for char in value if char >= " " or char in "\n\t")
        allowed = self.accumulator.max_chars + 1 - self.chunk_chars
        if len(value) > allowed:
            self.chunks.append(value[:allowed])
            self.chunk_chars += allowed
            self._emit_paragraph()
            return True
        self.chunks.append(value)
        self.chunk_chars += len(value)
        return False

    def feed(self, data):
        self.buffer.extend(data)
        while True:
            if len(self.buffer) < 4:
                return False
            header = struct.unpack_from("<I", self.buffer)[0]
            tag, size, header_size = header & 0x3FF, header >> 20, 4
            if size == 0xFFF:
                if len(self.buffer) < 8:
                    return False
                size = struct.unpack_from("<I", self.buffer, 4)[0]
                header_size = 8
            if size > MAX_HWP_RECORD_BYTES:
                raise _Malformed("Malformed HWP document")
            record_size = header_size + size
            if len(self.buffer) < record_size:
                return False
            record = bytes(self.buffer[header_size:record_size])
            del self.buffer[:record_size]
            if tag == HWP_PARA_HEADER:
                if self._emit_paragraph():
                    return True
            elif tag == HWP_PARA_TEXT and self._add_text(record):
                return True

    def finish(self):
        if self.buffer:
            raise _Malformed("Malformed HWP document")
        return self._emit_paragraph()


def _hwp_stream_into(stream, compressed, accumulator):
    parser = _HwpAccumulatorParser(accumulator)
    compressed_size = decompressed_size = 0
    decompressor = zlib.decompressobj(-15) if compressed else None
    while True:
        chunk = stream.read(min(READ_CHUNK_BYTES, MAX_HWP_STREAM_BYTES - compressed_size + 1))
        if not chunk:
            break
        compressed_size += len(chunk)
        if compressed_size > MAX_HWP_STREAM_BYTES:
            raise _Malformed("Malformed HWP document")
        try:
            output = (
                decompressor.decompress(chunk, MAX_HWP_DECOMPRESSED_BYTES - decompressed_size + 1)
                if decompressor
                else chunk
            )
        except zlib.error:
            raise _Malformed("Malformed HWP document") from None
        decompressed_size += len(output)
        if decompressed_size > MAX_HWP_DECOMPRESSED_BYTES or (
            compressed and decompressed_size > max(1, compressed_size) * MAX_HWP_COMPRESSION_RATIO
        ):
            raise _Malformed("Malformed HWP document")
        if parser.feed(output):
            return
        if compressed and decompressor.unconsumed_tail:
            raise _Malformed("Malformed HWP document")
    if compressed:
        try:
            output = decompressor.flush(MAX_HWP_DECOMPRESSED_BYTES - decompressed_size + 1)
        except zlib.error:
            raise _Malformed("Malformed HWP document") from None
        decompressed_size += len(output)
        if not decompressor.eof or decompressed_size > MAX_HWP_DECOMPRESSED_BYTES:
            raise _Malformed("Malformed HWP document")
        if parser.feed(output):
            return
    parser.finish()


def extract_hwp_paragraph_stream(stream, *, compressed):
    """Decode one bounded HWP BodyText paragraph stream for isolated parser tests."""
    if not isinstance(stream, (bytes, bytearray)):
        raise ValueError("Malformed HWP paragraph stream")
    try:
        data = _hwp_stream_data(io.BytesIO(bytes(stream)), compressed)
        return list(_iter_hwp_paragraphs(data))
    except _Malformed:
        raise ValueError("Malformed HWP paragraph stream") from None


def _hwp_into(payload, accumulator):
    if not olefile.isOleFile(io.BytesIO(payload)):
        raise _Malformed("Malformed HWP document")
    with olefile.OleFileIO(io.BytesIO(payload)) as document:
        if not document.exists("FileHeader"):
            raise _Malformed("Malformed HWP document")
        try:
            header = _limited_read(document.openstream("FileHeader"), MAX_HWP_HEADER_BYTES)
        except (_Malformed, OSError):
            raise _Malformed("Malformed HWP document") from None
        if len(header) < 40 or header[:32] != HWP_SIGNATURE:
            raise _Malformed("Malformed HWP document")
        properties = struct.unpack_from("<I", header, 36)[0]
        if properties & 2:
            raise _Unsupported("Password-protected HWP document")
        if properties & ~1:
            raise _Unsupported("Unsupported protected HWP document")
        sections = []
        for path in document.listdir():
            if len(path) != 2 or path[0] != "BodyText":
                continue
            match = HWP_SECTION.fullmatch(path[1])
            if match:
                sections.append((int(match.group(1)), "/".join(path)))
        if not sections or len(sections) > MAX_HWP_SECTIONS:
            raise _Malformed("Malformed HWP document")
        for _, section in sorted(sections):
            _hwp_stream_into(document.openstream(section), bool(properties & 1), accumulator)
            if accumulator.full:
                return


@contextmanager
def _pypdf_page_limits(limit):
    """Temporarily lower pypdf's module-global decoders under one module lock."""
    with _PDF_FILTER_LOCK:
        original = {name: getattr(filters, name) for name in PDF_FILTER_LIMITS}
        try:
            for name in PDF_FILTER_LIMITS:
                setattr(filters, name, limit)
            yield
        finally:
            for name, value in original.items():
                setattr(filters, name, value)


def _pdf_streams(page):
    if not hasattr(page, "get"):
        return []
    contents = page.get("/Contents")
    if contents is None:
        return []
    if hasattr(contents, "get_object"):
        contents = contents.get_object()
    values = contents if isinstance(contents, (list, tuple)) else [contents]
    streams = []
    for value in values:
        stream = value.get_object() if hasattr(value, "get_object") else value
        if not hasattr(stream, "get"):
            raise _Malformed("Malformed PDF document")
        streams.append(stream)
    return streams


def _pdf_stream_size(stream):
    raw = getattr(stream, "_data", None)
    if isinstance(raw, (bytes, bytearray)) and len(raw) > MAX_PDF_PAGE_STREAM_BYTES:
        raise _Malformed("PDF page stream exceeds extraction limit")
    declared = stream.get("/Length")
    if hasattr(declared, "get_object"):
        declared = declared.get_object()
    if isinstance(declared, int) and declared > MAX_PDF_PAGE_STREAM_BYTES:
        raise _Malformed("PDF page stream exceeds extraction limit")


def _pdf_into(payload, accumulator):
    try:
        with _pypdf_page_limits(MAX_PDF_PAGE_STREAM_BYTES):
            reader = PdfReader(io.BytesIO(payload))
            if reader.is_encrypted:
                raise _Unsupported("Password-protected PDF document")
            for number, page in enumerate(reader.pages, 1):
                if number > MAX_PDF_PAGES:
                    raise _Malformed("Malformed PDF document")
                for stream in _pdf_streams(page):
                    _pdf_stream_size(stream)
                if accumulator.add(page.extract_text() or ""):
                    return
    except LimitReachedError:
        raise _Malformed("PDF page stream exceeds extraction limit") from None


REFERENCE_MAX_BYTES = 32 * 1024 * 1024
REFERENCE_MAX_CHARS = 1_000_000


class ReferencePipeline:
    """Download and extract official registered reference attachments independently."""

    def __init__(self, store, http):
        self.store, self.http = store, http

    def run(
        self, *, types=None, limit=None, max_bytes=None, max_chars=None, force=None, resume=None
    ):
        self.store.initialize()
        if resume:
            run = self.store.get_run(resume)
            if run.get("status") == "completed":
                raise ValueError("Completed reference run cannot be resumed")
        else:
            selected_types = list(dict.fromkeys(types or ["API"]))
            if not selected_types or any(not isinstance(kind, str) for kind in selected_types):
                raise ValueError("Invalid reference catalog types")
            max_bytes = REFERENCE_MAX_BYTES if max_bytes is None else max_bytes
            max_chars = REFERENCE_MAX_CHARS if max_chars is None else max_chars
            if limit is not None and (not isinstance(limit, int) or limit < 1):
                raise ValueError("Reference limit must be positive")
            if (
                not isinstance(max_bytes, int)
                or max_bytes < 1
                or not isinstance(max_chars, int)
                or max_chars < 1
            ):
                raise ValueError("Invalid reference limits")
            run = self.store.start_run(selected_types, limit, max_bytes, max_chars, bool(force))
        # Saved configuration is authoritative for every resume.
        selected_types, limit, max_bytes, max_chars, force = (
            run["types"],
            run.get("limit"),
            run["max_bytes"],
            run["max_chars"],
            run["force"],
        )
        if not run.get("selection_complete"):
            selected = 0
            selection_ok = True
            try:
                for catalog, detail, error in self.store.catalogs(selected_types):
                    if error:
                        self.store.catalog_error(run["_id"], catalog["_id"], error)
                        selection_ok = False
                        continue
                    self.store.catalog_loaded(run["_id"], catalog["_id"])
                    item = {**catalog, "catalog_id": catalog["_id"]}
                    for descriptor in select_reference_attachments(item, detail):
                        if limit is not None and selected >= limit:
                            break
                        self.store.add_item(run["_id"], descriptor, force=force)
                        selected += 1
                    if limit is not None and selected >= limit:
                        break
            except Exception:
                selection_ok = False
            self.store.selection_complete(run["_id"], selection_ok)
            run = self.store.get_run(run["_id"])
        if run.get("selection_complete"):
            for item in self.store.pending(run["_id"]):
                descriptor = self.store.current_descriptor(item["descriptor"])
                if descriptor is None:
                    self.store.stale_document(run["_id"], item["descriptor"])
                    continue
                try:
                    resource = self.http.get(descriptor["url"], kind="reference_document")
                    if len(resource.content) > max_bytes:
                        self.store.fail_document(
                            run["_id"], descriptor, "Reference download exceeds size limit"
                        )
                        continue
                    extracted = extract_reference_text(
                        resource.content, descriptor["name"], max_chars=max_chars
                    )
                    self.store.save_document(run["_id"], descriptor, resource, extracted)
                except FetchError as error:
                    self.store.fail_document(run["_id"], descriptor, str(error))
                except Exception:
                    self.store.fail_document(run["_id"], descriptor, "Reference processing failed")
        return self.store.report(run["_id"], persist=True)


def extract_reference_text(payload, name, *, max_chars):
    """Extract bounded text with explicit, safe statuses for unsupported or malformed inputs."""
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
        return _result("MALFORMED", error="Invalid extraction limit")
    if not isinstance(payload, (bytes, bytearray)):
        return _result("MALFORMED", error="Reference content must be bytes")
    if len(payload) > MAX_INPUT_BYTES:
        return _result("MALFORMED", error="Reference content exceeds extraction limit")
    document_format = detect_reference_format(name)
    if not document_format:
        return _result("UNSUPPORTED", error="Unsupported reference format")
    accumulator = _TextAccumulator(max_chars)
    try:
        if document_format == "PDF":
            _pdf_into(payload, accumulator)
        elif document_format in {"DOCX", "HWPX"}:
            _zip_into(payload, document_format, accumulator)
        else:
            _hwp_into(payload, accumulator)
    except _Unsupported as error:
        return _result("UNSUPPORTED", error=str(error))
    except _Malformed as error:
        return _result("MALFORMED", error=str(error))
    except Exception:
        if document_format in {"DOCX", "HWPX"}:
            return _result("MALFORMED", error=f"Malformed {document_format} archive")
        return _result("MALFORMED", error=f"Malformed {document_format} document")
    return accumulator.result()
