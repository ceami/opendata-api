import gzip
import hashlib
import io
import json
import struct
import zipfile
import zlib

import mongomock
from mongomock.gridfs import enable_gridfs_integration
from pypdf import filters

import opendata_collector.reference_docs as reference_docs
from opendata_collector.http import FetchError, Resource
from opendata_collector.reference_docs import (
    ReferencePipeline,
    extract_hwp_paragraph_stream,
    extract_reference_text,
    reference_attachment_identity,
    select_reference_attachments,
)
from opendata_collector.store import MongoStore, ReferenceStore

enable_gridfs_integration()


def attachment(name, **values):
    result = {"name": name, "file_id": "FILE_000000000001", "file_detail_sn": "2"}
    result.update(values)
    return result


def detail(*attachments):
    return {
        "hidden_fields": {"publicDataPk": "15129394", "publicDataDetailPk": "uddi:guide"},
        "attachments": list(attachments),
    }


def reference_store_with_catalogs(*, api=True, file=True):
    db = mongomock.MongoClient(tz_aware=True).reference_test
    raw = MongoStore(db)
    for kind, include in (("API", api), ("FILE", file)):
        if not include:
            continue
        number = 15129394 if kind == "API" else 15129395
        payload = detail(attachment(f"{kind} guide.docx"))
        if kind == "FILE":
            payload["hidden_fields"]["publicDataPk"] = str(number)
        db.portal_catalog.insert_one(
            {
                "_id": f"{kind}:{number}",
                "data_type": kind,
                "list_id": number,
                "is_active": True,
                "detail_status": "completed",
                "parsed_detail_ref": raw.save_raw(json.dumps(payload).encode()),
            }
        )
    return ReferenceStore(db)


class ReferenceHTTP:
    def __init__(self, payload=b"document"):
        self.payload = payload
        self.calls = []
        self.fail = set()

    def get(self, url, *, kind):
        self.calls.append((url, kind))
        if url in self.fail:
            raise FetchError("temporary attachment failure")
        return Resource(url, self.payload, "application/octet-stream", None, kind)


def test_reference_pipeline_selects_active_api_descriptors_and_persists_content_hashes(monkeypatch):
    store = reference_store_with_catalogs()
    http = ReferenceHTTP(b"source document")
    monkeypatch.setattr(
        reference_docs,
        "extract_reference_text",
        lambda payload, name, *, max_chars: {
            "status": "EXTRACTED",
            "text": "extracted text",
            "char_count": 14,
            "error": None,
        },
    )

    report = ReferencePipeline(store, http).run(types=["API"], max_bytes=17, max_chars=100)

    assert report["status"] == "completed"
    assert report["selected"] == report["completed"] == 1
    assert len(http.calls) == 1
    resource = store.db.portal_resources.find_one({"kind": "reference_document"})
    assert resource["catalog_id"] == "API:15129394"
    assert resource["document_sha256"] == hashlib.sha256(b"source document").hexdigest()
    assert resource["text_sha256"] == hashlib.sha256(b"extracted text").hexdigest()
    assert gzip.decompress(store.raw.get(resource["raw_id"]).read()) == b"source document"
    assert gzip.decompress(store.raw.get(resource["text_raw_id"]).read()) == b"extracted text"
    assert resource["extraction_status"] == "EXTRACTED"
    assert resource["char_count"] == 14


def test_reference_pipeline_skips_completed_descriptors_resumes_failures_and_force_refreshes(
    monkeypatch,
):
    store = reference_store_with_catalogs(file=False)
    http = ReferenceHTTP()
    monkeypatch.setattr(
        reference_docs,
        "extract_reference_text",
        lambda payload, name, *, max_chars: {
            "status": "EXTRACTED",
            "text": "ok",
            "char_count": 2,
            "error": None,
        },
    )
    first = ReferencePipeline(store, http).run(types=["API"], max_bytes=32, max_chars=10)
    second = ReferencePipeline(store, http).run(types=["API"], max_bytes=32, max_chars=10)
    forced = ReferencePipeline(store, http).run(
        types=["API"], max_bytes=32, max_chars=10, force=True
    )

    assert first["completed"] == 1
    assert second["skipped"] == 1
    assert forced["completed"] == 1
    assert len(http.calls) == 2

    retry_store = reference_store_with_catalogs(file=False)
    retry_http = ReferenceHTTP()
    retry_http.fail.add(
        "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000000001&fileDetailSn=2&dataNm=API+guide.docx"
    )
    failed = ReferencePipeline(retry_store, retry_http).run(
        types=["API"], max_bytes=32, max_chars=10
    )
    retry_http.fail.clear()
    resumed = ReferencePipeline(retry_store, retry_http).run(
        resume=failed["run_id"], max_bytes=32, max_chars=10
    )

    assert failed["status"] == "incomplete"
    assert failed["failed"] == 1
    assert resumed["status"] == "completed"
    assert resumed["completed"] == 1
    assert len(retry_http.calls) == 2


def test_successful_reference_refresh_retires_only_its_previous_attachment_resource(monkeypatch):
    store = reference_store_with_catalogs(file=False)
    http = ReferenceHTTP(b"revision one")
    monkeypatch.setattr(
        reference_docs,
        "extract_reference_text",
        lambda payload, name, *, max_chars: {
            "status": "EXTRACTED",
            "text": payload.decode(),
            "char_count": len(payload),
            "error": None,
        },
    )
    store.db.portal_resources.insert_one(
        {"_id": "dcat", "catalog_id": "API:15129394", "kind": "dcat", "is_active": True}
    )

    ReferencePipeline(store, http).run(types=["API"], max_bytes=32, max_chars=32)
    http.payload = b"revision two"
    ReferencePipeline(store, http).run(types=["API"], max_bytes=32, max_chars=32, force=True)

    resources = list(
        store.db.portal_resources.find({"catalog_id": "API:15129394", "kind": "reference_document"})
    )
    assert len(resources) == 2
    assert len([value for value in resources if value["is_active"]]) == 1
    assert store.db.portal_resources.find_one({"_id": "dcat"})["is_active"] is True


def test_reference_pipeline_rejects_oversized_download_without_retiring_other_resources(
    monkeypatch,
):
    store = reference_store_with_catalogs(file=False)
    http = ReferenceHTTP(b"too large")
    monkeypatch.setattr(
        reference_docs,
        "extract_reference_text",
        lambda payload, name, *, max_chars: {
            "status": "EXTRACTED",
            "text": "ok",
            "char_count": 2,
            "error": None,
        },
    )
    store.db.portal_resources.insert_one(
        {"_id": "dcat", "catalog_id": "API:15129394", "kind": "dcat", "is_active": True}
    )

    report = ReferencePipeline(store, http).run(types=["API"], max_bytes=3, max_chars=10)

    assert report["status"] == "incomplete"
    assert report["failed"] == 1
    assert store.db.portal_resources.find_one({"_id": "dcat"})["is_active"] is True


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


def _valid_docx(
    document=b'<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>text</w:t></w:r></w:p></w:body></w:document>',
):
    return _zip(
        {
            "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            "_rels/.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
            "word/document.xml": document,
        }
    )


def test_rejects_generic_zip_payloads_that_only_mimic_docx_or_hwpx_members():
    assert (
        extract_reference_text(
            _zip({"word/document.xml": b"<document><p>not a DOCX package</p></document>"}),
            "guide.docx",
            max_chars=100,
        )["status"]
        == "MALFORMED"
    )
    assert (
        extract_reference_text(
            _zip({"Contents/section0.xml": b"<section><p>not a HWPX package</p></section>"}),
            "guide.hwpx",
            max_chars=100,
        )["status"]
        == "MALFORMED"
    )


def test_rejects_non_positive_character_limits():
    for limit in (0, -1, True):
        result = extract_reference_text(_valid_docx(), "guide.docx", max_chars=limit)
        assert result == {
            "status": "MALFORMED",
            "text": "",
            "char_count": 0,
            "error": "Invalid extraction limit",
        }


def test_rejects_zip_member_limit_and_suspicious_compression_ratio(monkeypatch):
    monkeypatch.setattr(reference_docs, "MAX_ZIP_MEMBER_BYTES", 4)
    result = extract_reference_text(
        _valid_docx(b"<document><p>large</p></document>"), "guide.docx", max_chars=100
    )
    assert result == {
        "status": "MALFORMED",
        "text": "",
        "char_count": 0,
        "error": "Malformed DOCX archive",
    }
    monkeypatch.setattr(reference_docs, "MAX_ZIP_MEMBER_BYTES", 1024 * 1024)
    monkeypatch.setattr(reference_docs, "MAX_ZIP_COMPRESSION_RATIO", 1)
    result = extract_reference_text(_valid_docx(b"x" * 4096), "guide.docx", max_chars=100)
    assert result["status"] == "MALFORMED"
    assert result["error"] == "Malformed DOCX archive"


def test_pdf_stops_after_output_budget_and_rejects_excess_pages(monkeypatch):
    calls = []

    class Page:
        def __init__(self, value):
            self.value = value

        def extract_text(self):
            calls.append(self.value)
            if self.value == "later":
                raise AssertionError("output cap did not stop PDF extraction")
            return self.value

    class Reader:
        is_encrypted = False
        pages = [Page("one"), Page("later")]

        def __init__(self, *_):
            pass

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
    def __init__(self, streams):
        self.streams = streams

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def exists(self, name):
        return name in self.streams

    def openstream(self, name):
        return _Stream(self.streams[name])

    def listdir(self):
        return [name.split("/") for name in self.streams]


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
    _fake_hwp(
        monkeypatch,
        {"FileHeader": _hwp_header(), "BodyText/Section10": raw_ten, "BodyText/Section2": raw_two},
    )
    result = extract_reference_text(b"ole", "guide.hwp", max_chars=100)
    assert result["text"] == "two\n\nten"
    _fake_hwp(monkeypatch, {"FileHeader": _hwp_header(valid=False), "BodyText/Section0": raw_two})
    assert extract_reference_text(b"ole", "guide.hwp", max_chars=100) == {
        "status": "MALFORMED",
        "text": "",
        "char_count": 0,
        "error": "Malformed HWP document",
    }
    _fake_hwp(
        monkeypatch, {"FileHeader": _hwp_header(encrypted=True), "BodyText/Section0": raw_two}
    )
    assert extract_reference_text(b"ole", "guide.hwp", max_chars=100) == {
        "status": "UNSUPPORTED",
        "text": "",
        "char_count": 0,
        "error": "Password-protected HWP document",
    }


def test_hwp_public_extraction_supports_compressed_section_and_ignores_nonstandard_sections(
    monkeypatch,
):
    import zlib

    raw = _record(66) + _record(67, "compressed".encode("utf-16le"))
    compressor = zlib.compressobj(wbits=-15)
    packed = compressor.compress(raw) + compressor.flush()
    _fake_hwp(
        monkeypatch,
        {
            "FileHeader": _hwp_header(compressed=True),
            "BodyText/Section0": packed,
            "BodyText/SectionNotes": raw,
        },
    )
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
        observations.append(
            (stage, {name: getattr(filters, name) for name in reference_docs.PDF_FILTER_LIMITS})
        )

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
    assert all(
        values == {name: limit for name in reference_docs.PDF_FILTER_LIMITS}
        for _, values in observations
    )
    assert {name: getattr(filters, name) for name in reference_docs.PDF_FILTER_LIMITS} == original


def test_reference_resume_uses_persisted_limits_and_retries_malformed_content(monkeypatch):
    store = reference_store_with_catalogs(file=False)
    http = ReferenceHTTP(b"long document")
    monkeypatch.setattr(
        reference_docs,
        "extract_reference_text",
        lambda payload, name, *, max_chars: {
            "status": "MALFORMED",
            "text": "",
            "char_count": 0,
            "error": "Malformed DOCX archive",
        },
    )
    first = ReferencePipeline(store, http).run(types=["API"], max_bytes=32, max_chars=2)
    assert first["status"] == "incomplete"
    resource = store.db.portal_resources.find_one({"kind": "reference_document"})
    assert resource["is_active"] is False
    assert store.db.portal_reference_runs.find_one({"_id": first["run_id"]})["max_chars"] == 2

    observed = {}

    def extracted(payload, name, *, max_chars):
        observed["max_chars"] = max_chars
        return {"status": "EXTRACTED", "text": "ok", "char_count": 2, "error": None}

    monkeypatch.setattr(reference_docs, "extract_reference_text", extracted)
    second = ReferencePipeline(store, http).run(resume=first["run_id"])
    assert second["status"] == "completed"
    assert observed["max_chars"] == 2


def test_reference_resume_marks_removed_descriptor_stale_without_publishing(monkeypatch):
    store = reference_store_with_catalogs(file=False)
    http = ReferenceHTTP()
    http.fail.add(
        "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000000001&fileDetailSn=2&dataNm=API+guide.docx"
    )
    first = ReferencePipeline(store, http).run(types=["API"], max_bytes=32, max_chars=10)
    catalog = store.db.portal_catalog.find_one({"_id": "API:15129394"})
    MongoStore(store.db).save_raw(json.dumps({"attachments": []}).encode())
    store.db.portal_catalog.update_one(
        {"_id": catalog["_id"]},
        {
            "$set": {
                "parsed_detail_ref": MongoStore(store.db).save_raw(
                    json.dumps({"attachments": []}).encode()
                )
            }
        },
    )
    http.fail.clear()
    resumed = ReferencePipeline(store, http).run(resume=first["run_id"])
    assert resumed["status"] == "completed"
    assert resumed["stale"] == 1
    assert (
        store.db.portal_resources.count_documents({"kind": "reference_document", "is_active": True})
        == 0
    )


def test_selection_load_failures_checkpoint_and_resume_before_document_processing(monkeypatch):
    store = reference_store_with_catalogs(file=False)
    store.db.portal_catalog.insert_one(
        {
            "_id": "API:2",
            "data_type": "API",
            "list_id": 2,
            "is_active": True,
            "detail_status": "completed",
            "parsed_detail_ref": "missing",
        }
    )
    http = ReferenceHTTP()
    monkeypatch.setattr(
        reference_docs,
        "extract_reference_text",
        lambda *_args, **_kwargs: {
            "status": "EXTRACTED",
            "text": "ok",
            "char_count": 2,
            "error": None,
        },
    )
    first = ReferencePipeline(store, http).run(types=["API"], max_bytes=32, max_chars=10)
    assert first["status"] == "incomplete"
    assert first["selection_complete"] is True
    assert first["failed"] == 1
    assert len(http.calls) == 1
    store.db.portal_catalog.update_one(
        {"_id": "API:2"},
        {
            "$set": {
                "parsed_detail_ref": MongoStore(store.db).save_raw(
                    json.dumps({"attachments": []}).encode()
                )
            }
        },
    )
    resumed = ReferencePipeline(store, http).run(resume=first["run_id"])
    assert resumed["status"] == "completed"
    assert resumed["selection_complete"] is True
    assert resumed["completed"] == 1


def test_unreadable_current_detail_stays_retryable_and_same_bytes_failed_force_keeps_active_success(
    monkeypatch,
):
    store = reference_store_with_catalogs(file=False)
    http = ReferenceHTTP(b"same bytes")
    monkeypatch.setattr(
        reference_docs,
        "extract_reference_text",
        lambda *_a, **_k: {"status": "EXTRACTED", "text": "ok", "char_count": 2, "error": None},
    )
    ReferencePipeline(store, http).run(types=["API"], max_bytes=32, max_chars=10)
    active = store.db.portal_resources.find_one({"kind": "reference_document", "is_active": True})
    monkeypatch.setattr(
        reference_docs,
        "extract_reference_text",
        lambda *_a, **_k: {
            "status": "MALFORMED",
            "text": "",
            "char_count": 0,
            "error": "Malformed DOCX archive",
        },
    )
    failed = ReferencePipeline(store, http).run(
        types=["API"], max_bytes=32, max_chars=10, force=True
    )
    assert failed["status"] == "incomplete"
    assert store.db.portal_resources.find_one({"_id": active["_id"]})["is_active"] is True
    catalog = store.db.portal_catalog.find_one({"_id": "API:15129394"})
    store.db.portal_catalog.update_one(
        {"_id": catalog["_id"]}, {"$set": {"parsed_detail_ref": "missing"}}
    )
    retry = ReferencePipeline(store, http).run(resume=failed["run_id"])
    assert retry["status"] == "incomplete"
    assert retry["failed"] == 1
    assert retry["stale"] == 0


def test_resume_active_catalog_without_usable_detail_stays_retryable_but_removed_catalog_is_stale(
    monkeypatch,
):
    store = reference_store_with_catalogs(file=False)
    http = ReferenceHTTP()
    http.fail.add(
        "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000000001&fileDetailSn=2&dataNm=API+guide.docx"
    )
    first = ReferencePipeline(store, http).run(types=["API"], max_bytes=32, max_chars=10)
    for fields in ({"detail_status": "failed"}, {"$unset": "parsed_detail_ref"}):
        if "$unset" in fields:
            store.db.portal_catalog.update_one(
                {"_id": "API:15129394"}, {"$unset": {"parsed_detail_ref": ""}}
            )
        else:
            store.db.portal_catalog.update_one({"_id": "API:15129394"}, {"$set": fields})
        result = ReferencePipeline(store, http).run(resume=first["run_id"])
        assert result["failed"] == 1 and result["stale"] == 0
        store.db.portal_catalog.update_one(
            {"_id": "API:15129394"},
            {
                "$set": {
                    "detail_status": "completed",
                    "parsed_detail_ref": MongoStore(store.db).save_raw(
                        json.dumps(detail(attachment("API guide.docx"))).encode()
                    ),
                }
            },
        )
    store.db.portal_catalog.update_one({"_id": "API:15129394"}, {"$set": {"is_active": False}})
    result = ReferencePipeline(store, http).run(resume=first["run_id"])
    assert result["stale"] == 1 and result["failed"] == 0
