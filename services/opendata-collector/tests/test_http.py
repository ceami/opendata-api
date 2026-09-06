import httpx
import pytest

from opendata_collector.http import FetchError, PortalHTTP


def test_retries_rate_limit_and_never_sends_service_key_to_portal():
    seen = []
    delays = []

    def handle(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, text='{"data":[]}')

    with PortalHTTP(
        service_key="secret%2Bkey",
        interval=0,
        retries=2,
        transport=httpx.MockTransport(handle),
        sleep=delays.append,
    ) as client:
        client.get("https://api.odcloud.kr/api/15077093/v1/open-data-list?page=1", auth=True)
        client.get("https://www.data.go.kr/catalog/123/openapi.json")
    assert delays == [2.0]
    assert seen[1].headers["Authorization"] == "Infuser secret+key"
    assert "Authorization" not in seen[2].headers
    assert all("secret" not in str(request.url) for request in seen)


def test_unauthorized_is_not_retried_or_exposed_in_error():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(401, text="echoed-secret")

    with PortalHTTP(interval=0, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(FetchError, match="HTTP 401") as error:
            client.get("https://api.odcloud.kr/api/15077093/v1/file-data-list")
    assert len(requests) == 1
    assert "echoed-secret" not in str(error.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.data.go.kr/catalog/1/openapi.json",
        "https://127.0.0.1/a",
        "https://www.data.go.kr.evil.test/a",
        "https://www.data.go.kr/tcs/dss/addApiLinkPrcuse.do",
    ],
)
def test_unapproved_destinations_and_usage_mutations_are_rejected(url):
    with PortalHTTP(interval=0) as client:
        with pytest.raises(FetchError):
            client.get(url)


def test_redirect_is_revalidated_without_forwarding_credentials():
    def handle(request):
        return httpx.Response(302, headers={"Location": "https://localhost/private"})

    with PortalHTTP(interval=0, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(FetchError, match="destination"):
            client.get("https://www.data.go.kr/catalog/1/openapi.json")


def test_oversized_response_fails_instead_of_truncating():
    with PortalHTTP(
        interval=0,
        max_bytes=3,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"1234")),
    ) as client:
        with pytest.raises(FetchError, match="size"):
            client.get("https://www.data.go.kr/catalog/1/openapi.json")


def test_network_failure_stops_after_retry_budget():
    requests = []

    def handle(request):
        requests.append(request)
        raise httpx.ReadTimeout("secret-bearing message", request=request)

    with PortalHTTP(
        interval=0, retries=2, sleep=lambda _: None, transport=httpx.MockTransport(handle)
    ) as client:
        with pytest.raises(FetchError, match="Network") as error:
            client.get("https://www.data.go.kr/catalog/1/openapi.json")
    assert len(requests) == 3
    assert "secret-bearing" not in str(error.value)


def test_infuser_staged_openapi_path_is_narrowly_allowed():
    from opendata_collector.http import validate_url

    validate_url("https://infuser.odcloud.kr/api/stages/28493/api-docs?1728017570963")
    for url in (
        "https://infuser.odcloud.kr/api/stages/not-a-number/api-docs",
        "https://infuser.odcloud.kr/api/stages/28493/admin",
        "https://infuser.odcloud.kr/api/stages/28493/api-docs/extra",
    ):
        with pytest.raises(FetchError):
            validate_url(url)


def test_snapshot_descriptor_post_and_final_download_get_are_narrowly_allowed():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=b"ok")

    with PortalHTTP(interval=0, transport=httpx.MockTransport(handle)) as client:
        client.request(
            "POST",
            "https://www.data.go.kr/tcs/dss/selectFileDataDownload.do",
            data={"publicDataPk": "15062804"},
        )
        client.get(
            "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_1&fileDetailSn=1"
        )
        with pytest.raises(FetchError):
            client.request("POST", "https://www.data.go.kr/cmm/cmm/fileDownload.do")
        with pytest.raises(FetchError):
            client.get("https://www.data.go.kr/cmm/cmm/otherDownload.do")

    assert [request.url.path for request in requests] == [
        "/tcs/dss/selectFileDataDownload.do",
        "/cmm/cmm/fileDownload.do",
    ]
