from datetime import datetime, timezone

import pytest
from opendata_collector.parse_normalizers import (
    PARSER_VERSION,
    ParseInput,
    normalize_catalog,
)
from opendata_collector.projection import project_legacy

from api.v1.application.catalog.catalog_service import CatalogService
from api.v1.application.open_data.documents_service import DocumentsAppService
from api.v1.application.open_data.dto import DocumentDetailDTO
from api.v1.domain.open_data.entities import (
    GeneratedDocMeta,
    RankedItem,
    UnifiedDataItem,
)
from models import (
    OpenAPIInfo,
    OpenFileInfo,
    ParsedAPIInfo,
    ParsedEndpoint,
    ParsedFileInfo,
    ParsedLinkedInfo,
    ParsedSTDInfo,
    ParsedSTDMember,
    PortalCatalog,
)

NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def projected(kind="FILE"):
    item = {
        "catalog_id": f"{kind}:7",
        "list_id": 7,
        "data_type": kind,
        "title": "공개 자료",
        "detail_url": "https://www.data.go.kr/data/7/fileData.do",
        "summary": {"formats": ["CSV"]},
    }
    detail = {
        "metadata": {
            "확장자": ["CSV"],
            "관리부서 전화번호": ["02-1234-5678"],
        },
        "tables": [],
        "api_specs": [],
        "attachments": [{"name": "guide.pdf", "handler": "download"}],
    }
    return project_legacy(item, detail, NOW)[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_kind", ["CSV", "FILE", None])
async def test_file_rows_keep_kind_separate_from_format(database, legacy_kind):
    row = projected()
    row.pop("data_format", None)
    row["data_type"] = legacy_kind
    row["ext"] = "CSV"
    await database.open_file_info.insert_one({"_id": "legacy", **row})

    document = await OpenFileInfo.find_one({"list_id": 7})

    assert document.data_type == "FILE"
    assert document.data_format == "CSV"
    assert (await database.open_file_info.find_one({"_id": "legacy"}))[
        "data_type"
    ] == legacy_kind


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,model", [("FILE", OpenFileInfo), ("API", OpenAPIInfo)]
)
async def test_collected_fields_survive_model_and_response_serialization(
    database, kind, model
):
    row = projected(kind)
    document = model(**row)
    value = document.model_dump()
    assert value["source_catalog_id"] == f"{kind}:7"
    assert value["collected_at"] == NOW
    assert value["contact"] == "02-1234-5678"
    assert value["attachments"] == [
        {"name": "guide.pdf", "handler": "download"}
    ]
    response = DocumentDetailDTO(**value, generated_status=False).model_dump(
        by_alias=True, mode="json"
    )
    assert response["sourceCatalogId"] == f"{kind}:7"
    assert response["attachments"][0]["name"] == "guide.pdf"


@pytest.mark.parametrize("kind", ["STD", "LINKED"])
def test_all_domain_records_preserve_standard_and_linked_identity(kind):
    item = UnifiedDataItem(
        list_id=7,
        title="public",
        description=None,
        department=None,
        category=None,
        data_type=kind,
        data_format=None,
        pricing=None,
        copyright=None,
        third_party_copyright=None,
    )
    assert item.data_type == kind
    assert GeneratedDocMeta(7, kind).data_type == kind
    assert RankedItem(7, kind).data_type == kind


def test_invalid_domain_kind_is_not_silently_relabelled_as_api():
    with pytest.raises(ValueError):
        RankedItem(7, "unknown")


@pytest.mark.asyncio
async def test_collected_file_is_found_by_search_id_and_reports_csv(database):
    await database.open_file_info.insert_one({"_id": "FILE:7", **projected()})
    items = await CatalogService(database.client)._get_file_data(["7"])
    assert len(items) == 1
    assert items[0].data_type == "FILE"
    assert items[0].data_format == "CSV"


@pytest.mark.asyncio
async def test_existing_document_detail_includes_collected_metadata(database):
    await database.open_file_info.insert_one({"_id": "FILE:7", **projected()})
    value = await DocumentsAppService().get_std_doc_detail(list_id=7)
    response = DocumentDetailDTO(**value).model_dump(by_alias=True)
    assert response["sourceCatalogId"] == "FILE:7"
    assert response["dataFormat"] == "CSV"
    assert response["contact"] == "02-1234-5678"
    assert response["generatedStatus"] is False


@pytest.mark.asyncio
async def test_old_api_kind_field_does_not_break_the_api_collection(database):
    row = projected("API")
    row["data_type"] = "OPENAPI"
    await database.open_data_info.insert_one({"_id": "old-api", **row})

    document = await OpenAPIInfo.find_one({"list_id": 7})

    assert document.data_type == "API"
    assert (await database.open_data_info.find_one({"_id": "old-api"}))[
        "data_type"
    ] == "OPENAPI"


@pytest.mark.parametrize(
    "kind,model",
    [
        ("API", ParsedAPIInfo),
        ("FILE", ParsedFileInfo),
        ("STD", ParsedSTDInfo),
        ("LINKED", ParsedLinkedInfo),
    ],
)
def test_parser_outputs_validate_against_api_models(kind, model):
    detail = {
        "metadata": {
            "설명": ["description"],
            "이용허락범위": ["출처표시"],
            "등록일": ["2025-01-02"],
        },
        "schema_org": [
            {"@type": "Dataset", "name": "public"},
            {"@type": "WebPage", "name": "detail page"},
        ],
        "api_specs": [],
        "attachments": [],
        "tables": [],
        "standard_members": {
            "total": 0,
            "collected_count": 0,
            "items": [],
        },
        "detail_popups": [],
        "detail_format": "TABLE",
    }
    value = normalize_catalog(
        ParseInput(
            catalog={
                "_id": f"{kind}:7",
                "data_type": kind,
                "list_id": 7,
                "title": "public",
                "summary": {},
                "detail_url": "https://www.data.go.kr/data/7/detail.do",
                "detail_status": "completed",
                "detail_errors": [],
            },
            detail=detail,
            source_fingerprint="fingerprint",
        )
    )

    document = model.model_validate(value.document)

    assert document.source_catalog_id == f"{kind}:7"
    assert document.parser_version == PARSER_VERSION
    assert document.parse_status == "completed"
    assert document.source_url == "https://www.data.go.kr/data/7/detail.do"
    assert document.license == "출처표시"
    assert document.created_at == datetime(2025, 1, 2, tzinfo=timezone.utc)
    assert len(document.schema_org_raw) == 2
    assert document.schema_org_raw[1]["@type"] == "WebPage"


def test_enriched_endpoint_fields_survive_api_model_validation():
    endpoint = ParsedEndpoint.model_validate(
        {
            "id": "7_/items_GET",
            "path": "/items",
            "method": "GET",
            "name": "목록 조회",
            "description": "항목을 조회합니다.",
            "operation_id": "listItems",
            "tags": ["items"],
            "servers": [{"url": "https://api.example.test/v1"}],
            "security": [{"ApiKey": []}],
            "deprecated": False,
            "absolute_url": "https://api.example.test/v1/items",
            "request_schema": {},
            "response_schemas": {},
        }
    )

    assert endpoint.description == "항목을 조회합니다."
    assert endpoint.operation_id == "listItems"
    assert endpoint.tags == ["items"]
    assert endpoint.servers == [{"url": "https://api.example.test/v1"}]
    assert endpoint.security == [{"ApiKey": []}]
    assert endpoint.deprecated is False
    assert endpoint.absolute_url == "https://api.example.test/v1/items"


def test_standard_member_output_validates_against_api_model():
    member = {
        "_id": "STD:7:a",
        "source_catalog_id": "STD:7",
        "list_id": 7,
        "public_data_detail_pk": "a",
        "title": "member",
        "provider": "Agency",
        "registered_at": "2026-09-01",
        "source_record": {"provider": "Agency"},
        "detail_status": "completed",
        "metadata": {},
        "columns": [],
        "distributions": [],
        "source_fingerprint": "fingerprint",
        "parser_version": "1",
        "parsed_at": NOW,
        "is_active": True,
    }

    document = ParsedSTDMember.model_validate(member)

    assert document.public_data_detail_pk == "a"
    assert document.provider == "Agency"
    assert document.source_record == {"provider": "Agency"}
    assert document.detail_status == "completed"
    assert document.is_active is True


def test_file_and_catalog_models_preserve_parse_status():
    file_value = OpenFileInfo.model_validate(
        {**projected(), "is_parsed": "Y", "parsed_at": NOW}
    ).model_dump()
    catalog_value = PortalCatalog.model_validate(
        {
            "_id": "FILE:7",
            "data_type": "FILE",
            "list_id": 7,
            "title": "public",
            "detail_url": "https://www.data.go.kr/data/7/fileData.do",
            "parse_status": "partial",
            "parse_errors": [{"kind": "dcat"}],
            "parsed_at": NOW,
            "parser_version": "1",
            "source_fingerprint": "fingerprint",
        }
    ).model_dump()

    assert file_value["is_parsed"] == "Y"
    assert file_value["parsed_at"] == NOW
    assert catalog_value["parse_status"] == "partial"
    assert catalog_value["parse_errors"] == [{"kind": "dcat"}]
    assert catalog_value["parser_version"] == "1"



def test_parsed_api_model_serializes_monthly_snapshot_provenance_and_flags():
    output = normalize_catalog(
        ParseInput(
            catalog={
                "_id": "API:7",
                "data_type": "API",
                "list_id": 7,
                "title": "public",
                "summary": {},
                "detail_url": "https://www.data.go.kr/data/7/detail.do",
                "detail_status": "completed",
                "detail_errors": [],
            },
            detail={"metadata": {}, "schema_org": [], "api_specs": [], "attachments": [], "tables": []},
            source_records=[
                {
                    "source": "monthly_snapshot",
                    "record": {"목록명": "monthly", "조회수": "9", "제공유형": "FILE"},
                    "snapshot_run_id": "snapshot-run",
                    "snapshot_source": {"name": "monthly.csv"},
                    "snapshot_raw_sha256": "snapshot-hash",
                }
            ],
            source_fingerprint="fingerprint",
        )
    )

    document = ParsedAPIInfo.model_validate(output.document).model_dump(mode="json")

    assert document["monthly_snapshot"] == {"목록명": "monthly", "조회수": "9", "제공유형": "FILE"}
    assert document["snapshot_run_id"] == "snapshot-run"
    assert document["snapshot_source"] == {"name": "monthly.csv"}
    assert document["snapshot_raw_sha256"] == "snapshot-hash"
    assert document["view_count"] == 9
    assert document["provision_type"] == "FILE"
