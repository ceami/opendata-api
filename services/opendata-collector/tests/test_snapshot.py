import httpx
import pytest

from opendata_collector.http import PortalHTTP
from opendata_collector.snapshot import discover_snapshot_download, parse_snapshot_csv

HEADERS = "목록키,목록유형,목록명,목록 URL,제공기관\n"
FILE_ROW = (
    "3049380,파일,한국연구재단 KCI,https://www.data.go.kr/data/3049380/fileData.do,한국연구재단\n"
)
SUFFIXES = {"FILE": "fileData", "API": "openapi", "STD": "standard"}
TYPE_NAMES = {"FILE": "파일", "API": "오픈API", "STD": "표준데이터셋"}


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
                    "dataSetFileDetailInfo": {"dataNm": "목록개방현황 20260731"},
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
