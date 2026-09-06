"""Opt-in tests against a disposable database on a real MongoDB server.

Set MONGO_TEST_URL explicitly. Only a generated collector_test_<uuid> database
is created and dropped; this suite never uses MONGO_URL or MONGO_DB.
"""

import gzip
import json
import os
import uuid

import pytest
from pymongo import MongoClient
from test_store_pipeline import NOW, Details, Source, item

from opendata_collector.http import Resource
from opendata_collector.pipeline import Pipeline
from opendata_collector.store import MongoStore


@pytest.fixture
def real_store():
    url = os.environ.get("MONGO_TEST_URL")
    if not url:
        pytest.skip("Set MONGO_TEST_URL to run isolated real-Mongo integration tests")
    client = MongoClient(url, serverSelectionTimeoutMS=5000, tz_aware=True)
    database = client[f"collector_test_{uuid.uuid4().hex}"]
    connected = False
    try:
        client.admin.command("ping")
        connected = True
        yield MongoStore(database)
    finally:
        if connected:
            client.drop_database(database.name)
        client.close()


def test_real_mongo_resume_upsert_and_operation_preservation(real_store):
    db = real_store.db
    db.open_data_info.insert_one(
        {"_id": "existing-api", "list_id": 1, "is_parsed": "Y", "parsed_at": NOW}
    )
    first_operation = item(1, operation="1")
    first_operation["source_record"]["future_field"] = {"preserve": [1, 2]}
    source = Source(
        {
            ("API", 1): ([first_operation, item(1, operation="2")], 3),
            ("API", 2): ([item(2)], 3),
        }
    )
    details = Details(failures=["API:2"])
    first = Pipeline(source, real_store, details).run(types=["API"], page_size=2, max_pages=1)
    assert first["status"] == "paused"
    second = Pipeline(source, real_store, details).run(resume=first["run_id"])
    assert second["status"] == "incomplete"
    assert second["detail_failed"] == 1
    details.failures.clear()
    third = Pipeline(source, real_store, details).run(resume=first["run_id"])
    assert third["status"] == "completed"
    assert third["catalog_count"] == 2
    assert third["source_record_count"] == 3
    assert third["streams"]["API"]["verified"] is True
    assert details.calls == ["API:1", "API:2", "API:2"]

    raw_count = db.portal_raw.files.count_documents({})
    assert (
        Pipeline(source, real_store, details).run(types=["API"], page_size=2)["status"]
        == "completed"
    )
    assert db.portal_raw.files.count_documents({}) == raw_count
    assert db.portal_catalog.count_documents({}) == 2
    assert db.portal_source_records.count_documents({}) == 3
    assert db.open_data_info.count_documents({}) == 2
    previous = db.open_data_info.find_one({"list_id": 1})
    assert previous["_id"] == "existing-api"
    assert previous["is_parsed"] == "Y"
    assert previous["parsed_at"] == NOW
    source_row = db.portal_source_records.find_one({"_id": first_operation["source_id"]})
    assert source_row["record"]["future_field"] == {"preserve": [1, 2]}
    assert db.portal_locks.count_documents({}) == 0


def test_real_mongo_large_detail_and_binary_raw_round_trip(real_store):
    payload = "x" * (17 * 1024 * 1024)
    binary = os.urandom(1024 * 1024)

    class LargeDetails(Details):
        def collect(self, record, heartbeat=lambda: None):
            detail, _, errors = super().collect(record, heartbeat)
            detail["opaque_payload"] = payload
            raw = Resource(record["detail_url"], binary, "application/octet-stream", NOW)
            return detail, [raw], errors

    report = Pipeline(Source({("API", 1): ([item(1)], 1)}), real_store, LargeDetails()).run(
        types=["API"]
    )
    assert report["status"] == "completed"
    catalog = real_store.db.portal_catalog.find_one({"_id": "API:1"})
    detail = json.loads(gzip.decompress(real_store.raw.get(catalog["parsed_detail_ref"]).read()))
    assert detail["opaque_payload"] == payload
    resource = real_store.db.portal_resources.find_one({"catalog_id": "API:1"})
    assert gzip.decompress(real_store.raw.get(resource["raw_id"]).read()) == binary
    assert real_store.db.portal_raw.chunks.count_documents({"files_id": resource["raw_id"]}) > 1


def test_real_mongo_independent_writers_cannot_share_lease(real_store):
    other = MongoStore(real_store.db)
    real_store.acquire("first")
    with pytest.raises(RuntimeError, match="another collector"):
        other.acquire("second")
    real_store.release("first")
    other.acquire("second")
    other.heartbeat()
    other.release("second")


def test_real_mongo_refresh_updates_current_view_and_keeps_resource_history(real_store):
    class VersionedDetails(Details):
        content = b"revision-1"

        def collect(self, record, heartbeat=lambda: None):
            detail, _, errors = super().collect(record, heartbeat)
            detail["metadata"]["revision"] = [self.content.decode()]
            resource = Resource(
                record["detail_url"],
                self.content,
                "text/html",
                NOW,
                "detail_html",
            )
            return detail, [resource], errors

    source = Source({("API", 1): ([item(1), item(2)], 2)})
    details = VersionedDetails()
    first = Pipeline(source, real_store, details).run(types=["API"])
    previous_resource = real_store.db.portal_resources.find_one(
        {"catalog_id": "API:1", "is_active": True}
    )

    changed = item(1)
    changed["title"] = "Updated API"
    source.pages[("API", 1)] = ([changed], 1)
    details.content = b"revision-2"
    second = Pipeline(source, real_store, details).run(types=["API"])

    current = real_store.db.portal_catalog.find_one({"_id": "API:1"})
    removed = real_store.db.portal_catalog.find_one({"_id": "API:2"})
    removed_source = real_store.db.portal_source_records.find_one({"_id": item(2)["source_id"]})
    resources = list(real_store.db.portal_resources.find({"catalog_id": "API:1"}))
    active_resources = [row for row in resources if row["is_active"]]
    historical_resources = [row for row in resources if not row["is_active"]]

    assert first["status"] == second["status"] == "completed"
    assert current["title"] == "Updated API"
    assert current["metadata"]["revision"] == ["revision-2"]
    assert current["last_seen_run"] == second["run_id"]
    assert current["is_active"] is True
    assert removed["is_active"] is False
    assert removed["removed_at"] is not None
    assert removed_source["is_active"] is False
    assert len(active_resources) == len(historical_resources) == 1
    assert historical_resources[0]["_id"] == previous_resource["_id"]
    assert (
        gzip.decompress(real_store.raw.get(active_resources[0]["raw_id"]).read()) == b"revision-2"
    )


def test_real_mongo_collect_then_parse_all_catalog_types(real_store):
    from opendata_collector.parse_pipeline import ParsePipeline
    from opendata_collector.parse_store import ParseStore

    pages = {
        (kind, 1): ([item(number, kind)], 1)
        for number, kind in enumerate(("API", "FILE", "STD", "LINKED"), 1)
    }
    source = Source(pages)
    real_store.db.generated_api_docs.insert_one(
        {"_id": "sentinel", "list_id": 1, "markdown": "keep"}
    )

    collected = Pipeline(source, real_store, Details()).run(types=["API", "FILE", "STD", "LINKED"])
    parsed = ParsePipeline(ParseStore(real_store.db)).run(["API", "FILE", "STD", "LINKED"])
    repeated = ParsePipeline(ParseStore(real_store.db)).run(["API", "FILE", "STD", "LINKED"])

    assert collected["status"] == "completed"
    assert parsed["status"] == "completed"
    assert parsed["parsed"] == 4
    assert repeated["skipped"] == 4
    assert real_store.db.parsed_api_info.count_documents({}) == 1
    assert real_store.db.parsed_file_info.count_documents({}) == 1
    assert real_store.db.parsed_std_info.count_documents({}) == 1
    assert real_store.db.parsed_linked_info.count_documents({}) == 1
    assert real_store.db.generated_api_docs.find_one({"_id": "sentinel"})["markdown"] == "keep"
