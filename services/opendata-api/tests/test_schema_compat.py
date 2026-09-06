from datetime import datetime, timezone

import pytest
from opendata_collector.projection import project_legacy

from api.v1.application.catalog.catalog_service import CatalogService
from api.v1.application.open_data.documents_service import DocumentsAppService
from api.v1.application.open_data.dto import DocumentDetailDTO
from api.v1.domain.open_data.entities import (
    GeneratedDocMeta,
    RankedItem,
    UnifiedDataItem,
)
from models import OpenAPIInfo, OpenFileInfo

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
