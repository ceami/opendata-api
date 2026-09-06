import json
from datetime import datetime, timedelta, timezone

import mongomock
import pytest
from mongomock.gridfs import enable_gridfs_integration

from opendata_collector.parse_normalizers import PARSER_VERSION, normalize_catalog
from opendata_collector.parse_pipeline import ParsePipeline
from opendata_collector.parse_store import ParseStore
from opendata_collector.reference_docs import reference_attachment_identity
from opendata_collector.store import MongoStore, SnapshotStore

enable_gridfs_integration()
NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


@pytest.fixture
def store():
    return ParseStore(mongomock.MongoClient(tz_aware=True).parse_test)


def seed(store, kind="API", number=7, *, detail=None, detail_status="completed"):
    detail = detail or {
        "metadata": {"설명": ["description"]},
        "schema_org": [],
        "api_specs": [],
        "attachments": [],
        "tables": [],
        "detail_format": "TABLE",
    }
    detail_ref = MongoStore(store.db).save_raw(json.dumps(detail, ensure_ascii=False).encode())
    catalog_id = f"{kind}:{number}"
    store.db.portal_catalog.insert_one(
        {
            "_id": catalog_id,
            "data_type": kind,
            "list_id": number,
            "title": f"{kind} {number}",
            "summary": {},
            "metadata": detail.get("metadata", {}),
            "detail_url": f"https://www.data.go.kr/data/{number}/detail.do",
            "parsed_detail_ref": detail_ref,
            "detail_status": detail_status,
            "detail_errors": [] if detail_status == "completed" else [{"kind": "dcat"}],
            "is_active": True,
        }
    )
    store.db.portal_source_records.insert_one(
        {
            "_id": f"source:{catalog_id}",
            "catalog_id": catalog_id,
            "record": {"id": f"official-{number}", "title": f"Official {number}"},
            "is_active": True,
        }
    )
    raw_id = MongoStore(store.db).save_raw(b"resource payload")
    store.db.portal_resources.insert_one(
        {
            "_id": f"resource:{catalog_id}",
            "catalog_id": catalog_id,
            "kind": "attachment",
            "url": "https://example.test/resource",
            "raw_id": raw_id,
            "is_active": True,
        }
    )
    return catalog_id


def test_inputs_load_gridfs_payloads_and_fingerprint_source_changes(store):
    catalog_id = seed(store, "LINKED")
    store.db.portal_resources.update_one({"catalog_id": catalog_id}, {"$set": {"kind": "dcat"}})

    first = list(store.inputs(["LINKED"]))[0]
    second = list(store.inputs(["LINKED"]))[0]

    assert first.detail["metadata"]["설명"] == ["description"]
    assert first.resources[0]["content"] == b"resource payload"
    assert first.source_fingerprint == second.source_fingerprint

    store.db.portal_source_records.update_one(
        {"catalog_id": catalog_id}, {"$set": {"record.title": "Changed"}}
    )
    changed = list(store.inputs(["LINKED"]))[0]
    assert changed.source_fingerprint != first.source_fingerprint


def test_inputs_use_latest_completed_snapshot_as_a_low_priority_source(store):
    catalog_id = seed(store, "FILE")
    store.db.portal_snapshot_runs.insert_many(
        [
            {
                "_id": "completed",
                "status": "completed",
                "completed_at": NOW,
                "source": {"name": "monthly.csv"},
                "raw_sha256": "completed-hash",
            },
            {
                "_id": "running",
                "status": "running",
                "completed_at": NOW + timedelta(days=1),
                "source": {"name": "unpublished.csv"},
                "raw_sha256": "running-hash",
            },
        ]
    )
    store.db.portal_snapshot_records.insert_many(
        [
            {
                "_id": "completed:FILE:7",
                "snapshot_run_id": "completed",
                "run_id": "completed",
                "catalog_id": catalog_id,
                "data_type": "FILE",
                "list_id": 7,
                "source_record": {"목록명": "Monthly title", "제공기관": "Monthly org"},
            },
            {
                "_id": "running:FILE:7",
                "snapshot_run_id": "running",
                "run_id": "running",
                "catalog_id": catalog_id,
                "data_type": "FILE",
                "list_id": 7,
                "source_record": {"목록명": "Unpublished title"},
            },
        ]
    )

    SnapshotStore(store.db).initialize()
    index_keys = {
        tuple(index["key"].items()) for index in store.db.portal_snapshot_records.list_indexes()
    }
    assert (("run_id", 1), ("catalog_id", 1)) in index_keys

    first = next(store.inputs(["FILE"]))

    snapshot = first.source_records[-1]
    assert snapshot["source"] == "monthly_snapshot"
    assert snapshot["record"] == {"목록명": "Monthly title", "제공기관": "Monthly org"}
    assert snapshot["snapshot_run_id"] == "completed"
    assert snapshot["snapshot_source"] == {"name": "monthly.csv"}
    assert snapshot["snapshot_raw_sha256"] == "completed-hash"
    assert first.source_records[0]["record"]["title"] == "Official 7"

    store.db.portal_snapshot_records.update_one(
        {"_id": "completed:FILE:7"}, {"$set": {"source_record.제공기관": "Changed org"}}
    )
    changed = next(store.inputs(["FILE"]))

    assert changed.source_fingerprint != first.source_fingerprint


def test_pipeline_skips_unchanged_reparses_changed_and_supports_force(store):
    catalog_id = seed(store)
    pipeline = ParsePipeline(store)

    first = pipeline.run(["API"])
    second = pipeline.run(["API"])
    store.db.portal_catalog.update_one({"_id": catalog_id}, {"$set": {"title": "Changed"}})
    changed = pipeline.run(["API"])
    forced = pipeline.run(["API"], force=True)

    assert first["parsed"] == 1
    assert second["skipped"] == 1
    assert changed["parsed"] == 1
    assert forced["parsed"] == 1
    parsed = store.db.parsed_api_info.find_one({"list_id": 7})
    assert (
        parsed["source_fingerprint"]
        == store.db.portal_catalog.find_one({"_id": catalog_id})["source_fingerprint"]
    )
    assert parsed["parser_version"] == PARSER_VERSION


def test_older_parser_version_reparses_even_when_source_fingerprint_matches(store):
    catalog_id = seed(store)
    parse_input = next(store.inputs(["API"]))
    store.db.parsed_api_info.insert_one(
        {
            "_id": "old-parser",
            "list_id": 7,
            "source_catalog_id": catalog_id,
            "source_fingerprint": parse_input.source_fingerprint,
            "parser_version": "1",
            "parsed_at": NOW,
        }
    )

    report = ParsePipeline(store).run(["API"])

    assert report["parsed"] == 1
    assert report["skipped"] == 0
    assert store.db.parsed_api_info.find_one({"list_id": 7})["parser_version"] == PARSER_VERSION


def test_duplicate_legacy_file_rows_collapse_and_newest_id_is_preserved(store):
    seed(store, "FILE")
    store.db.parsed_file_info.insert_many(
        [
            {"_id": "older", "list_id": 7, "parsed_at": NOW - timedelta(days=1)},
            {"_id": "newer", "list_id": 7, "parsed_at": NOW},
        ]
    )

    report = ParsePipeline(store).run(["FILE"])

    assert report["parsed"] == 1
    rows = list(store.db.parsed_file_info.find({"list_id": 7}))
    assert len(rows) == 1
    assert rows[0]["_id"] == "newer"


def test_standard_members_are_separate_and_stale_members_become_inactive(store):
    catalog_id = seed(
        store,
        "STD",
        detail={
            "metadata": {},
            "schema_org": [],
            "api_specs": [],
            "attachments": [],
            "tables": [],
            "standard_members": {
                "total": 2,
                "collected_count": 2,
                "items": [
                    {"public_data_detail_pk": "a", "title": "A"},
                    {"public_data_detail_pk": "b", "title": "B"},
                ],
            },
            "detail_popups": [],
            "detail_format": "TABLE",
        },
    )
    store.db.parsed_std_members.insert_one(
        {"_id": f"{catalog_id}:removed", "source_catalog_id": catalog_id, "is_active": True}
    )

    ParsePipeline(store).run(["STD"])

    assert (
        store.db.parsed_std_members.count_documents(
            {"source_catalog_id": catalog_id, "is_active": True}
        )
        == 2
    )
    assert (
        store.db.parsed_std_members.find_one({"_id": f"{catalog_id}:removed"})["is_active"] is False
    )


def test_partial_and_parser_failure_statuses_remain_visible(store, monkeypatch):
    partial_id = seed(store, "LINKED", 1, detail_status="partial")
    failed_id = seed(store, "API", 2)
    store.db.open_data_info.insert_one(
        {"_id": "existing-api", "list_id": 2, "title": "complete legacy row"}
    )
    real_normalize = __import__(
        "opendata_collector.parse_pipeline", fromlist=["normalize_catalog"]
    ).normalize_catalog

    def fail_one(value):
        if value.catalog["_id"] == failed_id:
            raise ValueError("bad parser input")
        return real_normalize(value)

    monkeypatch.setattr("opendata_collector.parse_pipeline.normalize_catalog", fail_one)

    report = ParsePipeline(store).run(["LINKED", "API"])

    assert report["partial"] == 1
    assert report["failed"] == 1
    assert report["status"] == "incomplete"
    assert store.db.portal_catalog.find_one({"_id": partial_id})["parse_status"] == "partial"
    failed = store.db.portal_catalog.find_one({"_id": failed_id})
    assert failed["parse_status"] == "failed"
    assert failed["parse_errors"] == [{"error": "bad parser input"}]
    assert store.db.open_data_info.find_one({"list_id": 2})["is_parsed"] == "ERROR"


def test_pending_catalogs_are_not_parsed_and_missing_completed_payload_is_partial(store):
    store.db.portal_catalog.insert_many(
        [
            {
                "_id": "API:pending",
                "data_type": "API",
                "list_id": 90,
                "title": "pending",
                "detail_status": "pending",
                "is_active": True,
            },
            {
                "_id": "API:broken",
                "data_type": "API",
                "list_id": 91,
                "title": "broken",
                "detail_status": "completed",
                "is_active": True,
            },
        ]
    )

    report = ParsePipeline(store).run(["API"])

    assert report["selected"] == 1
    assert report["failed"] == 0
    assert report["partial"] == 1
    assert store.db.portal_catalog.find_one({"_id": "API:pending"}).get("parse_status") is None
    assert store.db.portal_catalog.find_one({"_id": "API:broken"})["parse_status"] == "partial"
    assert store.db.open_data_info.count_documents({"list_id": 91}) == 0


def test_partial_source_makes_parse_run_incomplete(store):
    seed(store, "LINKED", 8, detail_status="partial")

    report = ParsePipeline(store).run(["LINKED"])

    assert report["parsed"] == 1
    assert report["partial"] == 1
    assert report["status"] == "incomplete"


def test_partial_standard_does_not_retire_unobserved_members(store):
    seed(
        store,
        "STD",
        20,
        detail={
            "metadata": {},
            "schema_org": [],
            "api_specs": [],
            "attachments": [],
            "tables": [],
            "standard_members": {
                "total": 2,
                "collected_count": 1,
                "items": [{"public_data_detail_pk": "observed", "title": "Observed"}],
            },
            "detail_popups": [],
            "detail_format": "TABLE",
        },
        detail_status="partial",
    )
    store.db.parsed_std_members.insert_one(
        {
            "_id": "STD:20:unobserved",
            "source_catalog_id": "STD:20",
            "is_active": True,
        }
    )

    ParsePipeline(store).run(["STD"])

    assert store.db.parsed_std_members.find_one({"_id": "STD:20:unobserved"})["is_active"] is True


def test_malformed_catalog_failure_does_not_abort_later_catalogs(store):
    seed(
        store,
        "API",
        30,
        detail={
            "metadata": {},
            "schema_org": [],
            "api_specs": [{"openapi": "3.0.0", "paths": None}],
            "attachments": [],
            "tables": [],
            "detail_format": "SWAGGER",
        },
    )
    seed(store, "API", 31)

    report = ParsePipeline(store).run(["API"])

    assert report["selected"] == 2
    assert report["failed"] == 1
    assert report["parsed"] == 1
    assert store.db.portal_catalog.find_one({"_id": "API:30"})["parse_status"] == "failed"
    assert store.db.parsed_api_info.count_documents({"list_id": 31}) == 1


def test_missing_dcat_payload_creates_partial_result_instead_of_total_failure(store):
    catalog_id = seed(store, "LINKED", 40)
    store.db.portal_resources.update_one({"catalog_id": catalog_id}, {"$set": {"kind": "dcat"}})
    resource = store.db.portal_resources.find_one({"catalog_id": catalog_id})
    store.raw.delete(resource["raw_id"])

    report = ParsePipeline(store).run(["LINKED"])

    assert report["failed"] == 0
    assert report["partial"] == 1
    parsed = store.db.parsed_linked_info.find_one({"list_id": 40})
    assert parsed["parse_status"] == "partial"
    assert parsed["parse_errors"] == [{"kind": "dcat", "error": "Cannot load resource payload"}]


def test_irrelevant_resource_payload_is_not_loaded_or_reported_as_partial(store):
    catalog_id = seed(store, "API", 50)
    resource = store.db.portal_resources.find_one({"catalog_id": catalog_id})
    store.raw.delete(resource["raw_id"])

    report = ParsePipeline(store).run(["API"])

    assert report["parsed"] == 1
    assert report["partial"] == 0


def test_partial_standard_keeps_previous_popup_fields_for_observed_member(store):
    seed(
        store,
        "STD",
        60,
        detail={
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
                        "title": "Updated title",
                        "provider": "Updated provider",
                    }
                ],
            },
            "detail_popups": [],
            "detail_format": "TABLE",
        },
        detail_status="partial",
    )
    store.db.parsed_std_members.insert_one(
        {
            "_id": "STD:60:member",
            "source_catalog_id": "STD:60",
            "is_active": True,
            "title": "Old title",
            "metadata": {"설명": ["complete detail"]},
            "columns": [{"caption": "complete columns"}],
            "distributions": [{"name": "complete.csv"}],
        }
    )

    ParsePipeline(store).run(["STD"])

    member = store.db.parsed_std_members.find_one({"_id": "STD:60:member"})
    assert member["title"] == "Updated title"
    assert member["provider"] == "Updated provider"
    assert member["metadata"] == {"설명": ["complete detail"]}
    assert member["columns"] == [{"caption": "complete columns"}]
    assert member["distributions"] == [{"name": "complete.csv"}]
    assert member["detail_status"] == "missing"


def test_summary_is_written_last_so_member_failure_remains_retryable(store, monkeypatch):
    seed(
        store,
        "STD",
        70,
        detail={
            "metadata": {},
            "schema_org": [],
            "api_specs": [],
            "attachments": [],
            "tables": [],
            "standard_members": {"total": 0, "collected_count": 0, "items": []},
            "detail_popups": [],
            "detail_format": "TABLE",
        },
    )
    parse_input = list(store.inputs(["STD"]))[0]
    output = normalize_catalog(parse_input)

    def fail_members(_):
        raise RuntimeError("transient member write")

    monkeypatch.setattr(store, "_save_standard_members", fail_members)

    with pytest.raises(RuntimeError, match="transient member write"):
        store.save(output)

    assert store.db.parsed_std_info.count_documents({"list_id": 70}) == 0


def test_unchanged_partial_remains_incomplete_when_skipped(store):
    seed(store, "LINKED", 80, detail_status="partial")
    pipeline = ParsePipeline(store)

    first = pipeline.run(["LINKED"])
    second = pipeline.run(["LINKED"])

    assert first["partial"] == 1
    assert second["skipped"] == 1
    assert second["partial"] == 1
    assert second["status"] == "incomplete"


def test_inputs_enrich_registered_attachments_with_active_reference_documents_and_fingerprint_them(
    store,
):
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [],
        "tables": [],
        "detail_format": "TABLE",
        "hidden_fields": {"publicDataPk": "7", "publicDataDetailPk": "uddi:guide"},
        "attachments": [
            {
                "name": "API guide.docx",
                "file_id": "FILE_000000000001",
                "file_detail_sn": "2",
            }
        ],
    }
    catalog_id = seed(store, detail=detail)
    store.db.portal_resources.insert_one(
        {
            "_id": "reference-resource",
            "reference_head": "reference-resource",
            "catalog_id": catalog_id,
            "kind": "reference_document",
            "attachment_id": reference_attachment_identity(
                "API:7", "7", "uddi:guide", "FILE_000000000001", "2"
            ),
            "source": "official_attachment",
            "name": "API guide.docx",
            "format": "DOCX",
            "file_id": "FILE_000000000001",
            "file_detail_sn": "2",
            "raw_id": "document-hash",
            "document_sha256": "document-hash",
            "text_raw_id": "text-hash",
            "text_sha256": "text-hash",
            "extraction_status": "EXTRACTED",
            "extraction_error": None,
            "char_count": 22,
            "is_active": True,
        }
    )

    parse_input = next(store.inputs(["API"]))
    reference = parse_input.detail["attachments"][0]["reference_document"]

    assert reference == {
        "resource_id": "reference-resource",
        "document_raw_id": "document-hash",
        "document_sha256": "document-hash",
        "text_raw_id": "text-hash",
        "text_sha256": "text-hash",
        "source": "official_attachment",
        "name": "API guide.docx",
        "format": "DOCX",
        "extraction_status": "EXTRACTED",
        "error": None,
        "char_count": 22,
    }
    first_fingerprint = parse_input.source_fingerprint
    store.db.portal_resources.update_one(
        {"_id": "reference-resource"}, {"$set": {"text_sha256": "changed"}}
    )
    assert next(store.inputs(["API"])).source_fingerprint != first_fingerprint
    output = ParsePipeline(store).run(["API"])
    assert output["parsed"] == 1
    assert store.db.parsed_api_info.find_one({"list_id": 7})["attachments"][0][
        "reference_document"
    ] == reference | {"text_sha256": "changed"}


def test_reference_enrichment_uses_canonical_arguments_and_ignores_external_or_malformed_duplicates(
    store,
):
    detail = {
        "metadata": {},
        "schema_org": [],
        "api_specs": [],
        "tables": [],
        "detail_format": "TABLE",
        "hidden_fields": {"publicDataPk": "7", "publicDataDetailPk": "uddi:guide"},
        "attachments": [
            {"name": "guide.docx", "arguments": ["7", "uddi:guide", "FILE_000000000001", 2, "x"]},
            {
                "name": "guide.docx",
                "file_id": "FILE_000000000001",
                "file_detail_sn": "2",
                "url": "https://bad.test",
            },
            {"name": [], "file_id": [], "file_detail_sn": []},
        ],
    }
    catalog_id = seed(store, detail=detail)
    attachment_id = reference_attachment_identity(
        "API:7", "7", "uddi:guide", "FILE_000000000001", "2"
    )
    store.db.portal_resources.insert_one(
        {
            "_id": "ref",
            "reference_head": "ref",
            "catalog_id": catalog_id,
            "kind": "reference_document",
            "attachment_id": attachment_id,
            "raw_id": "d",
            "document_sha256": "d",
            "text_raw_id": "t",
            "text_sha256": "t",
            "source": "official_attachment",
            "name": "guide.docx",
            "format": "DOCX",
            "extraction_status": "EXTRACTED",
            "extraction_error": None,
            "char_count": 1,
            "is_active": True,
        }
    )
    attachments = next(store.inputs(["API"])).detail["attachments"]
    assert attachments[0]["reference_document"]["resource_id"] == "ref"
    assert "reference_document" not in attachments[1]
    assert "reference_document" not in attachments[2]
