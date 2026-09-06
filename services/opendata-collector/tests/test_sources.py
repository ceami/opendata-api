import httpx
import pytest

from opendata_collector.http import PortalHTTP
from opendata_collector.sources import CatalogSource, parse_api_page


def envelope(rows, **overrides):
    return {
        "page": 1,
        "perPage": 2,
        "totalCount": 3,
        "matchCount": 3,
        "currentCount": len(rows),
        "data": rows,
        **overrides,
    }


def test_operations_with_same_list_id_are_kept_as_distinct_source_records():
    payload = envelope(
        [
            {
                "id": "service-1",
                "list_id": "123",
                "operation_seq": "1",
                "list_title": "교통",
                "extra": {"x": 1},
            },
            {"id": "service-1", "list_id": "123", "operation_seq": "2", "list_title": "교통"},
        ]
    )
    page = parse_api_page(payload, "API", 1, 2)
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["items"][0]["catalog_id"] == "API:123"
    assert page["items"][0]["source_id"] != page["items"][1]["source_id"]
    assert page["items"][0]["source_record"]["extra"] == {"x": 1}


@pytest.mark.parametrize(
    "overrides",
    [
        {"page": 2},
        {"currentCount": 0},
        {"matchCount": -1},
        {"data": []},
        {"perPage": 1},
        {"data": "error"},
    ],
)
def test_malformed_or_unexpected_envelopes_cannot_look_like_completion(overrides):
    payload = envelope([{"id": "a", "list_id": "123"}], **overrides)
    with pytest.raises(ValueError):
        parse_api_page(payload, "FILE", 1, 2)


def test_zero_count_and_partial_final_page_are_valid():
    assert parse_api_page(envelope([], totalCount=0, matchCount=0), "FILE", 1, 2)["items"] == []
    page = parse_api_page(envelope([{"id": "a", "list_id": "123"}], page=2), "FILE", 2, 2)
    assert len(page["items"]) == 1


def test_missing_identifier_and_repeated_source_record_fail():
    for rows in [[{"id": "a"}], [{"id": "a", "list_id": "123"}] * 2]:
        with pytest.raises(ValueError):
            parse_api_page(envelope(rows), "API", 1, 2)


def test_auto_source_uses_authenticated_official_endpoint_and_preserves_raw_body():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(
            200, json=envelope([{"id": "a", "list_id": "123"}], totalCount=1, matchCount=1)
        )

    with PortalHTTP(
        service_key="test-key", interval=0, transport=httpx.MockTransport(handle)
    ) as client:
        source = CatalogSource(client, mode="auto")
        page, raw = source.page("FILE", 1, 2)
    assert (
        str(seen[0].url) == "https://api.odcloud.kr/api/15077093/v1/file-data-list?page=1&perPage=2"
    )
    assert page["source"] == "api"
    assert b'"list_id":"123"' in raw.content


def test_api_mode_requires_key_instead_of_silently_falling_back():
    with PortalHTTP(interval=0) as client:
        with pytest.raises(ValueError, match="ODP_SERVICE_KEY"):
            CatalogSource(client, mode="api")
