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


def test_parse_arguments_support_types_limit_and_force():
    from opendata_collector.cli import parser

    args = parser().parse_args(["parse", "--types", "FILE", "STD", "--limit", "10", "--force"])

    assert args.command == "parse"
    assert args.types == ["FILE", "STD"]
    assert args.limit == 10
    assert args.force is True


def test_parse_dispatches_without_constructing_http(monkeypatch, capsys):
    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    mongo_store = type("MongoStoreStub", (), {"db": object()})()
    parse_store = object()
    observed = {}

    class PipelineStub:
        def __init__(self, value):
            assert value is parse_store

        def run(self, types, limit=None, force=False):
            observed.update(types=types, limit=limit, force=force)
            return {"status": "completed", "parsed": 2, "failed": 0}

    monkeypatch.setattr("opendata_collector.cli._mongo", lambda: (Client(), mongo_store))
    monkeypatch.setattr("opendata_collector.cli.ParseStore", lambda db: parse_store)
    monkeypatch.setattr("opendata_collector.cli.ParsePipeline", PipelineStub)
    monkeypatch.setattr(
        "opendata_collector.cli.PortalHTTP",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("HTTP must not be constructed")),
    )

    assert main(["parse", "--types", "API", "LINKED", "--limit", "2", "--force"]) == 0
    assert observed == {"types": ["API", "LINKED"], "limit": 2, "force": True}
    assert json.loads(capsys.readouterr().out)["parsed"] == 2


def test_parse_reports_parser_errors_without_http(monkeypatch, capsys):
    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    mongo_store = type("MongoStoreStub", (), {"db": object()})()

    class PipelineStub:
        def __init__(self, _):
            pass

        def run(self, **_):
            raise ValueError("invalid parsed source")

    monkeypatch.setattr("opendata_collector.cli._mongo", lambda: (Client(), mongo_store))
    monkeypatch.setattr("opendata_collector.cli.ParseStore", lambda db: object())
    monkeypatch.setattr("opendata_collector.cli.ParsePipeline", PipelineStub)
    monkeypatch.setattr(
        "opendata_collector.cli.PortalHTTP",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("HTTP must not be constructed")),
    )

    assert main(["parse"]) == 1
    assert "Parsing failed: invalid parsed source" in capsys.readouterr().err
