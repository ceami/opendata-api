"""Public-page excerpts and adverse responses exercise collector boundaries."""

from copy import deepcopy
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from opendata_collector.parsers import (
    load_json_metadata,
    parse_dcat_metadata,
    parse_detail,
    parse_listing,
    parse_standard_members,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    html = (FIXTURES / name).read_text(encoding="utf-8")
    if name.startswith("list-"):
        soup = BeautifulSoup(html, "html.parser")
        node = soup.select_one(".apply-result-item")
        for index in range(1, 10):
            duplicate = deepcopy(node)
            link = duplicate.select_one(".apply-result-link a")
            parts = link["href"].split("/")
            parts[2] = str(int(parts[2]) + index)
            link["href"] = "/".join(parts)
            soup.select_one(".data-list-group").append(duplicate)
        return str(soup)
    return html


def item(kind="API", pk=15129394):
    suffix = {"API": "openapi", "FILE": "fileData", "STD": "standard", "LINKED": "linkedData"}[kind]
    return {
        "catalog_id": f"{kind}:{pk}",
        "data_type": kind,
        "list_id": pk,
        "detail_url": f"https://www.data.go.kr/data/{pk}/{suffix}.do",
        "title": "데이터",
    }


@pytest.mark.parametrize(
    "kind,pk,total",
    [
        ("API", 15075883, 11910),
        ("FILE", 3049380, 84179),
        ("STD", 15028204, 300),
        ("LINKED", 33643, 262684),
    ],
)
def test_current_listing_preserves_identity_and_totals(kind, pk, total):
    result = parse_listing(fixture(f"list-{kind.lower()}.html"), kind, 1, 10)
    assert result["total"] == total
    assert (result["page"], result["page_size"]) == (1, 10)
    assert result["member_total"] == (12692 if kind == "STD" else None)
    assert result["items"][0]["catalog_id"] == f"{kind}:{pk}"
    assert result["items"][0]["detail_url"] == item(kind, pk)["detail_url"]
    assert result["items"][0]["summary"]["badges"]
    assert result["items"][0]["summary"]["description"]


def test_linked_malformed_keyword_markup_remains_in_summary_text():
    result = parse_listing(fixture("list-linked.html"), "LINKED", 1, 10)
    assert "영문법령,법령정보,법제연구원" in result["items"][0]["summary"]["text"]


@pytest.mark.parametrize("page,size", [(2, 10), (1, 100)])
def test_listing_rejects_ignored_pagination(page, size):
    with pytest.raises(ValueError, match="pagination"):
        parse_listing(fixture("list-api.html"), "API", page, size)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-link",
        "invalid-id",
        "wrong-type",
        "duplicate",
        "empty",
        "missing-count",
        "missing-page",
        "conflicting-page",
    ],
)
def test_listing_rejects_incomplete_or_ambiguous_response(mutation):
    s = BeautifulSoup(fixture("list-api.html"), "html.parser")
    a = s.select_one(".apply-result-link a")
    if mutation == "missing-link":
        a.decompose()
    if mutation == "invalid-id":
        a["href"] = "/data/invalid/openapi.do"
    if mutation == "wrong-type":
        a["href"] = "/data/15075883/fileData.do"
    if mutation == "duplicate":
        s.select_one(".data-list-group").append(
            BeautifulSoup(str(s.select_one(".apply-result-item")), "html.parser")
        )
    if mutation == "empty":
        for node in s.select(".apply-result-item"):
            node.decompose()
    if mutation == "missing-count":
        s.select_one(".data-result-tit").decompose()
    if mutation == "missing-page":
        s.select_one("[name=currentPage]").decompose()
    if mutation == "conflicting-page":
        s.append(BeautifulSoup('<input name="currentPage" value="2">', "html.parser"))
    with pytest.raises(ValueError):
        parse_listing(str(s), "API", 1, 10)


def test_explicit_zero_is_valid_and_core_is_not_a_dataset_type():
    html = '<input name="currentPage" value="1"><input name="perPage" value="10"><div class="data-result-tit">오픈API (0건)</div>'
    assert parse_listing(html, "API", 1, 10)["items"] == []
    with pytest.raises(ValueError):
        parse_listing(html, "CORE", 1, 10)


def test_api_detail_preserves_spec_schema_labels_and_reference_file():
    result = parse_detail(fixture("detail-api.html"), item())
    assert result["detail_format"] == "SWAGGER"
    assert result["metadata"]["제공기관"] == ["조달청"]
    assert result["metadata"]["관리부서 전화번호"] == ["0427247685"]
    assert result["schema_org"][0]["description"] == "물품, 용역, 공사\n외자 입찰공고목록"
    assert result["api_specs"][0]["info"]["description"] == "공고목록\n사용 안내"
    assert result["api_specs"][0]["paths"]["/bids"]["get"]["parameters"][0]["required"] is True
    assert result["attachments"][0]["name"].endswith(".docx")
    assert result["attachments"][0]["file_id"] == "FILE_000000003665344"
    assert result["attachments"][0]["file_detail_sn"] == "1"
    assert result["hidden_fields"]["publicDataPk"] == "15129394"
    assert {r["kind"] for r in result["resource_links"]} == {"schema_org", "dcat"}


def test_file_detail_preserves_column_table_and_external_swagger_resource():
    result = parse_detail(fixture("detail-file.html"), item("FILE", 3049380))
    assert {
        "kind": "openapi_spec",
        "url": "https://infuser.odcloud.kr/oas/docs?namespace=3049380/v1",
    } in result["resource_links"]
    assert result["tables"][0]["rows"][0] == ["학술지명(국문)", "가변문자형(VARCHAR)", "1000"]
    assert any(
        a.get("public_data_detail_pk", "").startswith("uddi:") for a in result["attachments"]
    )
    assert any("columnDefExcel.do" in a.get("url", "") for a in result["attachments"])


def test_standard_detail_exposes_member_fragment_pagination_and_opaque_identifiers():
    html = fixture("detail-std.html")
    result = parse_detail(html, item("STD", 15028204))
    members = result["standard_members"]
    assert members["total"] == 222
    assert members["pages"] == 45
    assert (
        members["list_url"] == "https://www.data.go.kr/tcs/dss/stdFileList.do?publicDataPk=15028204"
    )
    member = members["items"][0]
    assert member["public_data_detail_pk"] == "uddi:408da0d2-efc4-4ef6-bbe3-e0aa75bef72a"
    assert member["provider"] == "전남광주통합특별시 고흥군"
    assert member["registered_at"] == "2026-09-03"
    assert member["title"] == "전남광주통합특별시_고흥군_자동차정비업체"
    assert parse_standard_members(html)["items"] == members["items"]


def test_linked_detail_preserves_target_without_exposing_usage_counter_actions():
    result = parse_detail(fixture("detail-linked.html"), item("LINKED", 33643))
    assert result["detail_format"] == "LINK"
    assert result["metadata"]["URL"][0].startswith("https://elaw.klri.re.kr/")
    assert result["attachments"] == []
    assert any(r["url"].endswith("/linked/33643.do") for r in result["resource_links"])


def test_legacy_table_metadata_preserves_repeated_labels_and_related_datasets():
    html = '<input id="publicDataPk" value="15129394"><table><tr><th>제공기관</th><td>기관 A</td><th>제공기관</th><td>기관 B</td></tr></table><a href="/data/3049380/fileData.do">관련 파일</a>'
    result = parse_detail(html, item())
    assert result["metadata"]["제공기관"] == ["기관 A", "기관 B"]
    assert result["related_datasets"][0]["catalog_id"] == "FILE:3049380"
    assert result["detail_format"] == "TABLE"


@pytest.mark.parametrize(
    "html",
    [
        "<html>로그인</html>",
        '<input id="publicDataPk" value="999"><ul class="info-ul"><li><strong class="key">이름</strong><div class="value">오류</div></li></ul>',
    ],
)
def test_detail_rejects_missing_or_wrong_identity(html):
    with pytest.raises(ValueError, match="identity"):
        parse_detail(html, item())


def test_standard_uses_schema_identity_when_internal_hidden_id_differs():
    html = '<input id="publicDataPk" value="15045089"><script type="application/ld+json">{"@type":"Dataset","url":"https://data.go.kr/data/15124679/standard.do"}</script><ul class="info-ul"><li><strong class="key">설명</strong><div class="value">표준</div></li></ul>'
    assert parse_detail(html, item("STD", 15124679))["hidden_fields"]["publicDataPk"] == "15045089"


def test_invalid_embedded_spec_is_failure_instead_of_silent_metadata_loss():
    with pytest.raises(ValueError, match="swaggerJson"):
        parse_detail(
            '<input id="publicDataPk" value="15129394"><script>const swaggerJson = `{broken}`;</script>',
            item(),
        )


def test_member_fragment_rejects_login_shell():
    with pytest.raises(ValueError):
        parse_standard_members("<html>로그인</html>")


def test_listing_rejects_short_nonfinal_page():
    soup = BeautifulSoup(fixture("list-api.html"), "html.parser")
    soup.select(".apply-result-item")[-1].decompose()
    with pytest.raises(ValueError, match="count"):
        parse_listing(str(soup), "API", 1, 10)


def test_file_history_descriptor_uses_actual_dataset_ids():
    html = (
        fixture("detail-file.html")
        + '<div id="fileHistAndCsvData"></div><script src="/js/biz/datset/script_fileDetail.js"></script>'
    )
    result = parse_detail(html, item("FILE", 3049380))
    assert result["file_history"] == {
        "url": "https://www.data.go.kr/tcs/dss/selectHistAndCsvData.do",
        "params": {
            "publicDataPk": "3049380",
            "publicDataDetailPk": "uddi:a7c1395d-5090-42f5-a3a1-8f4d41477dd1",
        },
    }


def test_fragment_preserves_history_identifiers_and_preview_tables():
    from opendata_collector.parsers import parse_metadata_fragment

    result = parse_metadata_fragment(fixture("file-history.html"))
    assert len(result["tables"]) == 2
    assert result["tables"][1]["rows"][0] == ["한국연구재단_KCI인용지수정보_20211231", "2022-08-19"]
    assert (
        result["file_details"][0]["public_data_detail_pk"]
        == "uddi:b253839b-1574-4a0e-b1bf-de45581aef07"
    )
    assert result["file_details"][0]["public_data_detail_sn"] == "2"
    assert "미리보기" in result["text"]
    assert result["detail_popups"] == [
        {
            "url": "https://www.data.go.kr/tcs/dss/selectDpkDetailInfo.do",
            "params": {
                "publicDataDetailPk": "uddi:b253839b-1574-4a0e-b1bf-de45581aef07",
                "publicDataHistSn": "2",
            },
        }
    ]


def test_fragment_accepts_portal_empty_file_history_response():
    from opendata_collector.parsers import parse_metadata_fragment

    html = """<script>
    const $fileDetailPopupArea = $('#fileDetailPopup');
    $(document).on('click', '.openFileDetailPopup', function() {
      $.ajax({url: '/tcs/dss/selectDpkDetailInfo.do'});
    });
    </script>"""

    result = parse_metadata_fragment(html)

    assert result["file_details"] == []
    assert result["detail_popups"] == []
    assert result["tables"] == []


def test_fragment_rejects_error_shell_with_empty_history_script_tokens():
    from opendata_collector.parsers import parse_metadata_fragment

    html = """<h1>점검중</h1><script>
    const $fileDetailPopupArea = $('#fileDetailPopup');
    $(document).on('click', '.openFileDetailPopup', function() {
      $.ajax({url: '/tcs/dss/selectDpkDetailInfo.do'});
    });
    </script>"""

    with pytest.raises(ValueError):
        parse_metadata_fragment(html)


def test_fragment_rejects_unrecognized_error_shell():
    from opendata_collector.parsers import parse_metadata_fragment

    with pytest.raises(ValueError):
        parse_metadata_fragment("<html><h1>점검중</h1></html>")


def test_legacy_operation_descriptors_require_actual_select_options():
    html = (
        fixture("detail-api.html")
        + """<select id="open_api_detail_select"><option value="">선택</option><option value="314">조회 기능</option></select><script>const fn_selectApiDetailFunction = function () { $.ajax({url: "/tcs/dss/selectApiDetailFunction.do", method: "post", data: {oprtinSeqNo: $("#open_api_detail_select").val(), publicDataDetailPk: $("#publicDataDetailPk").val()}}); };</script>"""
    )
    result = parse_detail(html, item())
    assert result["api_operations"] == [
        {
            "name": "조회 기능",
            "url": "https://www.data.go.kr/tcs/dss/selectApiDetailFunction.do",
            "params": {
                "oprtinSeqNo": "314",
                "publicDataDetailPk": "uddi:53bc9153-fb7f-4c75-8a7c-cf013fe00d5a_202410251427",
                "publicDataPk": "15129394",
            },
        }
    ]
    assert "api_operations" not in parse_detail(fixture("detail-api.html"), item())


def test_history_popup_download_format_is_not_a_history_sequence():
    from opendata_collector.parsers import parse_metadata_fragment

    html = """<div id="file-detail-popup"><ul class="info-ul"><li><strong class="key">데이터 다운로드</strong><div class="value"><a onclick="fn_fileDataDown('3049380', 'uddi:history', 'FILE_000000002590216', '1', 'csv')">CSV</a></div></li></ul></div>"""
    attachment = parse_metadata_fragment(html)["attachments"][0]
    assert attachment["format"] == "csv"
    assert "public_data_hist_sn" not in attachment
    assert attachment["arguments"] == [
        "3049380",
        "uddi:history",
        "FILE_000000002590216",
        "1",
        "csv",
    ]


def test_standard_detail_uses_response_url_and_title_when_schema_identity_is_malformed():
    title = "전국건설업체정보표준데이터"
    html = f"""<title>{title} | 공공데이터포털</title>
    <input id="publicDataPk" value="15061362">
    <script type="application/ld+json">{{"@type":"Dataset","description":"깨진 "설명""}}</script>
    <ul class="info-ul"><li><strong class="key">설명</strong><div class="value">표준 상세</div></li></ul>"""
    catalog_item = item("STD", 15129444)
    catalog_item["title"] = title

    result = parse_detail(html, catalog_item, source_url=catalog_item["detail_url"])

    assert result["metadata"]["설명"] == ["표준 상세"]
    assert result["parse_errors"] == [
        {"kind": "schema_org", "error": "Malformed embedded schema.org JSON"}
    ]


def test_standard_detail_rejects_generic_title_fallback():
    html = """<title>데이터 | 공공데이터포털</title>
    <input id="publicDataPk" value="15061362">
    <script type="application/ld+json">{"@type":"Dataset","description":"깨진 "설명""}</script>"""
    catalog_item = item("STD", 15129444)

    with pytest.raises(ValueError, match="identity"):
        parse_detail(html, catalog_item, source_url=catalog_item["detail_url"])


def test_fragment_rejects_bare_error_text_with_empty_history_script_tokens():
    from opendata_collector.parsers import parse_metadata_fragment

    html = """서비스 점검중<script>
    const $fileDetailPopupArea = $('#fileDetailPopup');
    $(document).on('click', '.openFileDetailPopup', function() {
      $.ajax({url: '/tcs/dss/selectDpkDetailInfo.do'});
    });
    </script>"""

    with pytest.raises(ValueError):
        parse_metadata_fragment(html)


@pytest.mark.parametrize(
    "property_line",
    [
        '  "name":"자료 "인용"", "url":"https://example.test/data"',
        r'  "name":"자료 "인용"\\", "url":"https://example.test/data"',
        '  "name":"자료 "인용"", "orphan"',
    ],
)
def test_json_quote_repair_never_absorbs_sibling_properties(property_line):
    value = '{\n  "@type":"Dataset",\n' + property_line + "\n}"

    with pytest.raises(ValueError):
        load_json_metadata(value)


def test_dcat_repair_preserves_a_valid_xml_literal_sibling():
    value = b"""<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dct="http://purl.org/dc/terms/" xmlns:xhtml="http://www.w3.org/1999/xhtml"><rdf:Description><dct:title>R&D</dct:title><dct:description rdf:parseType="Literal"><xhtml:b>Bold</xhtml:b></dct:description></rdf:Description></rdf:RDF>"""

    root, repaired = parse_dcat_metadata(value, value.decode())

    assert repaired is True
    description = root.find(".//{http://purl.org/dc/terms/}description")
    assert description is not None
    assert len(description) == 1
    assert description[0].tag == "{http://www.w3.org/1999/xhtml}b"
    assert description[0].text == "Bold"


def test_exact_undefined_swagger_json_literal_means_no_embedded_spec():
    html = """<input id="publicDataPk" value="15129394">
    <script>const swaggerUrl = ''; const swaggerJson = `undefined`;</script>
    <ul class="info-ul"><li><strong class="key">OpenAPI 명</strong><div class="value">데이터</div></li></ul>"""

    result = parse_detail(html, item())

    assert result["api_specs"] == []
    assert result["detail_format"] == "METADATA"


def test_swagger_json_template_with_literal_backtick_is_recovered_at_statement_end():
    html = r"""<input id="publicDataPk" value="15129394">
    <script>const swaggerJson = `{"swagger":"2.0","info":{"description":"* `25. 7월 서비스 중단"},"paths":{}}`;</script>"""

    result = parse_detail(html, item())

    assert result["api_specs"][0]["info"]["description"] == "* `25. 7월 서비스 중단"
    assert result["detail_format"] == "SWAGGER"


def test_known_infuser_http_swagger_url_is_upgraded_to_https():
    html = (
        '<input id="publicDataPk" value="15129394">'
        "<script>const swaggerUrl = 'http://infuser.odcloud.kr/oas/docs?namespace=15113397/v1';</script>"
    )

    result = parse_detail(html, item())

    assert result["resource_links"] == [
        {
            "kind": "openapi_spec",
            "url": "https://infuser.odcloud.kr/oas/docs?namespace=15113397/v1",
        }
    ]
