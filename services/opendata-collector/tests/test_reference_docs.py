import io
import struct
import zipfile

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
            "word/document.xml": b'<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>one</w:t></w:r></w:p><w:p><w:r><w:t>two</w:t></w:r></w:p></w:body></w:document>'
        }
    )
    hwpx = _zip(
        {
            "Contents/section0.xml": b'<hp:section xmlns:hp="hp"><hp:p><hp:run><hp:t>hana</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>dul</hp:t></hp:run></hp:p></hp:section>'
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
