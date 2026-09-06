from datetime import datetime, timezone

from opendata_collector.parse_normalizers import (
    PARSER_VERSION,
    ParseInput,
    normalize_catalog,
    parse_openapi_endpoints,
)

NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


def parse_input(kind, detail, *, sources=(), resources=(), detail_status="completed"):
    return ParseInput(
        catalog={
            "_id": f"{kind}:7",
            "data_type": kind,
            "list_id": 7,
            "title": f"{kind} title",
            "detail_url": f"https://www.data.go.kr/data/7/{kind.lower()}.do",
            "summary": {"description": "summary description", "org_nm": "summary org"},
            "metadata": detail.get("metadata", {}),
            "detail_status": detail_status,
            "detail_errors": [] if detail_status == "completed" else [{"kind": "source"}],
            "parsed_detail_ref": "detail-sha",
        },
        detail=detail,
        source_records=list(sources),
        resources=list(resources),
        source_fingerprint="source-fingerprint",
    )


def test_parses_swagger2_parameters_responses_and_local_refs():
    spec = {
        "swagger": "2.0",
        "securityDefinitions": {"ApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}},
        "paths": {
            "/items": {
                "get": {
                    "parameters": [
                        {
                            "name": "page",
                            "in": "query",
                            "type": "integer",
                            "required": False,
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "schema": {"$ref": "#/definitions/Item"},
                            "examples": {"application/json": {"name": "sample"}},
                        }
                    },
                }
            }
        },
        "definitions": {
            "Item": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            }
        },
    }

    endpoints = parse_openapi_endpoints(spec, 7)

    assert endpoints == [
        {
            "id": "7_/items_GET",
            "path": "/items",
            "method": "GET",
            "request_schema": {
                "headers": {
                    "X-API-Key": {
                        "name": "X-API-Key",
                        "description": "",
                        "type": "string",
                        "required": True,
                        "in_": "header",
                    }
                },
                "query_params": {
                    "page": {
                        "name": "page",
                        "description": "",
                        "type": "integer",
                        "required": False,
                        "in_": "query",
                    }
                },
                "path_params": {},
                "cookie_params": {},
                "request_body": {},
            },
            "response_schemas": {
                "200": {
                    "code": "200",
                    "description": "ok",
                    "data_schema": {
                        "type": "object",
                        "required": ["name"],
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "",
                                "format": None,
                                "enum": None,
                            }
                        },
                        "description": "",
                    },
                    "examples": {"application/json": {"name": "sample"}},
                }
            },
            "example_response_data": {"name": "sample"},
            "example_request_string": None,
        }
    ]


def test_parses_openapi3_request_body_path_parameter_and_recursive_ref():
    spec = {
        "openapi": "3.0.3",
        "paths": {
            "/nodes/{node_id}": {
                "parameters": [
                    {
                        "name": "node_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "post": {
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Node"}}
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "created",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Node"},
                                    "example": {"name": "root"},
                                }
                            },
                        }
                    },
                },
            }
        },
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "children": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Node"},
                        },
                    },
                }
            }
        },
    }

    endpoint = parse_openapi_endpoints(spec, 7)[0]

    assert endpoint["request_schema"]["path_params"]["node_id"]["required"] is True
    assert endpoint["request_schema"]["request_body"]["required"] is True
    assert endpoint["request_schema"]["request_body"]["content"]["application/json"]["schema"][
        "properties"
    ]["children"]["items"] == {
        "$ref": "#/components/schemas/Node",
        "recursive": True,
    }
    assert endpoint["response_schemas"]["201"]["data_schema"]["type"] == "object"
    assert endpoint["example_response_data"] == {"name": "root"}


def test_normalizes_api_with_official_source_and_openapi_endpoints():
    detail = {
        "metadata": {"설명": ["detail description"]},
        "schema_org": [],
        "api_specs": [
            {
                "swagger": "2.0",
                "paths": {"/status": {"get": {"responses": {"200": {"description": "ok"}}}}},
            }
        ],
        "attachments": [],
        "tables": [],
        "detail_format": "SWAGGER",
    }
    source = {
        "record": {
            "id": "official-id",
            "title": "official title",
            "desc": "official description",
            "dept_nm": "data dept",
            "category_nm": "public admin",
            "data_format": "JSON",
            "keywords": "one,two",
            "request_cnt": "12",
            "is_charged": "무료",
        }
    }

    output = normalize_catalog(parse_input("API", detail, sources=[source]))

    assert output.collection == "parsed_api_info"
    assert output.document["id"] == "official-id"
    assert output.document["title"] == "official title"
    assert output.document["description"] == "official description"
    assert output.document["keywords"] == ["one", "two"]
    assert output.document["request_cnt"] == 12
    assert output.document["endpoints"][0]["path"] == "/status"
    assert output.document["source_fingerprint"] == "source-fingerprint"
    assert output.document["parser_version"] == PARSER_VERSION


def test_normalizes_file_distributions_columns_and_history():
    detail = {
        "metadata": {"설명": ["file description"], "확장자": ["CSV"]},
        "schema_org": [],
        "api_specs": [],
        "attachments": [{"name": "current.csv", "url": "/download/current"}],
        "tables": [
            {
                "caption": "컬럼 정보",
                "headers": ["컬럼명", "설명"],
                "rows": [["name", "이름"]],
            }
        ],
        "file_history_data": {
            "file_details": [{"name": "old.csv", "public_data_detail_pk": "old"}],
            "tables": [],
            "attachments": [],
        },
        "detail_popups": [
            {
                "descriptor": {"params": {"publicDataDetailPk": "old"}},
                "data": {"metadata": {"설명": ["old version"]}, "tables": []},
            }
        ],
        "detail_format": "TABLE",
    }

    output = normalize_catalog(parse_input("FILE", detail))

    assert output.collection == "parsed_file_info"
    assert output.document["data_type"] == "FILE"
    assert output.document["data_format"] == "CSV"
    assert output.document["distributions"][0]["name"] == "current.csv"
    assert output.document["columns"][0]["headers"] == ["컬럼명", "설명"]
    assert output.document["history"][0]["public_data_detail_pk"] == "old"
    assert output.document["history"][0]["metadata"]["설명"] == ["old version"]


def test_normalizes_standard_summary_and_emits_member_documents():
    detail = {
        "metadata": {"설명": ["standard description"]},
        "schema_org": [],
        "api_specs": [],
        "attachments": [],
        "tables": [{"caption": "표준항목", "headers": ["항목명"], "rows": [["주소"]]}],
        "standard_members": {
            "total": 2,
            "collected_count": 2,
            "items": [
                {"public_data_detail_pk": "member-a", "title": "기관 A"},
                {"public_data_detail_pk": "member-b", "title": "기관 B"},
            ],
        },
        "detail_popups": [
            {
                "descriptor": {"params": {"publicDataDetailPk": "member-a"}},
                "data": {
                    "metadata": {"제공기관": ["기관 A"], "설명": ["A 설명"]},
                    "tables": [{"caption": "컬럼", "headers": ["컬럼명"], "rows": [["addr"]]}],
                    "attachments": [],
                },
            }
        ],
        "detail_format": "TABLE",
    }

    output = normalize_catalog(parse_input("STD", detail))

    assert output.collection == "parsed_std_info"
    assert output.document["member_count"] == 2
    assert output.document["parsed_member_count"] == 1
    assert output.document["columns"][0]["caption"] == "표준항목"
    assert len(output.members) == 2
    assert output.members[0]["_id"] == "STD:7:member-a"
    assert output.members[0]["metadata"]["설명"] == ["A 설명"]
    assert output.members[1]["metadata"] == {}


def test_normalizes_linked_schema_org_and_dcat_resources():
    dcat = b"""<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
      xmlns:dct="http://purl.org/dc/terms/" xmlns:dcat="http://www.w3.org/ns/dcat#">
      <rdf:Description>
        <dct:publisher>Linked Agency</dct:publisher>
        <dct:license rdf:resource="https://license.example/open"/>
        <dcat:accessURL rdf:resource="https://linked.example/data"/>
      </rdf:Description>
    </rdf:RDF>"""
    detail = {
        "metadata": {"URL": ["https://linked.example"]},
        "schema_org": [
            {
                "@type": "Dataset",
                "name": "Linked title",
                "description": "Linked description",
                "license": "https://license.example/open",
            }
        ],
        "api_specs": [],
        "attachments": [],
        "tables": [],
        "detail_format": "LINK",
    }

    output = normalize_catalog(
        parse_input(
            "LINKED",
            detail,
            resources=[{"kind": "dcat", "url": "https://data.go.kr/dcat", "content": dcat}],
        )
    )

    assert output.collection == "parsed_linked_info"
    assert output.document["title"] == "Linked title"
    assert output.document["description"] == "Linked description"
    assert output.document["publishers"] == ["Linked Agency"]
    assert output.document["licenses"] == ["https://license.example/open"]
    assert output.document["access_urls"] == [
        "https://linked.example",
        "https://linked.example/data",
    ]


def test_partial_source_produces_partial_parsed_record_with_source_errors():
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [],
        "attachments": [],
        "tables": [],
        "detail_format": "LINK",
    }

    output = normalize_catalog(parse_input("LINKED", detail, detail_status="partial"))

    assert output.document["parse_status"] == "partial"
    assert output.document["parse_errors"] == [{"kind": "source"}]


def test_api_operation_table_fallback_builds_endpoint_without_swagger():
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [],
        "attachments": [],
        "tables": [],
        "operation_details": [
            {
                "operation": {"name": "목록 조회", "params": {"oprtinSeqNo": "3"}},
                "data": {
                    "metadata": {
                        "요청주소": ["https://api.example.test/items"],
                        "요청방식": ["GET"],
                    },
                    "tables": [
                        {
                            "caption": "요청변수",
                            "headers": [
                                "항목명(영문)",
                                "항목명(국문)",
                                "항목크기",
                                "항목구분",
                                "샘플데이터",
                                "항목설명",
                            ],
                            "rows": [["page", "페이지", "4", "0", "1", "페이지 번호"]],
                        },
                        {
                            "caption": "출력결과",
                            "headers": ["항목명(영문)", "항목명(국문)", "항목설명"],
                            "rows": [["name", "이름", "자료명"]],
                        },
                    ],
                },
            }
        ],
        "detail_format": "TABLE",
    }

    endpoint = normalize_catalog(parse_input("API", detail)).document["endpoints"][0]

    assert endpoint["path"] == "https://api.example.test/items"
    assert endpoint["method"] == "GET"
    assert endpoint["request_schema"]["query_params"]["page"]["required"] is False
    assert (
        endpoint["response_schemas"]["200"]["data_schema"]["properties"]["name"]["description"]
        == "자료명"
    )


def test_file_embedded_openapi_and_real_popup_request_shape_are_preserved():
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [
            {
                "openapi": "3.0.0",
                "paths": {"/files": {"get": {"responses": {"200": {"description": "ok"}}}}},
            }
        ],
        "attachments": [],
        "tables": [],
        "file_history_data": {
            "file_details": [{"public_data_detail_pk": "old", "name": "old.csv"}]
        },
        "detail_popups": [
            {
                "request": {"params": {"publicDataDetailPk": "old"}},
                "data": {"metadata": {"설명": ["old"]}, "tables": [], "attachments": []},
            }
        ],
        "detail_format": "SWAGGER",
    }

    document = normalize_catalog(parse_input("FILE", detail)).document

    assert document["endpoints"][0]["path"] == "/files"
    assert document["history"][0]["metadata"]["설명"] == ["old"]


def test_api_official_record_is_last_endpoint_fallback():
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [],
        "attachments": [],
        "tables": [],
        "detail_format": "METADATA",
    }
    source = {
        "record": {
            "operation_seq": 4,
            "operation_nm": "조회",
            "operation_url": "https://api.example.test/fallback",
            "request_param_nm_en": ["page", "size"],
        }
    }

    endpoint = normalize_catalog(parse_input("API", detail, sources=[source])).document[
        "endpoints"
    ][0]

    assert endpoint["id"] == "7_4_GET"
    assert endpoint["path"] == "https://api.example.test/fallback"
    assert list(endpoint["request_schema"]["query_params"]) == ["page", "size"]


def test_openapi_wins_over_operation_table_instead_of_duplicating_endpoint():
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [
            {
                "openapi": "3.0.0",
                "paths": {"/canonical": {"get": {"responses": {}}}},
            }
        ],
        "operation_details": [
            {
                "operation": {"name": "fallback"},
                "data": {"metadata": {}, "tables": []},
            }
        ],
        "attachments": [],
        "tables": [],
        "detail_format": "SWAGGER",
    }

    endpoints = normalize_catalog(parse_input("API", detail)).document["endpoints"]

    assert len(endpoints) == 1
    assert endpoints[0]["path"] == "/canonical"


def test_file_history_uses_detail_and_history_sequence_as_identity():
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [],
        "attachments": [],
        "tables": [],
        "file_history_data": {
            "file_details": [
                {
                    "public_data_detail_pk": "same",
                    "public_data_detail_sn": "1",
                },
                {
                    "public_data_detail_pk": "same",
                    "public_data_detail_sn": "2",
                },
            ]
        },
        "detail_popups": [
            {
                "request": {
                    "params": {
                        "publicDataDetailPk": "same",
                        "publicDataHistSn": "1",
                    }
                },
                "data": {"metadata": {"revision": ["one"]}},
            },
            {
                "request": {
                    "params": {
                        "publicDataDetailPk": "same",
                        "publicDataHistSn": "2",
                    }
                },
                "data": {"metadata": {"revision": ["two"]}},
            },
        ],
        "detail_format": "TABLE",
    }

    history = normalize_catalog(parse_input("FILE", detail)).document["history"]

    assert history[0]["metadata"]["revision"] == ["one"]
    assert history[1]["metadata"]["revision"] == ["two"]


def test_standard_member_preserves_listing_provider_date_and_metadata():
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [],
        "attachments": [],
        "tables": [],
        "standard_members": {
            "total": 1,
            "collected_count": 1,
            "items": [
                {
                    "public_data_detail_pk": "member",
                    "title": "Member",
                    "provider": "Agency",
                    "registered_at": "2026-09-01",
                    "metadata": {"source": ["listing"]},
                }
            ],
        },
        "detail_popups": [],
        "detail_format": "TABLE",
    }

    member = normalize_catalog(parse_input("STD", detail)).members[0]

    assert member["provider"] == "Agency"
    assert member["registered_at"] == "2026-09-01"
    assert member["metadata"] == {"source": ["listing"]}


def test_missing_source_dates_stay_null_and_are_not_invented_from_parse_time():
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [],
        "attachments": [],
        "tables": [],
        "detail_format": "TABLE",
    }

    document = normalize_catalog(parse_input("FILE", detail)).document

    assert document["created_at"] is None
    assert document["update_at"] is None


def test_invalid_linked_dcat_is_explicit_partial_error():
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [],
        "attachments": [],
        "tables": [],
        "detail_format": "LINK",
    }

    document = normalize_catalog(
        parse_input(
            "LINKED",
            detail,
            resources=[
                {
                    "kind": "dcat",
                    "url": "https://data.go.kr/broken-dcat",
                    "content": b"not xml",
                }
            ],
        )
    ).document

    assert document["parse_status"] == "partial"
    assert document["parse_errors"] == [
        {
            "kind": "dcat",
            "url": "https://data.go.kr/broken-dcat",
            "error": "Cannot parse DCAT resource",
        }
    ]
