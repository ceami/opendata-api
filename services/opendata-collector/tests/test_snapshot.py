import httpx
import mongomock
import pytest
from mongomock.gridfs import enable_gridfs_integration

import opendata_collector.snapshot as snapshot_module
import opendata_collector.store as store_module
from opendata_collector.http import PortalHTTP
from opendata_collector.snapshot import (
    discover_snapshot_download,
    parse_snapshot_csv,
)

enable_gridfs_integration()

HEADERS = "목록키,목록유형,목록명,목록 URL,제공기관\n"
FILE_ROW = (
    "3049380,파일,한국연구재단 KCI,https://www.data.go.kr/data/3049380/fileData.do,한국연구재단\n"
)
SUFFIXES = {"FILE": "fileData", "API": "openapi", "STD": "standard"}
TYPE_NAMES = {"FILE": "파일", "API": "오픈API", "STD": "표준데이터셋"}


@pytest.fixture
def snapshot_pipeline():
    database = mongomock.MongoClient(tz_aware=True).snapshot
    return snapshot_module.SnapshotPipeline(store_module.SnapshotStore(database, batch_size=1))


def snapshot_row(list_id, data_type="FILE", title=None):
    suffix = SUFFIXES[data_type]
    return (
        f"{list_id},{TYPE_NAMES[data_type]},{title or f'Catalog {list_id}'},"
        f"https://www.data.go.kr/data/{list_id}/{suffix}.do,기관\n"
    )


def snapshot_payload(*rows):
    return (HEADERS + "".join(rows)).encode()


@pytest.mark.parametrize(
    ("payload", "data_type", "raw_type"),
    [
        (("\ufeff" + HEADERS + FILE_ROW).encode(), "FILE", "파일"),
        ((HEADERS + FILE_ROW.replace("파일", "파일데이터")).encode("cp949"), "FILE", "파일데이터"),
        (
            (HEADERS + FILE_ROW.replace("파일", "오픈API").replace("fileData", "openapi")).encode(),
            "API",
            "오픈API",
        ),
        (
            (
                HEADERS + FILE_ROW.replace("파일", "표준데이터셋").replace("fileData", "standard")
            ).encode(),
            "STD",
            "표준데이터셋",
        ),
    ],
)
def test_parse_snapshot_csv_decodes_official_encodings_and_normalizes_catalog_fields(
    payload, data_type, raw_type
):
    rows = list(parse_snapshot_csv(payload))
    suffix = SUFFIXES[data_type]

    assert rows == [
        {
            "catalog_id": f"{data_type}:3049380",
            "data_type": data_type,
            "list_id": 3049380,
            "detail_url": f"https://www.data.go.kr/data/3049380/{suffix}.do",
            "title": "한국연구재단 KCI",
            "source_id": f"snapshot:{data_type}:3049380",
            "source_record": {
                "목록키": "3049380",
                "목록유형": raw_type,
                "목록명": "한국연구재단 KCI",
                "목록 URL": f"https://www.data.go.kr/data/3049380/{suffix}.do",
                "제공기관": "한국연구재단",
            },
        }
    ]


@pytest.mark.parametrize(
    "payload",
    [
        "목록키,목록유형,목록 URL\n3049380,파일,https://www.data.go.kr/data/3049380/fileData.do\n".encode(),
        (HEADERS + FILE_ROW.replace("파일", "알수없음")).encode(),
        (HEADERS + FILE_ROW.replace("3049380/fileData", "3049381/fileData")).encode(),
        (HEADERS + FILE_ROW.replace("fileData", "openapi")).encode(),
        (HEADERS + FILE_ROW + FILE_ROW).encode(),
    ],
)
def test_parse_snapshot_csv_rejects_missing_or_inconsistent_catalog_identity(payload):
    with pytest.raises(ValueError):
        list(parse_snapshot_csv(payload))


def test_discover_snapshot_download_uses_only_official_descriptor_then_download_endpoints():
    requests = []
    html = """
    <button onclick="fileDetailObj.fn_fileDataDown('15062804', 'uddi:monthly', '', '1', '2')">
      다운로드
    </button>
    """

    def handle(request):
        requests.append(request)
        if request.url.path == "/data/15062804/fileData.do":
            return httpx.Response(200, text=html)
        if request.url.path == "/tcs/dss/selectFileDataDownload.do":
            assert request.method == "POST"
            assert (
                request.content
                == b"publicDataDetailPk=uddi%3Amonthly&publicDataPk=15062804&atchFileId=&fileDetailSn=1&publicDataTyCode=PR0051"
            )
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "atchFileId": "FILE_000000003695488",
                    "fileDetailSn": "1",
                    "dataSetFileDetailInfo": {
                        "publicDataPk": "15062804",
                        "publicDataDetailPk": "uddi:monthly",
                        "dataNm": "목록개방현황 20260731",
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    with PortalHTTP(interval=0, transport=httpx.MockTransport(handle)) as client:
        descriptor = discover_snapshot_download(client)

    assert descriptor == {
        "name": "목록개방현황 20260731",
        "url": "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003695488&fileDetailSn=1&dataNm=%EB%AA%A9%EB%A1%9D%EA%B0%9C%EB%B0%A9%ED%98%84%ED%99%A9+20260731",
    }
    assert [request.url.path for request in requests] == [
        "/data/15062804/fileData.do",
        "/tcs/dss/selectFileDataDownload.do",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"status": False},
        {"status": True, "atchFileId": "FILE", "fileDetailSn": "1"},
        {"status": True, "atchFileId": "FILE", "fileDetailSn": "1", "dataSetFileDetailInfo": {}},
    ],
)
def test_discover_snapshot_download_rejects_invalid_descriptor_payload(payload):
    def handle(request):
        if request.url.path == "/data/15062804/fileData.do":
            return httpx.Response(
                200,
                text="<button onclick=\"fileDetailObj.fn_fileDataDown('15062804', 'uddi:monthly', '', '1', '2')\">다운로드</button>",
            )
        return httpx.Response(200, json=payload)

    with PortalHTTP(interval=0, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError):
            discover_snapshot_download(client)


def test_parse_snapshot_csv_rejects_unicode_catalog_identifiers():
    payload = (HEADERS + FILE_ROW.replace("3049380", "３０４９３８０")).encode()

    with pytest.raises(ValueError):
        list(parse_snapshot_csv(payload))


def test_parse_snapshot_csv_validates_trailing_rows_before_returning_records():
    payload = (HEADERS + FILE_ROW + FILE_ROW.replace("파일", "알수없음")).encode()

    with pytest.raises(ValueError):
        parse_snapshot_csv(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "status": True,
            "atchFileId": "FILE_000000003695488",
            "fileDetailSn": "1",
            "dataSetFileDetailInfo": {
                "publicDataPk": "15062805",
                "publicDataDetailPk": "uddi:monthly",
                "dataNm": "목록개방현황 20260731",
            },
        },
        {
            "status": True,
            "atchFileId": "FILE_000000003695488",
            "fileDetailSn": "1",
            "dataSetFileDetailInfo": {
                "publicDataPk": "15062804",
                "publicDataDetailPk": "uddi:other",
                "dataNm": "목록개방현황 20260731",
            },
        },
        {
            "status": True,
            "atchFileId": "   ",
            "fileDetailSn": "1",
            "dataSetFileDetailInfo": {
                "publicDataPk": "15062804",
                "publicDataDetailPk": "uddi:monthly",
                "dataNm": "목록개방현황 20260731",
            },
        },
        {
            "status": True,
            "atchFileId": "FILE_000000003695488",
            "fileDetailSn": " 1 ",
            "dataSetFileDetailInfo": {
                "publicDataPk": "15062804",
                "publicDataDetailPk": "uddi:monthly",
                "dataNm": "목록개방현황 20260731",
            },
        },
        {
            "status": True,
            "atchFileId": "FILE_000000003695488",
            "fileDetailSn": True,
            "dataSetFileDetailInfo": {
                "publicDataPk": "15062804",
                "publicDataDetailPk": "uddi:monthly",
                "dataNm": "목록개방현황 20260731",
            },
        },
    ],
)
def test_discover_snapshot_download_rejects_mismatched_or_malformed_descriptor_fields(payload):
    def handle(request):
        if request.url.path == "/data/15062804/fileData.do":
            return httpx.Response(
                200,
                text="<button onclick=\"fileDetailObj.fn_fileDataDown('15062804', 'uddi:monthly', '', '1', '2')\">다운로드</button>",
            )
        return httpx.Response(200, json=payload)

    with PortalHTTP(interval=0, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError):
            discover_snapshot_download(client)


def test_snapshot_generations_deduplicate_raw_and_keep_latest_completed_rows(snapshot_pipeline):
    snapshot_pipeline.run(
        snapshot_payload(snapshot_row(1, title="Original")),
        source={"kind": "file", "name": "monthly.csv"},
    )
    before = list(snapshot_pipeline.store.current_records())[0]
    second = snapshot_pipeline.run(
        snapshot_payload(snapshot_row(1, title="Renamed")),
        source={"kind": "file", "name": "monthly.csv"},
    )
    repeated = snapshot_pipeline.run(
        snapshot_payload(snapshot_row(1, title="Renamed")),
        source={"kind": "file", "name": "monthly.csv"},
    )

    current = list(snapshot_pipeline.store.current_records())
    assert snapshot_pipeline.store.db.portal_raw.files.count_documents({}) == 2
    assert snapshot_pipeline.store.db.portal_snapshot_runs.count_documents({"status": "completed"}) == 2
    assert snapshot_pipeline.store.db.portal_snapshot_records.count_documents({}) == 2
    assert current[0]["run_id"] == second["run_id"] == repeated["run_id"]
    assert current[0]["title"] == "Renamed"
    assert current[0]["source_hash"] != before["source_hash"]


def test_invalid_snapshot_does_not_change_completed_generation(snapshot_pipeline):
    first = snapshot_pipeline.run(
        snapshot_payload(snapshot_row(1), snapshot_row(2)), source={"kind": "file"}
    )

    with pytest.raises(ValueError, match="unsupported catalog type"):
        snapshot_pipeline.run(
            snapshot_payload(snapshot_row(1, title="Changed").replace("파일", "알수없음")),
            source={"kind": "file"},
        )

    current = list(snapshot_pipeline.store.current_records())
    assert {record["catalog_id"] for record in current} == {"FILE:1", "FILE:2"}
    assert {record["run_id"] for record in current} == {first["run_id"]}


def test_completed_generation_replaces_membership_without_deleting_history(snapshot_pipeline):
    first = snapshot_pipeline.run(
        snapshot_payload(snapshot_row(1), snapshot_row(2)), source={"kind": "file"}
    )
    second = snapshot_pipeline.run(
        snapshot_payload(snapshot_row(1), snapshot_row(3)), source={"kind": "file"}
    )

    current = list(snapshot_pipeline.store.current_records())
    historical = list(snapshot_pipeline.store.db.portal_snapshot_records.find())
    assert second["status"] == "completed"
    assert {record["catalog_id"] for record in current} == {"FILE:1", "FILE:3"}
    assert {record["run_id"] for record in current} == {second["run_id"]}
    assert {record["run_id"] for record in historical} == {first["run_id"], second["run_id"]}
    assert len(historical) == 4


def test_snapshot_report_reconciles_candidate_generation_and_excludes_linked(snapshot_pipeline):
    catalog = snapshot_pipeline.store.db.portal_catalog
    catalog.insert_many(
        [
            {"_id": "API:1", "data_type": "API", "is_active": True},
            {"_id": "STD:3", "data_type": "STD", "is_active": True},
            {"_id": "LINKED:4", "data_type": "LINKED", "is_active": True},
            {"_id": "FILE:5", "data_type": "FILE", "is_active": False},
        ]
    )

    report = snapshot_pipeline.run(
        snapshot_payload(snapshot_row(1, "API"), snapshot_row(2)), source={"kind": "file"}
    )

    assert report["reconciliation"] == {
        "matched": 1,
        "snapshot_only": 1,
        "current_only": 1,
    }


def test_parse_snapshot_csv_rejects_header_only_snapshot():
    with pytest.raises(ValueError, match="no catalog rows"):
        parse_snapshot_csv(HEADERS.encode())


def test_snapshot_rejects_valid_prefix_that_is_too_small_to_replace_current_generation(snapshot_pipeline):
    snapshot_pipeline.run(
        snapshot_payload(*(snapshot_row(number) for number in range(1, 6))), source={"kind": "file"}
    )

    with pytest.raises(ValueError, match="too incomplete"):
        snapshot_pipeline.run(snapshot_payload(snapshot_row(1)), source={"kind": "file"})

    current = list(snapshot_pipeline.store.current_records())
    assert {record["catalog_id"] for record in current} == {f"FILE:{number}" for number in range(1, 6)}


def test_snapshot_store_serializes_publication_with_a_dedicated_lease(snapshot_pipeline):
    first = snapshot_pipeline.store
    second = store_module.SnapshotStore(first.db)

    first.acquire("first")
    try:
        with pytest.raises(RuntimeError, match="another snapshot publisher"):
            second.acquire("second")
    finally:
        first.release("first")


def test_failed_later_generation_is_invisible_and_marks_its_run_failed(snapshot_pipeline, monkeypatch):
    first = snapshot_pipeline.run(
        snapshot_payload(snapshot_row(1, title="Original"), snapshot_row(2)), source={"kind": "file"}
    )
    collection = snapshot_pipeline.store.db.portal_snapshot_records
    original = collection.update_one
    writes = 0

    def fail_second_staged_write(*args, **kwargs):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise RuntimeError("simulated staged bulk failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(collection, "update_one", fail_second_staged_write)
    with pytest.raises(RuntimeError, match="staged bulk failure"):
        snapshot_pipeline.run(
            snapshot_payload(snapshot_row(1, title="Uncommitted"), snapshot_row(3)),
            source={"kind": "file"},
        )

    failed = snapshot_pipeline.store.db.portal_snapshot_runs.find_one(sort=[("started_at", -1)])
    current = list(snapshot_pipeline.store.current_records())
    assert failed["status"] == "failed"
    assert {record["catalog_id"] for record in current} == {"FILE:1", "FILE:2"}
    assert current[0]["title"] == "Original"
    assert {record["run_id"] for record in current} == {first["run_id"]}
    assert collection.count_documents({"run_id": failed["_id"]}) == 1


def test_completion_of_one_run_document_is_the_visibility_gate(snapshot_pipeline):
    first = snapshot_pipeline.run(snapshot_payload(snapshot_row(1)), source={"kind": "file"})
    running_id = "staged-only"
    snapshot_pipeline.store.db.portal_snapshot_runs.insert_one(
        {"_id": running_id, "status": "running", "started_at": first["run_id"]}
    )
    snapshot_pipeline.store.db.portal_snapshot_records.insert_one(
        {
            "_id": f"{running_id}:FILE:2",
            "run_id": running_id,
            "snapshot_run_id": running_id,
            "catalog_id": "FILE:2",
            "data_type": "FILE",
            "list_id": 2,
            "title": "Staged only",
        }
    )

    assert {record["catalog_id"] for record in snapshot_pipeline.store.current_records()} == {"FILE:1"}

    snapshot_pipeline.store.db.portal_snapshot_runs.update_one(
        {"_id": running_id}, {"$set": {"status": "completed", "completed_at": store_module.now()}}
    )
    assert {record["catalog_id"] for record in snapshot_pipeline.store.current_records()} == {"FILE:2"}


def test_failed_generation_does_not_attempt_rollback_compensation(snapshot_pipeline, monkeypatch):
    collection = snapshot_pipeline.store.db.portal_snapshot_records
    calls = []

    def unexpected_update_many(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("rollback compensation must not run")

    monkeypatch.setattr(collection, "update_many", unexpected_update_many)
    monkeypatch.setattr(
        collection,
        "bulk_write",
        lambda *_, **__: (_ for _ in ()).throw(RuntimeError("simulated bulk failure")),
    )
    with pytest.raises(RuntimeError, match="simulated bulk failure"):
        snapshot_pipeline.run(snapshot_payload(snapshot_row(1)), source={"kind": "file"})

    failed = snapshot_pipeline.store.db.portal_snapshot_runs.find_one()
    assert calls == []
    assert failed["status"] == "failed"


@pytest.mark.parametrize("repeat_initialize", [False, True])
def test_initialize_migrates_completed_legacy_rows_on_first_pass_and_preserves_indexes(repeat_initialize):
    database = mongomock.MongoClient(tz_aware=True).snapshot_migration
    records = database.portal_snapshot_records
    records.create_index([("data_type", 1), ("list_id", 1)], unique=True, name="legacy_identity")
    records.create_index([("legacy_other", 1), ("run_id", 1)], unique=True, name="preserve_other_unique")
    run_id = "legacy-completed"
    database.portal_snapshot_runs.insert_one(
        {
            "_id": run_id,
            "status": "completed",
            "record_count": 1,
            "started_at": store_module.now(),
            "summary": {"run_id": run_id, "status": "completed"},
        }
    )
    records.insert_one(
        {
            "_id": "FILE:1",
            "catalog_id": "FILE:1",
            "data_type": "FILE",
            "list_id": 1,
            "title": "Legacy",
            "source_hash": "legacy-source",
            "legacy_other": "preserve",
            "published_run": run_id,
            "last_seen_run": run_id,
        }
    )

    store = store_module.SnapshotStore(database)
    store.initialize()

    names = {index["name"] for index in records.list_indexes()}
    current = list(store.current_records())
    assert "legacy_identity" not in names
    assert "preserve_other_unique" in names
    assert "run_id_1_catalog_id_1" in names
    assert records.find_one({"_id": "FILE:1"}) is None
    assert store.latest_completed_run()["_id"] == run_id
    assert len(current) == 1
    assert current[0]["_id"] == f"{run_id}:FILE:1"
    assert current[0]["run_id"] == run_id
    assert current[0]["snapshot_run_id"] == run_id
    assert current[0]["title"] == "Legacy"
    assert current[0]["source_hash"] == "legacy-source"
    assert database.portal_snapshot_runs.find_one({"_id": run_id})["completed_at"] is not None

    if repeat_initialize:
        store.initialize()
        assert list(store.current_records()) == current
        assert records.count_documents({}) == 1


def test_initialize_can_resume_after_copying_a_legacy_row_before_its_delete(monkeypatch):
    database = mongomock.MongoClient(tz_aware=True).snapshot_migration_interrupt
    run_id = "legacy-completed"
    database.portal_snapshot_runs.insert_one(
        {
            "_id": run_id,
            "status": "completed",
            "record_count": 1,
            "started_at": store_module.now(),
            "summary": {"run_id": run_id, "status": "completed"},
        }
    )
    records = database.portal_snapshot_records
    records.insert_one(
        {
            "_id": "FILE:1",
            "catalog_id": "FILE:1",
            "data_type": "FILE",
            "list_id": 1,
            "last_seen_run": run_id,
        }
    )
    store = store_module.SnapshotStore(database)
    original_delete = records.delete_one

    monkeypatch.setattr(
        records,
        "delete_one",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("delete interrupted")),
    )
    with pytest.raises(RuntimeError, match="delete interrupted"):
        store.initialize()
    current = list(store.current_records())
    assert len(current) == 1
    assert current[0]["_id"] == f"{run_id}:FILE:1"
    assert current[0]["snapshot_run_id"] == run_id
    assert records.find_one({"_id": "FILE:1"}) is not None

    monkeypatch.setattr(records, "delete_one", original_delete)
    store.initialize()
    assert records.find_one({"_id": "FILE:1"}) is None
    assert records.count_documents({"run_id": run_id}) == 1
    assert list(store.current_records()) == current


def test_initialize_leaves_running_and_failed_legacy_rows_unpublished():
    database = mongomock.MongoClient(tz_aware=True).snapshot_migration_unpublished
    records = database.portal_snapshot_records
    database.portal_snapshot_runs.insert_many(
        [
            {"_id": "running", "status": "running", "record_count": 1},
            {"_id": "failed", "status": "failed", "record_count": 1},
        ]
    )
    records.insert_many(
        [
            {"_id": "FILE:1", "catalog_id": "FILE:1", "last_seen_run": "running"},
            {"_id": "FILE:2", "catalog_id": "FILE:2", "published_run": "failed"},
        ]
    )

    store = store_module.SnapshotStore(database)
    store.initialize()

    assert list(store.current_records()) == []
    assert records.count_documents({"run_id": {"$exists": True}}) == 0
    assert records.count_documents({"_id": {"$in": ["FILE:1", "FILE:2"]}}) == 2


def test_duplicate_raw_replay_repairs_a_completed_generation_missing_rows(snapshot_pipeline):
    payload = snapshot_payload(snapshot_row(1), snapshot_row(2))
    first = snapshot_pipeline.run(payload, source={"kind": "file"})
    snapshot_pipeline.store.db.portal_snapshot_records.delete_one(
        {"_id": f"{first['run_id']}:FILE:2"}
    )

    repaired = snapshot_pipeline.run(payload, source={"kind": "file"})

    current = list(snapshot_pipeline.store.current_records())
    assert repaired["run_id"] != first["run_id"]
    assert snapshot_pipeline.store.db.portal_snapshot_runs.count_documents({"status": "completed"}) == 2
    assert {record["catalog_id"] for record in current} == {"FILE:1", "FILE:2"}
    assert {record["run_id"] for record in current} == {repaired["run_id"]}


def test_initialize_backfills_snapshot_run_marker_on_existing_generation_rows():
    database = mongomock.MongoClient(tz_aware=True).snapshot_generation_backfill
    run_id = "already-generated"
    database.portal_snapshot_runs.insert_one(
        {
            "_id": run_id,
            "status": "completed",
            "record_count": 1,
            "started_at": store_module.now(),
            "completed_at": store_module.now(),
            "summary": {"run_id": run_id, "status": "completed"},
        }
    )
    database.portal_snapshot_records.insert_one(
        {
            "_id": f"{run_id}:FILE:1",
            "run_id": run_id,
            "catalog_id": "FILE:1",
            "data_type": "FILE",
            "list_id": 1,
        }
    )

    store = store_module.SnapshotStore(database)
    store.initialize()

    current = list(store.current_records())
    assert current[0]["snapshot_run_id"] == run_id
