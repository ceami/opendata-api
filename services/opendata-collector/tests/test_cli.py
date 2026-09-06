import json

import httpx

from opendata_collector.cli import main


def test_missing_api_key_fails_before_connecting_to_mongo(monkeypatch, capsys):
    monkeypatch.delenv("ODP_SERVICE_KEY", raising=False)
    assert main(["collect", "--source", "api"]) == 1
    assert "ODP_SERVICE_KEY" in capsys.readouterr().err


def test_preview_writes_inspectable_jsonl_without_mongo(monkeypatch, tmp_path, capsys):
    from opendata_collector.http import PortalHTTP

    listing = """<input name="currentPage" value="1"><input name="perPage" value="1">
    <div class="data-result-tit">오픈API (1건)</div><div class="data-list-group">
    <div class="apply-result-item"><div class="apply-result-link"><a href="/data/123/openapi.do">자료</a></div></div></div>"""
    detail = """<input id="publicDataPk" value="123"><div class="data-info-body">
    <ul class="info-ul"><li><strong class="key">설명</strong><div class="value">공개 메타정보</div></li></ul></div>"""

    def handle(request):
        return httpx.Response(
            200, text=listing if "selectDataSetList" in request.url.path else detail
        )

    monkeypatch.setattr(
        "opendata_collector.cli.PortalHTTP",
        lambda **kwargs: PortalHTTP(interval=0, transport=httpx.MockTransport(handle)),
    )
    output = tmp_path / "preview.jsonl"
    assert (
        main(
            [
                "preview",
                "--source",
                "portal",
                "--types",
                "API",
                "--page-size",
                "1",
                "--limit",
                "1",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    record = json.loads(output.read_text())
    assert record["item"]["catalog_id"] == "API:123"
    assert record["detail"]["metadata"]["설명"] == ["공개 메타정보"]
    assert "Mongo" not in capsys.readouterr().err
