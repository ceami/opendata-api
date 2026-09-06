import json
from pathlib import Path

import httpx

from opendata_collector.details import DetailCollector
from opendata_collector.http import PortalHTTP

FIXTURES = Path(__file__).parent / "fixtures"


def api_item():
    return {
        "catalog_id": "API:123",
        "list_id": 123,
        "data_type": "API",
        "title": "자료",
        "detail_url": "https://www.data.go.kr/data/123/openapi.do",
    }


def html():
    return """<input id="publicDataPk" value="123"><div class="data-info-body">
    <ul class="info-ul"><li><strong class="key">OpenAPI 명</strong><div class="value">자료</div></li></ul>
    <a href="/catalog/123/openapi.json">Schema.org</a>
    <a href="/biz/dcat/metadata/123.do">DCAT</a></div>"""


def test_exported_json_served_as_html_is_accepted_and_dcat_is_validated():
    responses = {
        "/data/123/openapi.do": html(),
        "/catalog/123/openapi.json": json.dumps(
            {"@type": "Dataset", "name": "자료", "custom": "보존"}
        ),
        "/biz/dcat/metadata/123.do": '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>',
    }
    with PortalHTTP(
        interval=0,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=responses[r.url.path])),
    ) as client:
        detail, resources, errors = DetailCollector(client).collect(api_item())
    assert errors == []
    assert len(resources) == 3
    assert detail["schema_org"][-1]["custom"] == "보존"


def test_one_failed_metadata_export_preserves_successful_resources_and_failure():
    def handle(request):
        if request.url.path.startswith("/catalog/"):
            return httpx.Response(404)
        if request.url.path.startswith("/biz/"):
            return httpx.Response(200, text="<html>로그인</html>")
        return httpx.Response(200, text=html())

    with PortalHTTP(interval=0, transport=httpx.MockTransport(handle)) as client:
        _, resources, errors = DetailCollector(client).collect(api_item())
    assert len(errors) == 2
    assert {error["kind"] for error in errors} == {"schema_org", "dcat"}
    assert len(resources) == 2  # even a wrong 200 body is retained for diagnosis


def test_invalid_detail_page_is_retained_instead_of_becoming_empty_success():
    with PortalHTTP(
        interval=0,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, text="<html>maintenance</html>")
        ),
    ) as client:
        _, resources, errors = DetailCollector(client).collect(api_item())
    assert len(resources) == 1
    assert errors and errors[0]["kind"] == "detail"


def test_dynamic_history_and_popups_preserve_version_parameter(monkeypatch):
    parsed = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [],
        "attachments": [],
        "resource_links": [],
        "file_history": {
            "url": "https://www.data.go.kr/tcs/dss/selectHistAndCsvData.do",
            "params": {"publicDataPk": "123", "publicDataDetailPk": "uddi:latest"},
        },
    }
    monkeypatch.setattr("opendata_collector.details.parse_detail", lambda *_: parsed)
    requests = []

    def handle(request):
        requests.append(request)
        if "selectHistAndCsvData" in request.url.path:
            return httpx.Response(
                200,
                text="""<table><thead><tr><th>데이터명</th><th>등록일</th></tr></thead><tbody><tr><td><a class="openFileDetailPopup" data-public-pk="uddi:old" data-public-detail-sn="4">과거 자료</a></td><td>2025-01-01</td></tr></tbody></table>""",
            )
        if "selectDpkDetailInfo" in request.url.path:
            return httpx.Response(
                200, text="<table><tr><th>설명</th><td>과거 버전 설명</td></tr></table>"
            )
        return httpx.Response(200, text=html())

    with PortalHTTP(interval=0, transport=httpx.MockTransport(handle)) as client:
        detail, resources, errors = DetailCollector(client).collect(api_item())
    assert errors == []
    assert len(resources) == 3
    assert requests[-1].method == "POST"
    assert requests[-1].content == b"publicDataDetailPk=uddi%3Aold&publicDataHistSn=4"
    assert detail["detail_popups"][0]["data"]["metadata"]["설명"] == ["과거 버전 설명"]


def test_standard_members_are_paginated_and_each_metadata_popup_is_collected(monkeypatch):
    parsed = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [],
        "attachments": [],
        "resource_links": [],
        "standard_members": {
            "total": 2,
            "pages": 2,
            "list_url": "https://www.data.go.kr/tcs/dss/stdFileList.do?publicDataPk=123",
            "items": [{"public_data_detail_pk": "uddi:one", "title": "첫 기관"}],
        },
    }
    monkeypatch.setattr("opendata_collector.details.parse_detail", lambda *_: parsed)
    requests = []

    def handle(request):
        requests.append(request)
        if "stdFileList" in request.url.path:
            return httpx.Response(
                200,
                text="""<table><thead><tr><th>데이터명</th><th>제공기관</th><th>등록일</th></tr></thead><tbody><tr><td><a class="openFileDetailPopup" data-public-pk="uddi:two">둘째 기관</a></td><td>기관</td><td>2026-01-01</td></tr></tbody></table>""",
            )
        if "selectDpkDetailInfo" in request.url.path:
            return httpx.Response(
                200, text="<table><tr><th>설명</th><td>기관별 자료</td></tr></table>"
            )
        return httpx.Response(200, text=html())

    with PortalHTTP(interval=0, transport=httpx.MockTransport(handle)) as client:
        detail, _, errors = DetailCollector(client).collect(api_item())
    assert errors == []
    assert detail["standard_members"]["collected_count"] == 2
    assert len(detail["detail_popups"]) == 2
    assert requests[1].url.params["pageIndex"] == "2"


def test_malformed_embedded_schema_is_repaired_without_losing_metadata():
    body = """<input id="publicDataPk" value="123">
    <script type="application/ld+json">{
      "@type":"Dataset",
      "description":"잘못된 "인용부호"\r설명"
    }</script>
    <ul class="info-ul"><li><strong class="key">제공기관</strong><div class="value">시험기관</div></li></ul>"""
    with PortalHTTP(
        interval=0,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body)),
    ) as client:
        detail, resources, errors = DetailCollector(client).collect(api_item())

    assert len(resources) == 1
    assert detail["metadata"]["제공기관"] == ["시험기관"]
    assert detail["schema_org"][0]["description"] == '잘못된 "인용부호"\r설명'
    assert detail["metadata_repairs"] == [
        {"kind": "schema_org", "method": "escape_unescaped_json_quotes", "count": 2}
    ]
    assert errors == []


def test_malformed_dcat_literal_is_repaired_and_original_resource_is_retained():
    responses = {
        "/data/123/openapi.do": html(),
        "/catalog/123/openapi.json": json.dumps({"@type": "Dataset", "name": "자료"}),
        "/biz/dcat/metadata/123.do": """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dct="http://purl.org/dc/terms/" xmlns:vcard="http://www.w3.org/2006/vcard/ns#"><rdf:Description><dct:description>조회 <주의사항><br>원문 & 설명</dct:description><vcard:organization-unit>R&D센터</vcard:organization-unit><dct:accessURL>https://example.test/file?a=1&b=2</dct:accessURL></rdf:Description></rdf:RDF>""",
    }
    with PortalHTTP(
        interval=0,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=responses[r.url.path])),
    ) as client:
        detail, resources, errors = DetailCollector(client).collect(api_item())

    assert errors == []
    assert len(resources) == 3
    assert next(r for r in resources if r.kind == "dcat").content.endswith(b"</rdf:RDF>")
    assert detail["metadata_repairs"] == [{"kind": "dcat", "method": "escape_invalid_xml_literals"}]


def test_malformed_dcat_conforms_to_literal_is_repaired():
    responses = {
        "/data/123/openapi.do": html(),
        "/catalog/123/openapi.json": json.dumps({"@type": "Dataset", "name": "자료"}),
        "/biz/dcat/metadata/123.do": """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dct="http://purl.org/dc/terms/"><rdf:Description><dct:conformsTo><대한무역투자진흥공사 법 제 10조의 1항 1호><br/>제10조(사업)</dct:conformsTo></rdf:Description></rdf:RDF>""",
    }
    with PortalHTTP(
        interval=0,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=responses[r.url.path])),
    ) as client:
        detail, resources, errors = DetailCollector(client).collect(api_item())

    assert errors == []
    assert len(resources) == 3
    assert detail["metadata_repairs"] == [{"kind": "dcat", "method": "escape_invalid_xml_literals"}]


def test_structurally_invalid_embedded_schema_is_not_over_repaired():
    body = """<input id="publicDataPk" value="123">
    <script type="application/ld+json">{"@type":Dataset}</script>
    <ul class="info-ul"><li><strong class="key">제공기관</strong><div class="value">시험기관</div></li></ul>"""
    with PortalHTTP(
        interval=0,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body)),
    ) as client:
        detail, resources, errors = DetailCollector(client).collect(api_item())

    assert len(resources) == 1
    assert detail["metadata"]["제공기관"] == ["시험기관"]
    assert detail["schema_org"] == []
    assert detail["metadata_repairs"] == []
    assert errors == [{"kind": "schema_org", "error": "Malformed embedded schema.org JSON"}]


def test_structurally_invalid_dcat_is_not_over_repaired():
    responses = {
        "/data/123/openapi.do": html(),
        "/catalog/123/openapi.json": json.dumps({"@type": "Dataset", "name": "자료"}),
        "/biz/dcat/metadata/123.do": """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="https://example.test/a&b" /></rdf:RDF>""",
    }
    with PortalHTTP(
        interval=0,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=responses[r.url.path])),
    ) as client:
        detail, resources, errors = DetailCollector(client).collect(api_item())

    assert len(resources) == 3
    assert detail["metadata_repairs"] == []
    assert len(errors) == 1
    assert errors[0]["kind"] == "dcat"


def test_malformed_json_string_cannot_absorb_a_sibling_property():
    body = """<input id="publicDataPk" value="123">
    <script type="application/ld+json">{
      "@type":"Dataset",
      "name":"자료 "인용"", "url":"https://example.test/data"
    }</script>"""
    with PortalHTTP(
        interval=0,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body)),
    ) as client:
        detail, _, errors = DetailCollector(client).collect(api_item())

    assert detail["schema_org"] == []
    assert detail["metadata_repairs"] == []
    assert errors == [{"kind": "schema_org", "error": "Malformed embedded schema.org JSON"}]


def test_utf16_dcat_dtd_is_rejected_before_xml_parsing():
    dcat = """<?xml version="1.0" encoding="UTF-16"?>
    <!DOCTYPE rdf:RDF [<!ENTITY injected "EXPANDED">]>
    <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dct="http://purl.org/dc/terms/"><rdf:Description><dct:title>&injected;</dct:title></rdf:Description></rdf:RDF>""".encode(
        "utf-16"
    )

    def handle(request):
        if request.url.path == "/biz/dcat/metadata/123.do":
            return httpx.Response(200, content=dcat, headers={"content-type": "application/xml"})
        responses = {
            "/data/123/openapi.do": html(),
            "/catalog/123/openapi.json": json.dumps({"@type": "Dataset", "name": "자료"}),
        }
        return httpx.Response(200, text=responses[request.url.path])

    with PortalHTTP(interval=0, transport=httpx.MockTransport(handle)) as client:
        detail, resources, errors = DetailCollector(client).collect(api_item())

    assert len(resources) == 3
    assert detail["metadata_repairs"] == []
    assert len(errors) == 1
    assert errors[0]["kind"] == "dcat"
    assert "Unsupported XML declarations" in errors[0]["error"]


def test_ambiguous_description_quotes_require_matching_visible_metadata():
    description = '데이터는 "첫째","둘째" 항목으로 구성됩니다.'
    body = f"""<input id="publicDataPk" value="123">
    <script type="application/ld+json">{{
      "@type":"Dataset",
      "description":"{description}"
    }}</script>
    <ul class="info-ul"><li><strong class="key">설명</strong><div class="value">{description}</div></li></ul>"""
    with PortalHTTP(
        interval=0,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body)),
    ) as client:
        detail, _, errors = DetailCollector(client).collect(api_item())

    assert errors == []
    assert detail["schema_org"][0]["description"] == description
    assert detail["metadata_repairs"] == [
        {"kind": "schema_org", "method": "escape_unescaped_json_quotes", "count": 4}
    ]
