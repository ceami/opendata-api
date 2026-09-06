from datetime import datetime, timezone

import mongomock
import pytest
from mongomock.gridfs import enable_gridfs_integration

from opendata_collector.http import Resource
from opendata_collector.pipeline import Pipeline
from opendata_collector.store import MongoStore

enable_gridfs_integration()
NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def item(number, kind="API", operation=None):
    return {
        "catalog_id": f"{kind}:{number}",
        "list_id": number,
        "data_type": kind,
        "source_id": f"{kind}:{number}:{operation or ''}",
        "source_record": {"list_id": str(number), "operation_seq": operation},
        "title": f"Dataset {number}",
        "detail_url": f"https://www.data.go.kr/data/{number}/openapi.do",
        "summary": {},
    }


class Source:
    mode = "portal"

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def page(self, kind, page, size):
        self.calls.append((kind, page))
        value = self.pages[(kind, page)]
        if isinstance(value, Exception):
            raise value
        rows, total = value
        return (
            {
                "items": rows,
                "total": total,
                "source": self.mode,
                "page": page,
                "page_size": size,
                "member_total": None,
            },
            Resource(
                "https://www.data.go.kr/tcs/dss/selectDataSetList.do",
                repr(rows).encode(),
                "text/html",
                NOW,
                "catalog_html",
            ),
        )


class Details:
    def __init__(self, failures=()):
        self.failures, self.calls = set(failures), []

    def collect(self, record, heartbeat=lambda: None):
        self.calls.append(record["catalog_id"])
        if record["catalog_id"] in self.failures:
            raise ValueError("Missing metadata")
        return (
            {
                "metadata": {"OpenAPI 명": [record["title"]]},
                "schema_org": [],
                "api_specs": [],
                "attachments": [],
                "detail_format": "LINK",
            },
            [],
            [],
        )


@pytest.fixture
def store():
    return MongoStore(mongomock.MongoClient(tz_aware=True).audit)


def test_repeated_ingestion_retains_one_catalog_and_ai_state(store):
    store.db.open_data_info.insert_one(
        {"_id": "old", "list_id": 1, "is_parsed": "Y", "parsed_at": NOW}
    )
    source = Source({("API", 1): ([item(1)], 1)})
    for _ in range(2):
        report = Pipeline(source, store, Details()).run(types=["API"], page_size=2)
        assert report["status"] == "completed"
    assert store.db.portal_catalog.count_documents({}) == 1
    assert store.db.portal_source_records.count_documents({}) == 1
    assert store.db.open_data_info.count_documents({}) == 1
    assert store.db.open_data_info.find_one({"list_id": 1})["is_parsed"] == "Y"
    assert store.db.open_data_info.find_one({"list_id": 1})["_id"] == "old"


def test_page_limit_is_paused_and_resume_does_not_repeat_committed_page(store):
    source = Source({("API", 1): ([item(1), item(2)], 3), ("API", 2): ([item(3)], 3)})
    details = Details()
    first = Pipeline(source, store, details).run(types=["API"], page_size=2, max_pages=1)
    assert first["status"] == "paused"
    second = Pipeline(source, store, details).run(resume=first["run_id"])
    assert second["status"] == "completed"
    assert source.calls == [("API", 1), ("API", 2), ("API", 1), ("API", 2)]
    assert sorted(details.calls) == ["API:1", "API:2", "API:3"]


def test_detail_failure_remains_visible_and_resume_retries_only_failed_item(store):
    source = Source({("API", 1): ([item(1), item(2)], 2)})
    details = Details(failures=["API:2"])
    first = Pipeline(source, store, details).run(types=["API"], page_size=2)
    assert first["status"] == "incomplete"
    assert first["detail_failed"] == 1
    failed_catalog = store.db.portal_catalog.find_one({"_id": "API:2"})
    assert failed_catalog["detail_status"] == "failed"
    assert failed_catalog["detail_errors"] == [{"error": "Missing metadata"}]
    details.failures.clear()
    second = Pipeline(source, store, details).run(resume=first["run_id"])
    assert second["status"] == "completed"
    recovered_catalog = store.db.portal_catalog.find_one({"_id": "API:2"})
    assert recovered_catalog["detail_status"] == "completed"
    assert recovered_catalog["detail_errors"] == []
    assert details.calls == ["API:1", "API:2", "API:2"]
    assert source.calls == [("API", 1), ("API", 1)]


def test_same_numeric_id_across_types_and_operations_are_not_lost(store):
    source = Source(
        {
            ("API", 1): ([item(1, operation="1"), item(1, operation="2")], 2),
            ("FILE", 1): ([item(1, "FILE")], 1),
        }
    )
    report = Pipeline(source, store, Details()).run(types=["API", "FILE"], page_size=2)
    assert report["status"] == "completed"
    assert report["catalog_count"] == 2
    assert report["source_record_count"] == 3
    assert store.db.portal_source_records.count_documents({"catalog_id": "API:1"}) == 2


def test_repeated_cross_page_record_cannot_report_complete(store):
    source = Source({("API", 1): ([item(1), item(2)], 3), ("API", 2): ([item(2)], 3)})
    report = Pipeline(source, store, Details()).run(types=["API"], page_size=2)
    assert report["status"] == "incomplete"
    assert report["streams"]["API"]["unique_records"] == 2
    assert report["streams"]["API"]["expected_total"] == 3


def test_total_changes_fail_closed_even_if_new_total_was_reached(store):
    source = Source({("API", 1): ([item(1), item(2)], 3), ("API", 2): ([item(3), item(4)], 4)})
    report = Pipeline(source, store, Details()).run(types=["API"], page_size=2)
    assert report["status"] == "incomplete"
    assert report["streams"]["API"]["count_changed"] is True


def test_failed_listing_page_is_not_checkpointed(store):
    source = Source({("API", 1): ValueError("Unexpected empty page")})
    first = Pipeline(source, store, Details()).run(types=["API"], page_size=2)
    assert first["status"] == "incomplete"
    assert first["streams"]["API"]["next_page"] == 1
    source.pages[("API", 1)] = ([item(1)], 1)
    second = Pipeline(source, store, Details()).run(resume=first["run_id"])
    assert second["status"] == "completed"


def test_partial_supplement_failure_preserves_raw_and_retries(store):
    class PartialDetails:
        def collect(self, record, heartbeat=lambda: None):
            raw = Resource(record["detail_url"], b"<html>public detail</html>", "text/html", NOW)
            return (
                {"metadata": {}, "schema_org": [], "api_specs": [], "attachments": []},
                [raw],
                [{"kind": "dcat", "error": "HTTP 503"}],
            )

    report = Pipeline(Source({("API", 1): ([item(1)], 1)}), store, PartialDetails()).run(
        types=["API"]
    )
    assert report["status"] == "incomplete"
    assert store.db.portal_resources.count_documents({"catalog_id": "API:1"}) == 1
    assert store.db.portal_catalog.find_one({"_id": "API:1"})["detail_status"] == "partial"


def test_only_one_active_writer_holds_the_database_lease(store):
    store.acquire("first")
    with pytest.raises(RuntimeError, match="another collector"):
        store.acquire("second")
    store.release("first")
    store.acquire("second")
    store.release("second")


def test_detail_limit_leaves_unprocessed_records_pending(store):
    report = Pipeline(Source({("API", 1): ([item(1), item(2)], 2)}), store, Details()).run(
        types=["API"], page_size=2, max_details=1
    )
    assert report["status"] == "paused"
    assert report["detail_pending"] == 1


def test_same_total_replacement_during_scan_is_detected_by_final_verification(store):
    class ChangingSource(Source):
        def page(self, kind, page, size):
            result = super().page(kind, page, size)
            if page == 2:
                self.pages[("API", 1)] = ([item(9), item(1)], 4)
            return result

    source = ChangingSource(
        {("API", 1): ([item(1), item(2)], 4), ("API", 2): ([item(3), item(4)], 4)}
    )
    report = Pipeline(source, store, Details()).run(types=["API"], page_size=2)
    assert report["status"] == "incomplete"
    assert report["streams"]["API"]["snapshot_changed"] is True


def test_stable_run_requires_verified_membership_before_completion(store):
    source = Source({("API", 1): ([item(1)], 1)})
    report = Pipeline(source, store, Details()).run(types=["API"])
    assert report["status"] == "completed"
    assert report["streams"]["API"]["verified"] is True
    assert source.calls == [("API", 1), ("API", 1)]


def test_new_run_updates_values_and_preserves_ai_state(store):
    store.db.open_data_info.insert_one(
        {
            "_id": "existing-api",
            "list_id": 1,
            "is_parsed": "Y",
            "parsed_at": NOW,
            "ai_state": {"version": 3},
        }
    )
    source = Source({("API", 1): ([item(1)], 1)})
    first = Pipeline(source, store, Details()).run(types=["API"])
    previous_ref = store.db.portal_catalog.find_one({"_id": "API:1"})["parsed_detail_ref"]

    changed = item(1)
    changed["title"] = "Renamed dataset"
    changed["source_record"]["future_field"] = {"revision": 2}
    source.pages[("API", 1)] = ([changed], 1)
    second = Pipeline(source, store, Details()).run(types=["API"])

    catalog = store.db.portal_catalog.find_one({"_id": "API:1"})
    source_record = store.db.portal_source_records.find_one({"_id": changed["source_id"]})
    legacy = store.db.open_data_info.find_one({"list_id": 1})
    assert first["status"] == second["status"] == "completed"
    assert catalog["title"] == "Renamed dataset"
    assert catalog["metadata"]["OpenAPI 명"] == ["Renamed dataset"]
    assert catalog["parsed_detail_ref"] != previous_ref
    assert catalog["last_seen_run"] == second["run_id"]
    assert source_record["record"]["future_field"] == {"revision": 2}
    assert source_record["last_seen_run"] == second["run_id"]
    assert legacy["_id"] == "existing-api"
    assert legacy["title"] == "Renamed dataset"
    assert legacy["is_parsed"] == "Y"
    assert legacy["parsed_at"] == NOW
    assert legacy["ai_state"] == {"version": 3}


def test_incomplete_update_keeps_old_snapshot_then_complete_update_marks_removed(store):
    source = Source({("API", 1): ([item(1), item(2)], 2)})
    assert Pipeline(source, store, Details()).run(types=["API"])["status"] == "completed"

    source.pages[("API", 1)] = ValueError("Temporary listing failure")
    incomplete = Pipeline(source, store, Details()).run(types=["API"])
    assert incomplete["status"] == "incomplete"
    assert store.db.portal_catalog.find_one({"_id": "API:2"})["is_active"] is True

    source.pages[("API", 1)] = ([item(1)], 1)
    refreshed = Pipeline(source, store, Details()).run(types=["API"])
    current = store.db.portal_catalog.find_one({"_id": "API:1"})
    removed = store.db.portal_catalog.find_one({"_id": "API:2"})
    removed_source = store.db.portal_source_records.find_one({"_id": item(2)["source_id"]})
    assert refreshed["status"] == "completed"
    assert current["is_active"] is True
    assert current.get("removed_at") is None
    assert removed["is_active"] is False
    assert removed["removed_at"] is not None
    assert removed_source["is_active"] is False
    assert removed_source["removed_at"] is not None


def test_complete_detail_update_replaces_current_resource_without_deleting_history(store):
    class VersionedDetails(Details):
        content = b"revision-1"

        def collect(self, record, heartbeat=lambda: None):
            detail, _, errors = super().collect(record, heartbeat)
            resource = Resource(
                record["detail_url"],
                self.content,
                "text/html",
                NOW,
                "detail_html",
            )
            return detail, [resource], errors

    source = Source({("API", 1): ([item(1)], 1)})
    details = VersionedDetails()
    Pipeline(source, store, details).run(types=["API"])
    details.content = b"revision-2"
    second = Pipeline(source, store, details).run(types=["API"])

    resources = list(store.db.portal_resources.find({"catalog_id": "API:1"}))
    current = [row for row in resources if row.get("is_active", True)]
    history = [row for row in resources if row.get("is_active") is False]
    assert second["status"] == "completed"
    assert len(resources) == 2
    assert len(current) == len(history) == 1
    assert current[0]["last_seen_run"] == second["run_id"]
    assert history[0]["removed_at"] is not None


def test_successful_retry_replaces_partial_resources_within_the_same_run(store):
    class RetriedDetails(Details):
        partial = True

        def collect(self, record, heartbeat=lambda: None):
            detail, _, _ = super().collect(record, heartbeat)
            resources = [
                Resource(record["detail_url"] + "/kept", b"kept", "text/html", NOW),
            ]
            errors = []
            if self.partial:
                resources.append(
                    Resource(
                        record["detail_url"] + "/partial-only",
                        b"partial",
                        "text/html",
                        NOW,
                    )
                )
                errors = [{"kind": "supplement", "error": "temporary"}]
            return detail, resources, errors

    source = Source({("API", 1): ([item(1)], 1)})
    details = RetriedDetails()
    first = Pipeline(source, store, details).run(types=["API"])
    details.partial = False
    second = Pipeline(source, store, details).run(resume=first["run_id"])

    resources = list(store.db.portal_resources.find({"catalog_id": "API:1"}))
    current = [row for row in resources if row.get("is_active", True)]
    history = [row for row in resources if row.get("is_active") is False]
    assert first["status"] == "incomplete"
    assert second["status"] == "completed"
    assert [row["url"] for row in current] == [item(1)["detail_url"] + "/kept"]
    assert [row["url"] for row in history] == [item(1)["detail_url"] + "/partial-only"]


def test_incomplete_run_publishes_only_the_successfully_updated_item(store):
    class RevisionDetails(Details):
        revision = b"v1"

        def collect(self, record, heartbeat=lambda: None):
            if record["catalog_id"] in self.failures:
                raise ValueError("Missing metadata")
            detail, _, errors = super().collect(record, heartbeat)
            detail["metadata"]["revision"] = [self.revision.decode()]
            resource = Resource(
                record["detail_url"],
                self.revision,
                "text/html",
                NOW,
                "detail_html",
            )
            return detail, [resource], errors

    source = Source({("API", 1): ([item(1), item(2)], 2)})
    details = RevisionDetails()
    first = Pipeline(source, store, details).run(types=["API"])
    first_resource = store.db.portal_resources.find_one({"catalog_id": "API:1", "is_active": True})

    details.revision = b"v2"
    details.failures.add("API:2")
    second = Pipeline(source, store, details).run(types=["API"])
    resources = list(store.db.portal_resources.find({"catalog_id": "API:1"}))
    active = [row for row in resources if row.get("is_active", True)]
    history = [row for row in resources if row.get("is_active") is False]
    catalog = store.db.portal_catalog.find_one({"_id": "API:1"})

    assert first["status"] == "completed"
    assert second["status"] == "incomplete"
    assert catalog["metadata"]["revision"] == ["v2"]
    assert len(active) == len(history) == 1
    assert active[0]["_id"] != first_resource["_id"]
    assert history[0]["_id"] == first_resource["_id"]
    assert history[0]["removed_at"] is not None


def test_resuming_old_run_item_without_resource_ids_keeps_existing_resources(store):
    class ResourceDetails(Details):
        def collect(self, record, heartbeat=lambda: None):
            detail, _, errors = super().collect(record, heartbeat)
            resource = Resource(
                record["detail_url"],
                f"resource-{record['catalog_id']}".encode(),
                "text/html",
                NOW,
                "detail_html",
            )
            return detail, [resource], errors

    source = Source({("API", 1): ([item(1), item(2)], 2)})
    details = ResourceDetails()
    initial = Pipeline(source, store, details).run(types=["API"])
    original = store.db.portal_resources.find_one({"catalog_id": "API:1", "is_active": True})

    paused = Pipeline(source, store, details).run(types=["API"], max_details=1)
    store.db.portal_run_items.update_one(
        {"run_id": paused["run_id"], "catalog_id": "API:1"},
        {"$unset": {"resource_ids": ""}},
    )
    resumed = Pipeline(source, store, details).run(resume=paused["run_id"])
    preserved = store.db.portal_resources.find_one({"_id": original["_id"]})

    assert initial["status"] == "completed"
    assert paused["status"] == "paused"
    assert resumed["status"] == "completed"
    assert preserved["is_active"] is True
    assert preserved.get("removed_at") is None


def test_completed_historical_run_cannot_be_resumed_over_newer_snapshot(store):
    source = Source({("API", 1): ([item(1), item(2)], 2)})
    first = Pipeline(source, store, Details()).run(types=["API"])
    second = Pipeline(source, store, Details()).run(types=["API"])

    with pytest.raises(ValueError, match="Completed run cannot be resumed"):
        Pipeline(source, store, Details()).run(resume=first["run_id"])

    current = list(store.db.portal_catalog.find({"is_active": True}))
    assert first["status"] == second["status"] == "completed"
    assert {row["_id"] for row in current} == {"API:1", "API:2"}
    assert all(row["last_seen_run"] == second["run_id"] for row in current)


def test_older_paused_run_is_rejected_after_newer_overlapping_run(store):
    source = Source(
        {
            ("API", 1): ([item(1)], 2),
            ("API", 2): ([item(2)], 2),
        }
    )
    older = Pipeline(source, store, Details()).run(types=["API"], page_size=1, max_pages=1)
    newer = Pipeline(source, store, Details()).run(types=["API"], page_size=1)

    with pytest.raises(ValueError, match="superseded by a newer overlapping run"):
        Pipeline(source, store, Details()).run(resume=older["run_id"])

    current = list(store.db.portal_catalog.find({"is_active": True}))
    assert older["status"] == "paused"
    assert newer["status"] == "completed"
    assert {row["_id"] for row in current} == {"API:1", "API:2"}
    assert all(row["last_seen_run"] == newer["run_id"] for row in current)


def test_newer_disjoint_type_run_does_not_block_resume(store):
    source = Source(
        {
            ("API", 1): ([item(1)], 2),
            ("API", 2): ([item(2)], 2),
            ("FILE", 1): ([item(1, "FILE")], 1),
        }
    )
    paused = Pipeline(source, store, Details()).run(types=["API"], page_size=1, max_pages=1)
    file_run = Pipeline(source, store, Details()).run(types=["FILE"])
    resumed = Pipeline(source, store, Details()).run(resume=paused["run_id"])

    assert paused["status"] == "paused"
    assert file_run["status"] == resumed["status"] == "completed"
    assert {row["_id"] for row in store.db.portal_catalog.find({"is_active": True})} == {
        "API:1",
        "API:2",
        "FILE:1",
    }


def test_repeated_cross_page_record_keeps_collecting_new_rows_but_stays_incomplete(store):
    source = Source(
        {
            ("API", 1): ([item(1), item(2)], 5),
            ("API", 2): ([item(2), item(3)], 5),
            ("API", 3): ([item(4)], 5),
        }
    )
    details = Details()

    report = Pipeline(source, store, details).run(types=["API"], page_size=2)

    assert source.calls == [("API", 1), ("API", 2), ("API", 3)]
    assert sorted(details.calls) == ["API:1", "API:2", "API:3", "API:4"]
    assert report["status"] == "incomplete"
    assert report["streams"]["API"]["duplicate_records"] is True
    assert report["streams"]["API"]["unique_records"] == 4


def test_detail_refresh_does_not_retire_active_reference_documents(store):
    item_value = item(1)
    store.db.portal_catalog.insert_one({"_id": "API:1", "list_id": 1, "data_type": "API"})
    store.db.portal_resources.insert_one(
        {
            "_id": "ref",
            "catalog_id": "API:1",
            "kind": "reference_document",
            "attachment_id": "reference:1",
            "is_active": True,
        }
    )
    store.db.portal_run_items.insert_one(
        {"_id": "run-item", "run_id": "run", "catalog_id": "API:1", "status": "pending"}
    )
    store.save_detail(
        "run", item_value, {"metadata": {}, "api_specs": [], "attachments": []}, [], []
    )
    assert store.db.portal_resources.find_one({"_id": "ref"})["is_active"] is True
