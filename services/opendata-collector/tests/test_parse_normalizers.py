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
        "security": [{"ApiKey": []}],
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
                        "security_scheme": "ApiKey",
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
            "security": [{"ApiKey": []}],
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


def test_openapi_preserves_servers_operation_security_and_parameter_constraints():
    spec = {
        "openapi": "3.0.3",
        "servers": [{"url": "https://api.example.test/v1", "description": "production"}],
        "security": [{"ApiKey": []}],
        "paths": {
            "/items": {
                "get": {
                    "operationId": "listItems",
                    "summary": "항목 목록",
                    "description": "등록된 항목을 조회합니다.",
                    "tags": ["items"],
                    "deprecated": True,
                    "parameters": [
                        {
                            "name": "page",
                            "in": "query",
                            "description": "페이지 번호",
                            "schema": {
                                "type": "integer",
                                "format": "int32",
                                "default": 1,
                                "minimum": 1,
                                "maximum": 100,
                            },
                            "example": 2,
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {
                                                "type": "string",
                                                "default": "unknown",
                                                "example": "sample",
                                                "minLength": 1,
                                                "pattern": "^[a-z]+$",
                                            }
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {
            "securitySchemes": {
                "ApiKey": {
                    "type": "apiKey",
                    "in": "query",
                    "name": "serviceKey",
                    "description": "공공데이터포털 인증키",
                }
            }
        },
    }

    endpoint = parse_openapi_endpoints(spec, 7)[0]

    assert endpoint["name"] == "항목 목록"
    assert endpoint["description"] == "등록된 항목을 조회합니다."
    assert endpoint["operation_id"] == "listItems"
    assert endpoint["tags"] == ["items"]
    assert endpoint["deprecated"] is True
    assert endpoint["servers"] == [
        {"url": "https://api.example.test/v1", "description": "production"}
    ]
    assert endpoint["security"] == [{"ApiKey": []}]
    assert endpoint["request_schema"]["query_params"]["serviceKey"] == {
        "name": "serviceKey",
        "description": "공공데이터포털 인증키",
        "type": "string",
        "required": True,
        "in_": "query",
        "security_scheme": "ApiKey",
    }
    assert endpoint["request_schema"]["query_params"]["page"] == {
        "name": "page",
        "description": "페이지 번호",
        "type": "integer",
        "required": False,
        "in_": "query",
        "format": "int32",
        "default": 1,
        "example": 2,
        "minimum": 1,
        "maximum": 100,
    }
    assert endpoint["response_schemas"]["200"]["content_types"] == ["application/json"]
    response_property = endpoint["response_schemas"]["200"]["data_schema"]["properties"]["name"]
    assert response_property["default"] == "unknown"
    assert response_property["example"] == "sample"
    assert response_property["minLength"] == 1
    assert response_property["pattern"] == "^[a-z]+$"


def test_openapi_injects_only_effective_security_and_honors_public_override():
    spec = {
        "openapi": "3.0.3",
        "security": [{"UsedKey": []}],
        "paths": {
            "/secure": {"get": {"responses": {}}},
            "/public": {"get": {"security": [], "responses": {}}},
        },
        "components": {
            "securitySchemes": {
                "UsedKey": {"type": "apiKey", "in": "query", "name": "serviceKey"},
                "UnusedKey": {"type": "apiKey", "in": "header", "name": "X-Unused"},
            }
        },
    }

    endpoints = {endpoint["path"]: endpoint for endpoint in parse_openapi_endpoints(spec, 7)}

    assert set(endpoints["/secure"]["request_schema"]["query_params"]) == {"serviceKey"}
    assert endpoints["/secure"]["request_schema"]["headers"] == {}
    assert endpoints["/public"]["security"] == []
    assert endpoints["/public"]["request_schema"]["query_params"] == {}
    assert endpoints["/public"]["request_schema"]["headers"] == {}


def test_common_dates_skip_invalid_higher_priority_values():
    detail = {
        "metadata": {"등록일": ["2025-01-02"], "차기 등록 예정일": ["2025-02-03"]},
        "schema_org": [],
        "api_specs": [],
        "attachments": [],
        "tables": [],
        "detail_format": "TABLE",
    }
    sources = [{"record": {"created_at": "unknown", "next_registration_date": "unknown"}}]

    document = normalize_catalog(parse_input("FILE", detail, sources=sources)).document

    assert document["created_at"] == datetime(2025, 1, 2, tzinfo=timezone.utc)
    assert document["next_registration_date"] == datetime(2025, 2, 3, tzinfo=timezone.utc)


def test_common_metadata_promotes_document_context_without_discarding_raw_sources():
    detail = {
        "metadata": {
            "제공기관": ["공공기관"],
            "관리부서명": ["데이터부"],
            "관리부서 전화번호": ["02-0000-0000"],
            "보유근거": ["공공데이터법"],
            "수집방법": ["행정시스템"],
            "업데이트 주기": ["월간"],
            "차기 등록 예정일": ["2026-10-01"],
            "매체유형": ["텍스트"],
            "전체 행": ["1,234"],
            "데이터 한계": ["일부 공란"],
            "기타 유의사항": ["기준일 확인"],
            "공간범위": ["대한민국"],
            "시간범위": ["2025년"],
            "비용부과유무": ["무료"],
            "비용부과기준 및 단위": ["건"],
            "이용허락범위": ["출처표시"],
            "등록일": ["2025-01-02"],
            "수정일": ["2026-09-01"],
        },
        "schema_org": [
            {
                "@type": "Dataset",
                "name": "Schema title",
                "datePublished": "2025-01-03",
                "license": "https://license.example/open",
            },
            {"@type": "WebPage", "name": "상세 페이지"},
        ],
        "api_specs": [],
        "attachments": [{"name": "guide.pdf", "file_id": "guide"}],
        "tables": [],
        "detail_format": "TABLE",
    }

    document = normalize_catalog(parse_input("FILE", detail)).document

    assert document["organization"] == "공공기관"
    assert document["department"] == "데이터부"
    assert document["created_at"] == datetime(2025, 1, 2, tzinfo=timezone.utc)
    assert document["published_at"] == datetime(2025, 1, 3, tzinfo=timezone.utc)
    assert document["update_at"] == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert document["source_url"] == "https://www.data.go.kr/data/7/file.do"
    assert document["license"] == "https://license.example/open"
    assert document["ownership_grounds"] == "공공데이터법"
    assert document["collection_method"] == "행정시스템"
    assert document["update_cycle"] == "월간"
    assert document["next_registration_date"] == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert document["media_type"] == "텍스트"
    assert document["row_count"] == 1234
    assert document["data_limit"] == "일부 공란"
    assert document["notes"] == "기준일 확인"
    assert document["spatial_coverage"] == "대한민국"
    assert document["temporal_coverage"] == "2025년"
    assert document["pricing_basis"] == "건"
    assert document["contact"] == {"department": "데이터부", "phone": "02-0000-0000"}
    assert document["metadata"] == detail["metadata"]
    assert document["schema_org"] == detail["schema_org"][0]
    assert document["schema_org_raw"] == detail["schema_org"]
    assert document["distributions"] == detail["attachments"]


def test_common_contact_uses_source_and_schema_org_when_metadata_is_missing():
    source_detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [],
        "attachments": [],
        "tables": [],
        "detail_format": "TABLE",
    }
    source = {
        "record": {
            "dept_nm": "API부",
            "contact_tel": "02-1111-2222",
            "contact_email": "api@example.test",
            "cost_unit": "건당 10원",
        }
    }
    schema_detail = {
        **source_detail,
        "schema_org": [
            {
                "@type": "Dataset",
                "contactPoint": [
                    {"name": "데이터 담당자", "telephone": "02-3333-4444"},
                    {
                        "email": "data@example.test",
                        "contactType": "technical support",
                    },
                ],
            }
        ],
    }

    source_document = normalize_catalog(
        parse_input("FILE", source_detail, sources=[source])
    ).document
    schema_document = normalize_catalog(parse_input("FILE", schema_detail)).document

    assert source_document["contact"] == {
        "department": "API부",
        "phone": "02-1111-2222",
        "email": "api@example.test",
    }
    assert source_document["pricing_basis"] == "건당 10원"
    assert schema_document["contact"] == {
        "department": "summary org",
        "name": "데이터 담당자",
        "phone": "02-3333-4444",
        "email": "data@example.test",
        "type": "technical support",
    }


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


def test_matching_operation_table_enriches_openapi_endpoint_without_duplication():
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [
            {
                "openapi": "3.0.0",
                "servers": [{"url": "https://api.example.test/v1"}],
                "paths": {
                    "/items": {
                        "get": {
                            "parameters": [
                                {"name": "page", "in": "query", "schema": {"type": "integer"}}
                            ],
                            "responses": {
                                "200": {
                                    "description": "ok",
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {"name": {"type": "string"}},
                                            }
                                        }
                                    },
                                }
                            },
                        }
                    }
                },
            }
        ],
        "operation_details": [
            {
                "operation": {"name": "목록 조회", "params": {"oprtinSeqNo": "1"}},
                "data": {
                    "metadata": {
                        "요청주소": ["https://api.example.test/v1/items"],
                        "요청방식": ["GET"],
                    },
                    "tables": [
                        {
                            "caption": "요청변수",
                            "headers": ["항목명(영문)", "샘플데이터", "항목설명"],
                            "rows": [["page", "2", "페이지 번호"]],
                        },
                        {
                            "caption": "출력결과",
                            "headers": ["항목명(영문)", "항목설명"],
                            "rows": [["name", "자료명"]],
                        },
                    ],
                },
            }
        ],
        "attachments": [],
        "tables": [],
        "detail_format": "SWAGGER",
    }

    endpoints = normalize_catalog(parse_input("API", detail)).document["endpoints"]

    assert len(endpoints) == 1
    endpoint = endpoints[0]
    assert endpoint["path"] == "/items"
    assert endpoint["absolute_url"] == "https://api.example.test/v1/items"
    assert endpoint["name"] == "목록 조회"
    assert endpoint["request_schema"]["query_params"]["page"]["description"] == "페이지 번호"
    assert endpoint["request_schema"]["query_params"]["page"]["example"] == "2"
    assert (
        endpoint["response_schemas"]["200"]["data_schema"]["properties"]["name"]["description"]
        == "자료명"
    )
    assert endpoint["raw_tables"] == detail["operation_details"][0]["data"]["tables"]


def test_known_absolute_endpoint_does_not_suffix_match_another_api_version():
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [
            {
                "openapi": "3.0.0",
                "servers": [{"url": "https://api.example.test/v1"}],
                "paths": {"/items": {"get": {"responses": {}}}},
            }
        ],
        "operation_details": [
            {
                "operation": {"name": "v2", "url": "https://api.example.test/v2/items"},
                "data": {
                    "metadata": {"요청방식": ["GET"]},
                    "tables": [{"caption": "v2", "headers": [], "rows": []}],
                },
            }
        ],
        "attachments": [],
        "tables": [],
        "detail_format": "SWAGGER",
    }

    endpoints = normalize_catalog(parse_input("API", detail)).document["endpoints"]

    assert len(endpoints) == 2
    assert endpoints[0]["absolute_url"] == "https://api.example.test/v1/items"
    assert "raw_tables" not in endpoints[0]
    assert endpoints[1]["path"] == "https://api.example.test/v2/items"


def test_operation_table_matching_prefers_exact_server_url_over_ambiguous_suffix():
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [
            {
                "openapi": "3.0.0",
                "servers": [{"url": "https://api.example.test/v1"}],
                "paths": {"/items": {"get": {"responses": {}}}},
            }
        ],
        "operation_details": [
            {
                "operation": {"name": "v2", "url": "https://api.example.test/v2/items"},
                "data": {
                    "metadata": {"요청방식": ["GET"]},
                    "tables": [{"caption": "v2", "headers": [], "rows": []}],
                },
            },
            {
                "operation": {"name": "v1", "url": "https://api.example.test/v1/items"},
                "data": {
                    "metadata": {"요청방식": ["GET"]},
                    "tables": [{"caption": "v1", "headers": [], "rows": []}],
                },
            },
        ],
        "attachments": [],
        "tables": [],
        "detail_format": "SWAGGER",
    }

    endpoints = normalize_catalog(parse_input("API", detail)).document["endpoints"]

    assert endpoints[0]["path"] == "/items"
    assert endpoints[0]["absolute_url"] == "https://api.example.test/v1/items"
    assert endpoints[0]["name"] == "v1"
    assert endpoints[0]["raw_tables"][0]["caption"] == "v1"
    assert any(endpoint["path"].endswith("/v2/items") for endpoint in endpoints[1:])


def test_operation_table_enriches_array_schema_without_changing_openapi_structure():
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [
            {
                "openapi": "3.0.0",
                "paths": {
                    "/items": {
                        "get": {
                            "parameters": [
                                {"name": "page", "in": "query", "schema": {"type": "integer"}}
                            ],
                            "responses": {
                                "200": {
                                    "description": "ok",
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {"name": {"type": "string"}},
                                                },
                                            }
                                        }
                                    },
                                }
                            },
                        }
                    }
                },
            }
        ],
        "operation_details": [
            {
                "operation": {
                    "name": "목록 조회",
                    "url": "https://api.example.test/items",
                },
                "data": {
                    "metadata": {"요청방식": ["GET"]},
                    "tables": [
                        {
                            "caption": "요청변수",
                            "headers": ["항목명(영문)", "샘플데이터", "항목설명"],
                            "rows": [
                                ["page", "2", "페이지 번호"],
                                ["htmlOnly", "x", "명세에 없는 변수"],
                            ],
                        },
                        {
                            "caption": "출력결과",
                            "headers": ["항목명(영문)", "항목설명"],
                            "rows": [
                                ["name", "자료명"],
                                ["htmlOnly", "명세에 없는 결과"],
                            ],
                        },
                    ],
                },
            }
        ],
        "attachments": [],
        "tables": [],
        "detail_format": "SWAGGER",
    }

    endpoint = normalize_catalog(parse_input("API", detail)).document["endpoints"][0]
    query = endpoint["request_schema"]["query_params"]
    schema = endpoint["response_schemas"]["200"]["data_schema"]

    assert set(query) == {"page"}
    assert query["page"]["description"] == "페이지 번호"
    assert schema["type"] == "array"
    assert "properties" not in schema
    assert set(schema["items"]["properties"]) == {"name"}
    assert schema["items"]["properties"]["name"]["description"] == "자료명"
    assert endpoint["raw_tables"] == detail["operation_details"][0]["data"]["tables"]


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



def test_monthly_snapshot_fills_blanks_but_preserves_live_detail_and_provenance():
    detail = {
        "metadata": {
            "공간범위": ["detail spatial"],
            "분류체계": ["Detail category"],
            "등록일": ["2024-01-02"],
            "수정일": ["2024-02-03"],
        },
        "schema_org": [
            {
                "@type": "Dataset",
                "name": "Schema title",
                "creator": {"name": "Schema organization"},
                "dateCreated": "2024-01-01",
                "dateModified": "2024-02-01",
                "encodingFormat": "Schema format",
                "temporalCoverage": "detail temporal",
            }
        ],
        "api_specs": [],
        "attachments": [],
        "tables": [],
        "detail_format": "",
    }
    monthly_row = {
        "목록키": "7",
        "목록명": "Monthly title",
        "목록 URL": "https://monthly.example.test/7",
        "제공기관": "Monthly organization",
        "관리부서명": "Monthly department",
        "분류체계": "Monthly category",
        "확장자": "CSV",
        "등록일": "2025-01-02",
        "수정일": "2025-02-03",
        "이용허락범위": "Monthly license",
        "조회수": "1,234",
        "다운로드수": "56",
        "제공유형": "FILE",
        "표준데이터 여부": "Y",
        "공간범위": "monthly spatial",
        "시간범위": "monthly temporal",
        "서비스URL": "https://monthly.example.test/api",
    }
    output = normalize_catalog(
        parse_input(
            "API",
            detail,
            sources=[
                {"record": {}},
                {
                    "source": "monthly_snapshot",
                    "record": monthly_row,
                    "snapshot_run_id": "snapshot-run",
                    "snapshot_source": {"name": "monthly.csv"},
                    "snapshot_raw_sha256": "snapshot-hash",
                },
            ],
        )
    )

    assert output.document["title"] == "Schema title"
    assert output.document["organization"] == "Schema organization"
    assert output.document["department"] == "Monthly department"
    assert output.document["category"] == "Detail category"
    assert output.document["data_format"] == "Schema format"
    assert output.document["created_at"] == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert output.document["update_at"] == datetime(2024, 2, 1, tzinfo=timezone.utc)
    assert output.document["license"] == "Monthly license"
    assert output.document["request_cnt"] == 56
    assert output.document["view_count"] == 1234
    assert output.document["provision_type"] == "FILE"
    assert output.document["is_standard_data"] == "Y"
    assert output.document["spatial_coverage"] == "detail spatial"
    assert output.document["temporal_coverage"] == "detail temporal"
    assert output.document["service_urls"] == ["https://monthly.example.test/api"]
    assert output.document["monthly_snapshot"] == monthly_row
    assert output.document["snapshot_run_id"] == "snapshot-run"
    assert output.document["snapshot_source"] == {"name": "monthly.csv"}
    assert output.document["snapshot_raw_sha256"] == "snapshot-hash"



def test_monthly_snapshot_falls_back_for_contact_and_api_metadata():
    output = normalize_catalog(
        parse_input(
            "API",
            {
                "metadata": {"담당자명": ["Detail contact"]},
                "schema_org": [],
                "api_specs": [],
                "attachments": [],
                "tables": [],
                "detail_format": "TABLE",
            },
            sources=[
                {"record": {"contact_tel": "02-9999-9999", "api_type": "SOAP"}},
                {
                    "source": "monthly_snapshot",
                    "record": {
                        "관리부서명": "Monthly department",
                        "담당자명": "Monthly contact",
                        "관리부서 전화번호": "02-1111-2222",
                        "담당자 이메일": "monthly@example.test",
                        "API 유형": "REST",
                        "개발계정 자동승인": "Y",
                        "운영계정 자동승인": "N",
                        "일일 트래픽": "1,000",
                        "심의 여부": "Y",
                        "활용신청수": "88",
                    },
                },
            ],
        )
    ).document

    assert output["contact"] == {
        "department": "Monthly department",
        "name": "Detail contact",
        "phone": "02-9999-9999",
        "email": "monthly@example.test",
    }
    assert output["api_type"] == "SOAP"
    assert output["api_confirm_for_dev"] == "Y"
    assert output["api_confirm_for_prod"] == "N"
    assert output["traffic_limit"] == "1,000"
    assert output["review_status"] == "Y"
    assert output["request_cnt"] == 88
