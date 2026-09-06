from datetime import datetime, timezone

from opendata_collector.projection import project_legacy

COLLECTED_AT = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def test_projects_api_using_official_values_and_portal_fallbacks():
    item = {
        "catalog_id": "15012345",
        "data_type": "API",
        "list_id": 15012345,
        "title": "Portal title",
        "detail_url": "https://www.data.go.kr/data/15012345/openapi.do",
        "summary": {"description": "Portal description", "org_nm": "Portal org"},
    }
    detail = {
        "metadata": {
            "title": ["Detail title"],
            "description": ["Detail description"],
            "keywords": ["weather, climate / forecast"],
            "category_nm": ["Environment"],
            "use_prmisn_ennc": ["Public use"],
        },
        "api_specs": [
            {
                "swagger": "2.0",
                "schemes": ["https"],
                "host": "apis.data.go.kr",
                "basePath": "/B551011",
                "paths": {"/weather": {"get": {"operationId": "getWeather"}}},
            }
        ],
        "attachments": [{"name": "guide.pdf"}],
        "tables": [],
        "detail_format": "TABLE",
    }
    source = {
        "list_id": "15012345",
        "title": "Official title",
        "desc": "Official description",
        "org_nm": "Official org",
        "contact": "data@example.go.kr",
        "keywords": "official, keywords",
        "request_param_nm": "serviceKey, pageNo / numOfRows",
        "created_at": "2024-02-03 12:30:00",
        "updated_at": "2024-02-04T12:30:00+09:00",
        "is_confirmed_for_dev": None,
        "is_confirmed_for_prod": "Y",
        "is_copyrighted": None,
        "is_core_data": "N",
        "is_deleted": None,
        "is_list_deleted": "N",
        "is_std_data": None,
        "is_third_party_copyrighted": None,
        "request_cnt": "1,024",
    }

    collection, value = project_legacy(item, detail, COLLECTED_AT, source)

    assert collection == "open_data_info"
    assert value["title"] == "Official title"
    assert value["desc"] == "Official description"
    assert value["org_nm"] == "Official org"
    assert value["contact"] == "data@example.go.kr"
    assert value["category_nm"] == "Environment"
    assert value["keywords"] == ["official", "keywords"]
    assert value["request_param_nm"] == ["serviceKey", "pageNo", "numOfRows"]
    assert value["end_point_url"] == "https://apis.data.go.kr/B551011"
    assert value["request_cnt"] == 1024
    assert value["created_at"] == datetime(2024, 2, 3, 3, 30, tzinfo=timezone.utc)
    assert value["updated_at"] == datetime(2024, 2, 4, 3, 30, tzinfo=timezone.utc)
    assert value["is_confirmed_for_dev"] is None
    assert value["is_copyrighted"] is None
    assert value["is_deleted"] is None
    assert value["is_std_data"] is None
    assert value["is_third_party_copyrighted"] is None
    assert value["detail_format"] == "SWAGGER"
    assert value["source_catalog_id"] == "15012345"
    assert value["collected_at"] == COLLECTED_AT
    assert value["operations"] == [
        {"path": "/weather", "method": "GET", "operation_id": "getWeather"}
    ]
    assert value["attachments"] == [{"name": "guide.pdf"}]
    assert "detail_html" not in value
    assert not {"_id", "id", "is_parsed", "parsed_at", "ai_state"} & value.keys()


def test_projects_file_with_model_compatible_unknowns_without_inventing_flags():
    item = {
        "catalog_id": "15099999",
        "data_type": "FILE",
        "list_id": "15099999",
        "title": "File catalog title",
        "detail_url": "https://www.data.go.kr/data/15099999/fileData.do",
        "summary": {"description": "A downloadable file"},
    }
    detail = {
        "metadata": {"new_category_nm": ["Health"], "keywords": ["hospital; beds"]},
        "attachments": [{"name": "beds.csv", "ext": "csv"}],
        "tables": [{"name": "columns"}],
        "api_specs": [],
        "detail_format": "LINK",
    }

    collection, value = project_legacy(item, detail, COLLECTED_AT, {"data_type": "FILE"})

    assert collection == "open_file_info"
    assert value["list_id"] == 15099999
    assert value["data_type"] == "FILE"
    assert value["title"] == "File catalog title"
    assert value["desc"] == "A downloadable file"
    assert value["new_category_nm"] == "Health"
    assert value["keywords"] == ["hospital", "beds"]
    assert value["download_cnt"] is None
    assert value["is_charged"] is None
    assert value["created_at"] is None
    assert value["updated_at"] is None
    assert value["detail_format"] == "TABLE"
    assert value["attachments"] == [{"name": "beds.csv", "ext": "csv"}]
    assert "detail_html" not in value
    assert not {"_id", "id", "is_parsed", "parsed_at"} & value.keys()


def test_skips_standard_and_linked_catalog_records():
    base = {
        "catalog_id": "1",
        "list_id": 1,
        "title": "Ignored",
        "detail_url": "https://www.data.go.kr/data/1",
        "summary": {},
    }

    assert project_legacy({**base, "data_type": "STD"}, {}, COLLECTED_AT) is None
    assert project_legacy({**base, "data_type": "LINKED"}, {}, COLLECTED_AT) is None


def test_projects_korean_portal_metadata_and_schema_org_fallbacks():
    item = {
        "catalog_id": "API:15129394",
        "data_type": "API",
        "list_id": 15129394,
        "title": "Listing title",
        "detail_url": "https://www.data.go.kr/data/15129394/openapi.do",
        "summary": {},
    }
    detail = {
        "metadata": {
            "제공기관": ["조달청"],
            "관리부서명": ["조달관리국"],
            "관리부서 전화번호": ["0427247685"],
            "설명": ["공개 입찰 목록"],
            "키워드": ["입찰, 조달"],
            "분류체계": ["산업·고용"],
            "등록일": ["2024. 02. 03."],
            "수정일": ["not-a-date"],
            "API 유형": ["REST"],
            "데이터 포맷": ["JSON"],
            "활용신청 수": ["4,002"],
            "이용허락범위": ["제1유형"],
        },
        "schema_org": [
            {
                "name": "Schema title",
                "creator": {"name": "Schema organization"},
                "contactPoint": {"telephone": "02-0000-0000"},
                "dateModified": "still-not-a-date",
                "encodingFormat": "XML",
            }
        ],
        "api_specs": [],
        "attachments": [],
        "tables": [{"rows": [["large"]]}],
    }

    collection, value = project_legacy(item, detail, COLLECTED_AT)

    assert collection == "open_data_info"
    assert value["title"] == "Schema title"
    assert value["desc"] == "공개 입찰 목록"
    assert value["org_nm"] == "조달청"
    assert value["dept_nm"] == "조달관리국"
    assert value["contact"] == "0427247685"
    assert value["keywords"] == ["입찰", "조달"]
    assert value["category_nm"] == "산업·고용"
    assert value["api_type"] == "REST"
    assert value["data_format"] == "JSON"
    assert value["request_cnt"] == 4002
    assert value["use_prmisn_ennc"] == "제1유형"
    assert value["created_at"] == datetime(2024, 2, 2, 15, tzinfo=timezone.utc)
    assert value["updated_at"] is None
    assert "tables" not in value


def test_projects_schema_org_creator_contact_dates_and_format_when_metadata_is_absent():
    item = {
        "catalog_id": "API:3",
        "data_type": "API",
        "list_id": 3,
        "title": "Listing title",
        "detail_url": "https://www.data.go.kr/data/3/openapi.do",
        "summary": {},
    }
    detail = {
        "metadata": {},
        "schema_org": [
            {
                "name": "Schema dataset",
                "creator": {"name": "Schema provider"},
                "contactPoint": {"telephone": "02-1234-5678"},
                "datePublished": "2024-03-01",
                "dateModified": "2024-03-02T09:00:00+09:00",
                "encodingFormat": "CSV",
                "keywords": ["one", "two"],
                "license": "CC BY",
                "url": "https://schema.example/dataset",
            }
        ],
        "api_specs": [],
        "attachments": [],
        "tables": [],
    }

    _, value = project_legacy(item, detail, COLLECTED_AT)

    assert value["title"] == "Schema dataset"
    assert value["org_nm"] == "Schema provider"
    assert value["contact"] == "02-1234-5678"
    assert value["created_at"] == datetime(2024, 2, 29, 15, tzinfo=timezone.utc)
    assert value["updated_at"] == datetime(2024, 3, 2, tzinfo=timezone.utc)
    assert value["data_format"] == "CSV"
    assert value["keywords"] == ["one", "two"]
    assert value["use_prmisn_ennc"] == "CC BY"
    assert value["link_url"] == "https://schema.example/dataset"
