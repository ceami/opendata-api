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


def test_snapshot_deduplicates_unchanged_raw_csv_and_replaces_latest_row_fields(snapshot_pipeline):
    first = snapshot_pipeline.run(
        snapshot_payload(snapshot_row(1, title="Original")),
        source={"kind": "file", "name": "monthly.csv"},
    )
    before = snapshot_pipeline.store.db.portal_snapshot_records.find_one({"_id": "FILE:1"})
    second = snapshot_pipeline.run(
        snapshot_payload(snapshot_row(1, title="Renamed")),
        source={"kind": "file", "name": "monthly.csv"},
    )

    third = snapshot_pipeline.run(
        snapshot_payload(snapshot_row(1, title="Renamed")),
        source={"kind": "file", "name": "monthly.csv"},
    )

    records = list(snapshot_pipeline.store.db.portal_snapshot_records.find())
    current = records[0]
    assert snapshot_pipeline.store.db.portal_raw.files.count_documents({}) == 2
    assert len(records) == 1
    assert current["title"] == "Renamed"
    assert current["source_hash"] != before["source_hash"]
    assert current["last_seen_run"] == third["run_id"]
    assert first["raw_id"] != second["raw_id"] == third["raw_id"]


def test_snapshot_rejects_invalid_payload_before_retiring_current_rows(snapshot_pipeline):
    snapshot_pipeline.run(snapshot_payload(snapshot_row(1), snapshot_row(2)), source={"kind": "file"})

    with pytest.raises(ValueError, match="unsupported catalog type"):
        snapshot_pipeline.run(
            snapshot_payload(snapshot_row(1, title="Changed").replace("파일", "알수없음")),
            source={"kind": "file"},
        )

    records = list(snapshot_pipeline.store.db.portal_snapshot_records.find({"is_active": True}))
    assert {record["_id"] for record in records} == {"FILE:1", "FILE:2"}


def test_snapshot_retires_unseen_rows_only_after_a_complete_valid_snapshot(snapshot_pipeline):
    snapshot_pipeline.run(snapshot_payload(snapshot_row(1), snapshot_row(2)), source={"kind": "file"})

    report = snapshot_pipeline.run(
        snapshot_payload(snapshot_row(1), snapshot_row(3)), source={"kind": "file"}
    )

    current = snapshot_pipeline.store.db.portal_snapshot_records.find_one({"_id": "FILE:1"})
    retired = snapshot_pipeline.store.db.portal_snapshot_records.find_one({"_id": "FILE:2"})
    assert report["status"] == "completed"
    assert current["is_active"] is True
    assert retired["is_active"] is False
    assert retired["removed_at"] is not None


def test_snapshot_report_reconciles_snapshot_and_authoritative_current_records(snapshot_pipeline):
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


def test_snapshot_rejects_valid_prefix_that_is_too_small_to_retire_current_rows(snapshot_pipeline):
    snapshot_pipeline.run(
        snapshot_payload(*(snapshot_row(number) for number in range(1, 6))), source={"kind": "file"}
    )

    with pytest.raises(ValueError, match="too incomplete"):
        snapshot_pipeline.run(snapshot_payload(snapshot_row(1)), source={"kind": "file"})

    active = list(snapshot_pipeline.store.db.portal_snapshot_records.find({"is_active": True}))
    assert {record["_id"] for record in active} == {f"FILE:{number}" for number in range(1, 6)}


def test_snapshot_store_serializes_publication_with_a_dedicated_lease(snapshot_pipeline):
    first = snapshot_pipeline.store
    second = store_module.SnapshotStore(first.db)

    first.acquire("first")
    try:
        with pytest.raises(RuntimeError, match="another snapshot publisher"):
            second.acquire("second")
    finally:
        first.release("first")


def test_failed_snapshot_run_is_finalized_without_retiring_current_rows(snapshot_pipeline, monkeypatch):
    snapshot_pipeline.run(snapshot_payload(snapshot_row(1), snapshot_row(2)), source={"kind": "file"})
    collection = snapshot_pipeline.store.db.portal_snapshot_records

    def fail_bulk_write(*_, **__):
        raise RuntimeError("simulated bulk failure")

    monkeypatch.setattr(collection, "bulk_write", fail_bulk_write)
    with pytest.raises(RuntimeError, match="simulated bulk failure"):
        snapshot_pipeline.run(snapshot_payload(snapshot_row(1), snapshot_row(3)), source={"kind": "file"})

    failed = snapshot_pipeline.store.db.portal_snapshot_runs.find_one(sort=[("started_at", -1)])
    active = list(collection.find({"is_active": True}))
    assert failed["status"] == "failed"
    assert {record["_id"] for record in active} == {"FILE:1", "FILE:2"}


def test_failed_retirement_rolls_back_rows_marked_by_the_failed_run(snapshot_pipeline, monkeypatch):
    snapshot_pipeline.run(snapshot_payload(snapshot_row(1), snapshot_row(2)), source={"kind": "file"})
    collection = snapshot_pipeline.store.db.portal_snapshot_records
    original = collection.update_many

    def retire_then_fail(selector, update, **kwargs):
        if selector.get("last_seen_run", {}).get("$ne"):
            original(selector, update, **kwargs)
            raise RuntimeError("simulated retirement acknowledgement loss")
        return original(selector, update, **kwargs)

    monkeypatch.setattr(collection, "update_many", retire_then_fail)
    with pytest.raises(RuntimeError, match="retirement acknowledgement loss"):
        snapshot_pipeline.run(snapshot_payload(snapshot_row(1), snapshot_row(3)), source={"kind": "file"})

    active = list(collection.find({"is_active": True}))
    assert {record["_id"] for record in active} == {"FILE:1", "FILE:2"}


def test_completed_snapshot_records_the_completed_generation(snapshot_pipeline):
    report = snapshot_pipeline.run(snapshot_payload(snapshot_row(1)), source={"kind": "file"})

    state = snapshot_pipeline.store.db.portal_snapshot_state.find_one({"_id": "current"})
    assert state["active_run_id"] == report["run_id"]
