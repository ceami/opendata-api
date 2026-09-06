"""Regressions spanning snapshot, reference publication, and their parser consumers."""

import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from pymongo.errors import DuplicateKeyError, WriteError
from test_reference_docs import ReferenceHTTP, attachment, detail, reference_store_with_catalogs

from opendata_collector.parse_normalizers import normalize_catalog
from opendata_collector.parse_store import ParseStore
from opendata_collector.reference_docs import ReferencePipeline
from opendata_collector.snapshot import SnapshotPipeline
from opendata_collector.store import MongoStore, SnapshotStore

CSV = b"1,API,Monthly title,https://www.data.go.kr/data/1/openapi.do,description\n"
HEADERS = "목록키,목록유형,목록명,목록 URL,설명\n".encode()


def docx(text):
    import io
    import zipfile

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        )
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return stream.getvalue()


def head(store, catalog_id="API:15129394"):
    return store.db.portal_resources.find_one(
        {"catalog_id": catalog_id, "kind": "reference_document", "is_active": True}
    )


def refresh_detail(store, payload, *, catalog_id="API:15129394", errors=None):
    catalog = store.db.portal_catalog.find_one({"_id": catalog_id})
    MongoStore(store.db).save_detail(
        "detail-refresh", {**catalog, "catalog_id": catalog_id}, payload, [], errors or []
    )


def test_live_portal_listing_title_wins_over_monthly_fallback_with_failed_detail():
    store = reference_store_with_catalogs(file=False)
    store.db.portal_catalog.update_one(
        {"_id": "API:15129394"},
        {"$set": {"title": "Live title updated today", "detail_status": "failed"}},
    )
    store.db.portal_source_records.insert_one(
        {
            "_id": "portal:API:15129394",
            "catalog_id": "API:15129394",
            "source": "portal",
            "record": {"description": "Live summary"},
            "is_active": True,
        }
    )
    payload = HEADERS + CSV.replace(b"1,API", b"15129394,API").replace(
        b"data/1/", b"data/15129394/"
    )
    SnapshotPipeline(SnapshotStore(store.db)).run(payload, source={"kind": "file"})
    parsed = normalize_catalog(next(ParseStore(store.db).inputs(["API"])))
    assert parsed.document["title"] == "Live title updated today"


def test_duplicate_snapshot_reconciles_current_catalog_without_changing_publication():
    store = SnapshotStore(reference_store_with_catalogs(api=False, file=False).db)
    pipeline = SnapshotPipeline(store)
    first = pipeline.run(HEADERS + CSV, source={"kind": "file", "name": "first.csv"})
    published = store.db.portal_snapshot_runs.find_one({"_id": first["run_id"]})
    rows = list(store.current_records())
    store.db.portal_catalog.insert_one({"_id": "API:1", "data_type": "API", "is_active": True})

    replay = pipeline.run(HEADERS + CSV, source={"kind": "file", "name": "replay.csv"})

    assert replay["reconciliation"] == {"matched": 1, "snapshot_only": 0, "current_only": 0}
    assert replay["reused_generation"] is True
    assert replay["publication_summary"]["reconciliation"] == {
        "matched": 0,
        "snapshot_only": 1,
        "current_only": 0,
    }
    assert replay["source"] == {"kind": "file", "name": "replay.csv"}
    assert replay["run_id"] == first["run_id"]
    assert replay["reconciled_at"] >= published["completed_at"]
    assert store.db.portal_snapshot_runs.find_one({"_id": first["run_id"]}) == published
    assert list(store.current_records()) == rows
    assert store.db.portal_raw.files.count_documents({}) == 1
    assert store.db.portal_snapshot_runs.count_documents({}) == 1


@pytest.mark.parametrize("previous", [False, True])
@pytest.mark.parametrize("ending", [b'"unterminated', b'"closed"junk'])
def test_malformed_csv_quotes_never_publish_or_replace(previous, ending):
    store = SnapshotStore(reference_store_with_catalogs(api=False, file=False).db)
    pipeline = SnapshotPipeline(store)
    if previous:
        pipeline.run(HEADERS + CSV, source={"kind": "file"})
    before = list(store.db.portal_snapshot_runs.find())
    with pytest.raises(ValueError, match="Snapshot CSV.*malformed"):
        pipeline.run(HEADERS + CSV.rsplit(b",", 1)[0] + b"," + ending, source={"kind": "file"})
    assert list(store.db.portal_snapshot_runs.find()) == before
    assert store.db.portal_raw.files.count_documents({}) == int(previous)


def test_snapshot_persistence_failure_stores_only_safe_classification(monkeypatch):
    store = SnapshotStore(reference_store_with_catalogs(api=False, file=False).db)

    def fail(*_args, **_kwargs):
        raise WriteError("PRIVATE COMMAND PAYLOAD")

    monkeypatch.setattr(store.db.portal_snapshot_records, "bulk_write", fail)
    with pytest.raises(WriteError):
        SnapshotPipeline(store).run(HEADERS + CSV, source={"kind": "file"})
    failed = store.db.portal_snapshot_runs.find_one()
    assert failed["status"] == "failed"
    assert "PRIVATE" not in json.dumps(failed, default=str)
    assert failed["error_type"] == "WriteError"


def test_reference_refresh_updates_one_head_and_keeps_immutable_blobs():
    store = reference_store_with_catalogs(file=False)
    http = ReferenceHTTP(docx("First text"))
    ReferencePipeline(store, http).run()
    first = head(store)
    fingerprint = next(ParseStore(store.db).inputs(["API"])).source_fingerprint
    http.payload = docx("Second text")
    ReferencePipeline(store, http).run(force=True)
    second = head(store)
    assert second["_id"] == first["_id"]
    assert second["reference_head"] == first["_id"]
    assert second["raw_id"] != first["raw_id"]
    assert second["content_type"] == "application/octet-stream"
    assert "fetched_at" in second
    assert store.db.portal_resources.count_documents({"kind": "reference_document"}) == 1
    assert gzip.decompress(store.raw.get(first["text_raw_id"]).read()) == b"First text"
    assert gzip.decompress(store.raw.get(second["text_raw_id"]).read()) == b"Second text"
    parsed = next(ParseStore(store.db).inputs(["API"]))
    assert parsed.source_fingerprint != fingerprint
    assert (
        parsed.detail["attachments"][0]["reference_document"]["text_sha256"]
        == hashlib.sha256(b"Second text").hexdigest()
    )


def test_failed_head_publication_preserves_previous_resource_and_can_resume(monkeypatch):
    store = reference_store_with_catalogs(file=False)
    http = ReferenceHTTP(docx("First text"))
    ReferencePipeline(store, http).run()
    first = head(store)
    original = store.db.portal_resources.update_one

    def fail_publication(selector, update, **kwargs):
        if update.get("$set", {}).get("kind") == "reference_document":
            raise WriteError("publication failed")
        return original(selector, update, **kwargs)

    http.payload = docx("Second text")
    with monkeypatch.context() as patch:
        patch.setattr(store.db.portal_resources, "update_one", fail_publication)
        failed = ReferencePipeline(store, http).run(force=True)
    assert failed["status"] == "incomplete"
    assert list(store.db.portal_resources.find({"kind": "reference_document"})) == [first]
    resumed = ReferencePipeline(store, http).run(resume=failed["run_id"])
    assert resumed["completed"] == 1
    assert head(store)["_id"] == first["_id"]
    assert gzip.decompress(store.raw.get(head(store)["text_raw_id"]).read()) == b"Second text"


def test_multiple_legacy_revisions_migrate_to_latest_head_and_do_not_affect_consumers(monkeypatch):
    store = reference_store_with_catalogs(file=False)
    http = ReferenceHTTP(docx("First text"))
    ReferencePipeline(store, http).run()
    first = head(store)
    store.db.portal_resources.delete_one({"_id": first["_id"]})
    older = {key: value for key, value in first.items() if key not in {"_id", "reference_head"}}
    older["collected_at"] = datetime(2026, 9, 1, tzinfo=timezone.utc)
    newer = {
        **older,
        "collected_at": older["collected_at"] + timedelta(days=1),
        "text_sha256": "newest",
    }
    older.pop("content_type", None)
    newer.pop("content_type", None)
    store.db.portal_resources.insert_many([{"_id": "z-old", **older}, {"_id": "a-new", **newer}])
    # Simulate interruption after the head is durable but before old rows are retired.

    def fail_retirement(*_args, **_kwargs):
        raise WriteError("retirement failed")

    with monkeypatch.context() as patch:
        patch.setattr(store.db.portal_resources, "update_many", fail_retirement)
        with pytest.raises(WriteError, match="retirement failed"):
            store.initialize()
    parsed = next(ParseStore(store.db).inputs(["API"]))
    references = [row for row in parsed.resources if row["kind"] == "reference_document"]
    assert len(references) == 1
    assert references[0]["text_sha256"] == "newest"
    assert references[0]["content_type"] == "application/octet-stream"
    rerun = ReferencePipeline(store, http).run()
    assert rerun["skipped"] == 1
    assert (
        store.db.portal_resources.count_documents({"kind": "reference_document", "is_active": True})
        == 1
    )
    assert head(store)["text_sha256"] == "newest"
    with pytest.raises(DuplicateKeyError):
        store.db.portal_resources.insert_one({**head(store), "_id": "duplicate-head"})


@pytest.mark.parametrize(
    "replacement", [[], [attachment("Replacement.docx", file_id="FILE_replacement")]]
)
def test_completed_detail_retires_removed_or_replaced_identity_even_when_zero_selected(replacement):
    store = reference_store_with_catalogs(file=False)
    http = ReferenceHTTP(docx("First text"))
    ReferencePipeline(store, http).run()
    previous = head(store)
    refresh_detail(store, detail(*replacement))
    store.db.portal_resources.insert_one(
        {"_id": "dcat", "catalog_id": "API:15129394", "kind": "dcat", "is_active": True}
    )
    report = ReferencePipeline(store, http).run()
    assert report["status"] == "completed"
    assert report["selected"] == len(replacement)
    assert store.db.portal_resources.find_one({"_id": previous["_id"]})["is_active"] is False
    assert store.db.portal_resources.find_one({"_id": "dcat"})["is_active"] is True
    assert len(
        [
            row
            for row in next(ParseStore(store.db).inputs(["API"])).resources
            if row["kind"] == "reference_document"
        ]
    ) == len(replacement)


@pytest.mark.parametrize("observation", ["partial", "failed", "unreadable", "missing", "malformed"])
def test_untrustworthy_detail_preserves_previous_reference_head(observation):
    store = reference_store_with_catalogs(file=False)
    http = ReferenceHTTP(docx("First text"))
    ReferencePipeline(store, http).run()
    previous = head(store)
    if observation in {"partial", "failed"}:
        refresh_detail(store, detail(), errors=[{"error": "detail failed"}])
        store.db.portal_catalog.update_one(
            {"_id": "API:15129394"}, {"$set": {"detail_status": observation}}
        )
    elif observation == "unreadable":
        store.db.portal_catalog.update_one(
            {"_id": "API:15129394"}, {"$set": {"parsed_detail_ref": "unreadable"}}
        )
    else:
        refresh_detail(
            store,
            {} if observation == "missing" else detail(attachment("guide.docx", file_id="invalid")),
        )
    ReferencePipeline(store, http).run()
    assert head(store) == previous


def test_download_limit_does_not_limit_identity_reconciliation_or_retire_unselected_heads():
    store = reference_store_with_catalogs()
    http = ReferenceHTTP(docx("First text"))
    refresh_detail(
        store, detail(attachment("First.docx"), attachment("Second.docx", file_detail_sn="3"))
    )
    ReferencePipeline(store, http).run(types=["API", "FILE"])
    previous_file = head(store, "FILE:15129395")
    refresh_detail(store, {"attachments": []}, catalog_id="FILE:15129395")
    result = ReferencePipeline(store, http).run(types=["API", "FILE"], limit=1)
    assert result["selected"] == 1
    assert store.db.portal_resources.find_one({"_id": previous_file["_id"]})["is_active"] is False
    assert (
        store.db.portal_resources.count_documents(
            {"catalog_id": "API:15129394", "kind": "reference_document", "is_active": True}
        )
        == 2
    )


def test_reference_run_id_is_visible_before_interrupt_on_new_and_resume(capsys):
    store = reference_store_with_catalogs(file=False)

    class InterruptHTTP:
        def get(self, *_args, **_kwargs):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        ReferencePipeline(store, InterruptHTTP()).run()
    run = store.db.portal_reference_runs.find_one()
    captured = capsys.readouterr()
    assert run["_id"] in captured.err
    assert captured.out == ""
    with pytest.raises(KeyboardInterrupt):
        ReferencePipeline(store, InterruptHTTP()).run(resume=run["_id"])
    assert run["_id"] in capsys.readouterr().err


def test_failed_head_migration_keeps_legacy_success_until_retry(monkeypatch):
    store = reference_store_with_catalogs(file=False)
    http = ReferenceHTTP(docx("Preserved text"))
    ReferencePipeline(store, http).run()
    previous = head(store)
    store.db.portal_resources.delete_one({"_id": previous["_id"]})
    legacy = {key: value for key, value in previous.items() if key != "reference_head"}
    legacy["_id"] = "legacy-success"
    store.db.portal_resources.insert_one(legacy)
    original = store.db.portal_resources.update_one

    def fail_head(selector, update, **kwargs):
        if update.get("$setOnInsert", {}).get("reference_head"):
            raise WriteError("migration head failed")
        return original(selector, update, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(store.db.portal_resources, "update_one", fail_head)
        with pytest.raises(WriteError, match="migration head failed"):
            store.initialize()
    assert list(store.db.portal_resources.find({"kind": "reference_document"})) == [legacy]
    assert gzip.decompress(store.raw.get(legacy["text_raw_id"]).read()) == b"Preserved text"
    store.initialize()
    assert head(store)["text_raw_id"] == legacy["text_raw_id"]
    assert store.db.portal_resources.find_one({"_id": "legacy-success"})["is_active"] is False


def test_resume_reconciles_removed_identity_after_selection_was_completed():
    store = reference_store_with_catalogs(file=False)
    http = ReferenceHTTP(docx("Previous success"))
    ReferencePipeline(store, http).run()
    previous = head(store)
    http.fail.add(previous["url"])
    failed = ReferencePipeline(store, http).run(force=True)
    assert failed["selection_complete"] is True
    refresh_detail(store, detail())
    resumed = ReferencePipeline(store, http).run(resume=failed["run_id"])
    assert resumed["status"] == "completed"
    assert resumed["stale"] == 1
    assert store.db.portal_resources.find_one({"_id": previous["_id"]})["is_active"] is False


@pytest.mark.parametrize("active", [False, True])
def test_legacy_cleanup_cannot_replace_existing_head_or_resurrect_retired_identity(active):
    store = reference_store_with_catalogs(file=False)
    ReferencePipeline(store, ReferenceHTTP(docx("Authoritative text"))).run()
    current = head(store)
    store.db.portal_resources.update_one({"_id": current["_id"]}, {"$set": {"is_active": active}})
    current["is_active"] = active
    legacy = {key: value for key, value in current.items() if key != "reference_head"}
    legacy.update(_id="stray-legacy", is_active=True, text_sha256="obsolete")
    store.db.portal_resources.insert_one(legacy)

    store.initialize()

    assert store.db.portal_resources.find_one({"_id": current["_id"]}) == current
    assert store.db.portal_resources.find_one({"_id": "stray-legacy"})["is_active"] is False
