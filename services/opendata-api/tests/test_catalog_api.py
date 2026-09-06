import gzip
import json
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from gridfs import GridFS
from mongomock.gridfs import enable_gridfs_integration
from opendata_collector.http import Resource
from opendata_collector.store import MongoStore

from api.v1.application.catalog.portal_catalog_service import (
    PortalCatalogService,
)
from api.v1.routers.catalog import catalog_router, get_catalog_service

enable_gridfs_integration()
NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def seed(database, kind="API", number=7, *, errors=None):
    store = MongoStore(database.delegate)
    store.initialize()
    run = store.start_run("portal", [kind], 100)
    item = {
        "catalog_id": f"{kind}:{number}",
        "data_type": kind,
        "list_id": number,
        "title": f"공개 자료 {kind}",
        "detail_url": f"https://www.data.go.kr/data/{number}/openapi.do",
        "summary": {},
        "source_id": f"source:{kind}:{number}",
        "source_record": {
            "list_id": str(number),
            "unknown_field": {"keep": True},
        },
    }
    raw = Resource(
        item["detail_url"], b"<h1>public</h1>", "text/html", NOW, "detail_html"
    )
    page = {"items": [item], "page": 1, "source": "portal"}
    store.save_page(run["_id"], kind, page, raw)
    detail = {
        "metadata": {"데이터 포맷": ["JSON"], "확장자": ["CSV"]},
        "schema_org": [],
        "api_specs": [
            {
                "openapi": "3.0.0",
                "paths": {"/items": {"get": {"summary": "원문"}}},
            }
        ],
        "attachments": [{"name": "guide.pdf"}],
        "tables": [],
        "unrecognized_section": {"retained": [1, 2]},
    }
    store.save_detail(run["_id"], item, detail, [raw], errors or [])
    if not errors:
        store.finalize_snapshot(run["_id"])
    return item


@pytest_asyncio.fixture
async def client(database):
    app = FastAPI()
    app.include_router(catalog_router, prefix="/api/v1")
    app.dependency_overrides[get_catalog_service] = lambda: (
        PortalCatalogService(database)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as http:
        yield http


@pytest.mark.asyncio
async def test_all_types_sharing_numeric_id_are_listed_once_and_paginated(
    client, database
):
    for kind in ("API", "FILE", "STD", "LINKED"):
        seed(database, kind)
    page1 = (await client.get("/api/v1/catalog", params={"size": 2})).json()
    page2 = (
        await client.get("/api/v1/catalog", params={"size": 2, "page": 2})
    ).json()
    assert page1["total"] == page2["total"] == 4
    assert page1["hasNext"] is True
    assert page2["hasNext"] is False
    assert {row["catalogId"] for row in page1["items"] + page2["items"]} == {
        "API:7",
        "FILE:7",
        "STD:7",
        "LINKED:7",
    }
    assert all("detail" not in row for row in page1["items"])
    filtered = (
        await client.get("/api/v1/catalog", params={"data_type": "STD"})
    ).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["dataType"] == "STD"


@pytest.mark.asyncio
async def test_listing_keyword_is_literal_and_empty_page_has_correct_counts(
    client, database
):
    seed(database, "LINKED")
    found = (
        await client.get("/api/v1/catalog", params={"q": "공개 자료"})
    ).json()
    assert found["total"] == 1
    literal = (await client.get("/api/v1/catalog", params={"q": ".*"})).json()
    assert literal["total"] == 0
    beyond = (await client.get("/api/v1/catalog", params={"page": 2})).json()
    assert beyond["items"] == []
    assert beyond["total"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["API", "FILE", "STD", "LINKED"])
async def test_detail_reconstructs_complete_parsed_metadata(
    client, database, kind
):
    seed(database, kind)
    response = await client.get(f"/api/v1/catalog/{kind}/7")
    assert response.status_code == 200
    result = response.json()
    assert result["catalogId"] == f"{kind}:7"
    assert result["dataType"] == kind
    assert result["schemaVersion"] == 2
    assert result["detailStatus"] == "completed"
    assert (
        result["detail"]["api_specs"][0]["paths"]["/items"]["get"]["summary"]
        == "원문"
    )
    assert result["detail"]["unrecognized_section"] == {"retained": [1, 2]}
    if kind == "FILE":
        assert result["dataFormat"] == "CSV"


@pytest.mark.asyncio
async def test_source_and_raw_resources_preserve_fields(client, database):
    seed(database)
    sources = (await client.get("/api/v1/catalog/API/7/sources")).json()
    assert sources["total"] == 1
    assert sources["items"][0]["record"]["unknown_field"] == {"keep": True}
    resources = (await client.get("/api/v1/catalog/API/7/resources")).json()
    assert resources["total"] == 1
    resource_id = resources["items"][0]["resourceId"]
    raw = await client.get(f"/api/v1/catalog/API/7/resources/{resource_id}/raw")
    assert raw.status_code == 200
    assert raw.content == b"<h1>public</h1>"
    assert raw.headers["content-type"] == "application/octet-stream"
    assert raw.headers["content-disposition"].startswith("attachment;")
    assert raw.headers["x-content-type-options"] == "nosniff"
    seed(database, "FILE")
    other = await client.get(
        f"/api/v1/catalog/FILE/7/resources/{resource_id}/raw"
    )
    assert other.status_code == 404


@pytest.mark.asyncio
async def test_old_catalog_documents_are_readable_and_partial_status_is_exposed(
    client, database
):
    seed(database, "FILE", errors=[{"kind": "dcat", "error": "HTTP 503"}])
    await database.portal_catalog.update_one(
        {"_id": "FILE:7"},
        {
            "$unset": {
                "schema_version": "",
                "data_format": "",
                "is_active": "",
                "removed_at": "",
                "last_seen_run": "",
            }
        },
    )
    result = (await client.get("/api/v1/catalog/FILE/7")).json()
    assert result["schemaVersion"] == 1
    assert result["isActive"] is True
    assert result["removedAt"] is None
    assert result["dataFormat"] == "CSV"
    assert result["detailStatus"] == "partial"
    assert result["detailErrors"] == [{"kind": "dcat", "error": "HTTP 503"}]


@pytest.mark.asyncio
async def test_missing_records_and_invalid_parameters_have_explicit_statuses(
    client,
):
    for suffix in ("", "/sources", "/resources"):
        assert (
            await client.get(f"/api/v1/catalog/STD/7{suffix}")
        ).status_code == 404
    for url in (
        "/api/v1/catalog?data_type=BAD",
        "/api/v1/catalog?size=101",
        "/api/v1/catalog?page=0",
        "/api/v1/catalog/BAD/7",
    ):
        assert (await client.get(url)).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [b"broken gzip", gzip.compress(b"[]"), gzip.compress(b"invalid json")],
)
async def test_corrupt_stored_detail_is_reported_as_unavailable(
    client, database, payload
):
    seed(database)
    fs = GridFS(database.delegate, collection="portal_raw")
    fs.put(payload, _id="corrupt")
    await database.portal_catalog.update_one(
        {"_id": "API:7"}, {"$set": {"parsed_detail_ref": "corrupt"}}
    )
    response = await client.get("/api/v1/catalog/API/7")
    assert response.status_code == 503
    assert "traceback" not in json.dumps(response.json()).lower()


@pytest.mark.asyncio
async def test_malformed_catalog_shape_returns_controlled_unavailable(
    client, database
):
    seed(database)
    await database.portal_catalog.update_one(
        {"_id": "API:7"}, {"$set": {"metadata": ["not", "a", "mapping"]}}
    )
    response = await client.get("/api/v1/catalog")
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Collected metadata is temporarily unavailable"
    }


@pytest.mark.asyncio
async def test_resource_without_raw_reference_returns_controlled_unavailable(
    client, database
):
    seed(database)
    resource = await database.portal_resources.find_one({"catalog_id": "API:7"})
    await database.portal_resources.update_one(
        {"_id": resource["_id"]}, {"$unset": {"raw_id": ""}}
    )

    listing = await client.get("/api/v1/catalog/API/7/resources")
    raw = await client.get(
        f"/api/v1/catalog/API/7/resources/{resource['_id']}/raw"
    )

    assert listing.status_code == 503
    assert raw.status_code == 503
    assert raw.json() == {
        "detail": "Collected metadata is temporarily unavailable"
    }


@pytest.mark.asyncio
async def test_inactive_catalog_is_hidden_from_current_catalog_routes(
    client, database
):
    seed(database)
    resource = await database.portal_resources.find_one({"catalog_id": "API:7"})
    await database.portal_catalog.update_one(
        {"_id": "API:7"},
        {"$set": {"is_active": False, "removed_at": NOW}},
    )

    listing = await client.get("/api/v1/catalog")
    assert listing.status_code == 200
    assert listing.json()["total"] == 0
    for url in (
        "/api/v1/catalog/API/7",
        "/api/v1/catalog/API/7/sources",
        "/api/v1/catalog/API/7/resources",
        f"/api/v1/catalog/API/7/resources/{resource['_id']}/raw",
    ):
        assert (await client.get(url)).status_code == 404


@pytest.mark.asyncio
async def test_inactive_source_and_resource_history_is_hidden(client, database):
    seed(database)
    source = await database.portal_source_records.find_one(
        {"catalog_id": "API:7"}
    )
    resource = await database.portal_resources.find_one({"catalog_id": "API:7"})
    stale_source = {**source, "_id": "stale-source", "is_active": False}
    stale_resource = {**resource, "_id": "stale-resource", "is_active": False}
    await database.portal_source_records.insert_one(stale_source)
    await database.portal_resources.insert_one(stale_resource)

    sources = (await client.get("/api/v1/catalog/API/7/sources")).json()
    resources = (await client.get("/api/v1/catalog/API/7/resources")).json()
    stale_raw = await client.get(
        "/api/v1/catalog/API/7/resources/stale-resource/raw"
    )
    assert sources["total"] == 1
    assert resources["total"] == 1
    assert stale_raw.status_code == 404
