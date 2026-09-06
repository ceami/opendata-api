import io
import struct
import zipfile
import zlib

from pypdf import filters

import opendata_collector.reference_docs as reference_docs
from opendata_collector.reference_docs import (
    extract_hwp_paragraph_stream,
    extract_reference_text,
    reference_attachment_identity,
    select_reference_attachments,
)


def attachment(name, **values):
    result = {"name": name, "file_id": "FILE_000000000001", "file_detail_sn": "2"}
    result.update(values)
    return result


def detail(*attachments):
    return {
        "hidden_fields": {"publicDataPk": "15129394", "publicDataDetailPk": "uddi:guide"},
        "attachments": list(attachments),
    }


def test_selects_registered_official_reference_attachment_and_builds_download_url():
    selected = select_reference_attachments(
        {"catalog_id": "API:15129394", "data_type": "API", "list_id": 15129394},
        detail(attachment("API guide.docx")),
    )

    assert selected == [
        {
            "catalog_id": "API:15129394",
            "name": "API guide.docx",
            "format": "DOCX",
            "public_data_pk": "15129394",
            "public_data_detail_pk": "uddi:guide",
            "file_id": "FILE_000000000001",
            "file_detail_sn": "2",
            "url": "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000000001&fileDetailSn=2&dataNm=API+guide.docx",
            "attachment_id": reference_attachment_identity(
                "API:15129394", "15129394", "uddi:guide", "FILE_000000000001", "2"
            ),
        }
    ]


def test_selection_accepts_only_supported_registered_attachments():
    selected = select_reference_attachments(
        {"catalog_id": "API:15129394", "data_type": "API", "list_id": 15129394},
        detail(
            attachment("guide.pdf"),
            attachment("dataset.csv", file_id="FILE_000000000002"),
            attachment("external.hwp", file_id="FILE_000000000003", url="https://example.test/x"),
            attachment("bad.hwpx", file_id="bad", file_detail_sn="0"),
        ),
    )

    assert [(item["name"], item["format"]) for item in selected] == [("guide.pdf", "PDF")]


def test_selection_rejects_attachment_that_disagrees_with_catalog_identity():
    selected = select_reference_attachments(
        {"catalog_id": "API:15129394", "data_type": "API", "list_id": 15129394},
        detail(
            attachment(
                "guide.hwp",
                arguments=["15129395", "uddi:guide", "FILE_000000000001", "2", "hwp"],
            )
        ),
    )

    assert selected == []


def test_attachment_identity_is_stable_and_changes_for_a_new_file_version():
    original = reference_attachment_identity(
        "API:15129394", "15129394", "uddi:guide", "FILE_000000000001", "2"
    )

    assert original == reference_attachment_identity(
        "API:15129394", "15129394", "uddi:guide", "FILE_000000000001", "2"
    )
    assert original != reference_attachment_identity(
        "API:15129394", "15129394", "uddi:guide", "FILE_000000000001", "3"
    )


def test_extracts_pdf_text_with_page_boundaries_and_character_limit():
    # A tiny generated PDF with two uncompressed text streams; no external fixture is used.
    streams = [b"BT /F1 12 Tf (first page) Tj ET", b"BT /F1 12 Tf (second page) Tj ET"]
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Count 2/Kids[3 0 R 5 0 R]>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 100 100]/Resources<</Font<</F1 7 0 R>>>>/Contents 4 0 R>>",
        b"<</Length %d>>\nstream\n%s\nendstream" % (len(streams[0]), streams[0]),
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 100 100]/Resources<</Font<</F1 7 0 R>>>>/Contents 6 0 R>>",
        b"<</Length %d>>\nstream\n%s\nendstream" % (len(streams[1]), streams[1]),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    pdf, offsets = b"%PDF-1.4\n", []
    for number, content in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n%s\nendobj\n" % (number, content)
    xref = len(pdf)
    pdf += b"xref\n0 8\n0000000000 65535 f \n"
    pdf += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    pdf += b"trailer\n<</Size 8/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % xref

    result = extract_reference_text(pdf, "guide.pdf", max_chars=12)

    assert result == {
        "status": "TRUNCATED",
        "text": "first page\n\n",
        "char_count": 12,
        "error": None,
    }


def _zip(entries):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return result.getvalue()


def test_extracts_docx_and_hwpx_paragraphs():
    docx = _zip(
        {
            "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            "_rels/.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
            "word/document.xml": b'<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>one</w:t></w:r></w:p><w:p><w:r><w:t>two</w:t></w:r></w:p></w:body></w:document>',
        }
    )
    hwpx = _zip(
        {
            "mimetype": b"application/hwp+zip",
            "META-INF/manifest.xml": b'<manifest:manifest xmlns:manifest="manifest"><manifest:file-entry manifest:full-path="Contents/section0.xml"/></manifest:manifest>',
            "Contents/content.hpf": b"<package/>",
            "Contents/section0.xml": b'<hp:section xmlns:hp="hp"><hp:p><hp:run><hp:t>hana</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>dul</hp:t></hp:run></hp:p></hp:section>',
        }
    )

    assert extract_reference_text(docx, "guide.docx", max_chars=100)["text"] == "one\n\ntwo"
    assert extract_reference_text(hwpx, "guide.hwpx", max_chars=100)["text"] == "hana\n\ndul"


def test_malformed_archive_and_unsupported_format_return_explicit_statuses():
    assert extract_reference_text(b"not a zip", "guide.docx", max_chars=10) == {
        "status": "MALFORMED",
        "text": "",
        "char_count": 0,
        "error": "Malformed DOCX archive",
    }
    assert extract_reference_text(b"plain", "guide.txt", max_chars=10) == {
        "status": "UNSUPPORTED",
        "text": "",
        "char_count": 0,
        "error": "Unsupported reference format",
    }


def _record(tag, text=b""):
    return struct.pack("<I", tag | (len(text) << 20)) + text


def test_extracts_compressed_and_uncompressed_hwp_paragraph_streams():
    stream = b"".join(
        [
            _record(66),
            _record(67, "first".encode("utf-16le")),
            _record(66),
            _record(67, "second".encode("utf-16le")),
        ]
    )

    import zlib

    compressed = zlib.compressobj(wbits=-15)
    compressed_stream = compressed.compress(stream) + compressed.flush()
    assert extract_hwp_paragraph_stream(stream, compressed=False) == ["first", "second"]
    assert extract_hwp_paragraph_stream(compressed_stream, compressed=True) == ["first", "second"]


def test_malformed_hwp_stream_returns_explicit_malformed_result():
    result = extract_reference_text(b"not an ole file", "guide.hwp", max_chars=100)

    assert result["status"] == "MALFORMED"
    assert result["error"] == "Malformed HWP document"



def _valid_docx(document=b'<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>text</w:t></w:r></w:p></w:body></w:document>'):
    return _zip(
        {
            "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            "_rels/.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
            "word/document.xml": document,
        }
    )


def test_rejects_generic_zip_payloads_that_only_mimic_docx_or_hwpx_members():
    assert extract_reference_text(
        _zip({"word/document.xml": b"<document><p>not a DOCX package</p></document>"}),
        "guide.docx", max_chars=100,
    )["status"] == "MALFORMED"
    assert extract_reference_text(
        _zip({"Contents/section0.xml": b"<section><p>not a HWPX package</p></section>"}),
        "guide.hwpx", max_chars=100,
    )["status"] == "MALFORMED"


def test_rejects_non_positive_character_limits():
    for limit in (0, -1, True):
        result = extract_reference_text(_valid_docx(), "guide.docx", max_chars=limit)
        assert result == {"status": "MALFORMED", "text": "", "char_count": 0, "error": "Invalid extraction limit"}


def test_rejects_zip_member_limit_and_suspicious_compression_ratio(monkeypatch):
    monkeypatch.setattr(reference_docs, "MAX_ZIP_MEMBER_BYTES", 4)
    result = extract_reference_text(_valid_docx(b"<document><p>large</p></document>"), "guide.docx", max_chars=100)
    assert result == {"status": "MALFORMED", "text": "", "char_count": 0, "error": "Malformed DOCX archive"}
    monkeypatch.setattr(reference_docs, "MAX_ZIP_MEMBER_BYTES", 1024 * 1024)
    monkeypatch.setattr(reference_docs, "MAX_ZIP_COMPRESSION_RATIO", 1)
    result = extract_reference_text(_valid_docx(b"x" * 4096), "guide.docx", max_chars=100)
    assert result["status"] == "MALFORMED"
    assert result["error"] == "Malformed DOCX archive"


def test_pdf_stops_after_output_budget_and_rejects_excess_pages(monkeypatch):
    calls = []

    class Page:
        def __init__(self, value): self.value = value
        def extract_text(self):
            calls.append(self.value)
            if self.value == "later":
                raise AssertionError("output cap did not stop PDF extraction")
            return self.value

    class Reader:
        is_encrypted = False
        pages = [Page("one"), Page("later")]
        def __init__(self, *_): pass

    monkeypatch.setattr(reference_docs, "PdfReader", Reader)
    assert extract_reference_text(b"small", "guide.pdf", max_chars=3)["status"] == "TRUNCATED"
    assert calls == ["one"]
    monkeypatch.setattr(reference_docs, "MAX_PDF_PAGES", 1)
    result = extract_reference_text(b"small", "guide.pdf", max_chars=100)
    assert result["status"] == "MALFORMED"
    assert result["error"] == "Malformed PDF document"


class _Stream(io.BytesIO):
    pass


class _FakeOle:
    def __init__(self, streams): self.streams = streams
    def __enter__(self): return self
    def __exit__(self, *_): return None
    def exists(self, name): return name in self.streams
    def openstream(self, name): return _Stream(self.streams[name])
    def listdir(self): return [name.split("/") for name in self.streams]


def _hwp_header(*, compressed=False, encrypted=False, valid=True):
    signature = b"HWP Document File" + b"\0" * 15 if valid else b"not an HWP header" + b"\0" * 15
    flags = (1 if compressed else 0) | (2 if encrypted else 0)
    return signature + b"\0" * 4 + struct.pack("<I", flags) + b"\0" * 216


def _fake_hwp(monkeypatch, streams):
    monkeypatch.setattr(reference_docs.olefile, "isOleFile", lambda *_: True)
    monkeypatch.setattr(reference_docs.olefile, "OleFileIO", lambda *_: _FakeOle(streams))


def test_hwp_public_extraction_validates_signature_encryption_and_numeric_sections(monkeypatch):
    raw_two = _record(66) + _record(67, "two".encode("utf-16le"))
    raw_ten = _record(66) + _record(67, "ten".encode("utf-16le"))
    _fake_hwp(monkeypatch, {"FileHeader": _hwp_header(), "BodyText/Section10": raw_ten, "BodyText/Section2": raw_two})
    result = extract_reference_text(b"ole", "guide.hwp", max_chars=100)
    assert result["text"] == "two\n\nten"
    _fake_hwp(monkeypatch, {"FileHeader": _hwp_header(valid=False), "BodyText/Section0": raw_two})
    assert extract_reference_text(b"ole", "guide.hwp", max_chars=100) == {"status": "MALFORMED", "text": "", "char_count": 0, "error": "Malformed HWP document"}
    _fake_hwp(monkeypatch, {"FileHeader": _hwp_header(encrypted=True), "BodyText/Section0": raw_two})
    assert extract_reference_text(b"ole", "guide.hwp", max_chars=100) == {"status": "UNSUPPORTED", "text": "", "char_count": 0, "error": "Password-protected HWP document"}


def test_hwp_public_extraction_supports_compressed_section_and_ignores_nonstandard_sections(monkeypatch):
    import zlib
    raw = _record(66) + _record(67, "compressed".encode("utf-16le"))
    compressor = zlib.compressobj(wbits=-15)
    packed = compressor.compress(raw) + compressor.flush()
    _fake_hwp(monkeypatch, {"FileHeader": _hwp_header(compressed=True), "BodyText/Section0": packed, "BodyText/SectionNotes": raw})
    result = extract_reference_text(b"ole", "guide.hwp", max_chars=100)
    assert result["status"] == "EXTRACTED"
    assert result["text"] == "compressed"



def test_rejects_encrypted_zip_member_before_reading_it():
    payload = bytearray(_valid_docx())
    local = payload.find(b"PK\x03\x04")
    central = payload.find(b"PK\x01\x02")
    assert local >= 0 and central >= 0
    payload[local + 6] |= 1
    payload[central + 8] |= 1
    result = extract_reference_text(bytes(payload), "guide.docx", max_chars=100)
    assert result == {
        "status": "MALFORMED",
        "text": "",
        "char_count": 0,
        "error": "Malformed DOCX archive",
    }



def _compressed_pdf(content):
    stream = zlib.compress(content)
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Count 1/Kids[3 0 R]>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 100 100]/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>",
        b"<</Length %d/Filter/FlateDecode>>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    payload, offsets = b"%PDF-1.4\n", []
    for number, content in enumerate(objects, 1):
        offsets.append(len(payload))
        payload += b"%d 0 obj\n%s\nendobj\n" % (number, content)
    xref = len(payload)
    payload += b"xref\n0 6\n0000000000 65535 f \n"
    payload += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    return payload + b"trailer\n<</Size 6/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % xref


def test_pdf_decode_policy_rejects_expansion_and_restores_pypdf_globals(monkeypatch):
    content = b"BT /F1 12 Tf (" + b"a" * 512 + b") Tj ET"
    payload = _compressed_pdf(content)
    assert len(zlib.compress(content)) < 64 < len(content)
    monkeypatch.setattr(reference_docs, "MAX_PDF_PAGE_STREAM_BYTES", 64, raising=False)
    names = (
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
    original = {name: getattr(filters, name) for name in names}

    result = extract_reference_text(payload, "guide.pdf", max_chars=1000)

    assert result == {
        "status": "MALFORMED",
        "text": "",
        "char_count": 0,
        "error": "PDF page stream exceeds extraction limit",
    }
    assert {name: getattr(filters, name) for name in names} == original



def test_pdf_policy_is_active_during_reader_construction_and_content_resolution(monkeypatch):
    limit = 73
    observations = []

    def observe(stage):
        observations.append((stage, {name: getattr(filters, name) for name in reference_docs.PDF_FILTER_LIMITS}))

    class Page:
        def get(self, key):
            assert key == "/Contents"
            observe("contents")
            return None

        def extract_text(self):
            observe("text")
            return "safe"

    class Reader:
        is_encrypted = False
        pages = [Page()]

        def __init__(self, *_):
            observe("reader")

    original = {name: getattr(filters, name) for name in reference_docs.PDF_FILTER_LIMITS}
    monkeypatch.setattr(reference_docs, "MAX_PDF_PAGE_STREAM_BYTES", limit)
    monkeypatch.setattr(reference_docs, "PdfReader", Reader)

    assert extract_reference_text(b"small", "guide.pdf", max_chars=100)["text"] == "safe"
    assert [stage for stage, _ in observations] == ["reader", "contents", "text"]
    assert all(values == {name: limit for name in reference_docs.PDF_FILTER_LIMITS} for _, values in observations)
    assert {name: getattr(filters, name) for name in reference_docs.PDF_FILTER_LIMITS} == original
