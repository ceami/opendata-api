from datetime import datetime, timezone

import pytest

from opendata_collector.projection import project_legacy


@pytest.mark.parametrize(
    "source,metadata,expected",
    [
        ({"data_type": "FILE"}, {"확장자": ["CSV"]}, "CSV"),
        ({"data_type": "CSV"}, {}, "CSV"),
        ({"data_type": "FILE", "data_format": "XLSX"}, {"확장자": ["CSV"]}, "XLSX"),
        ({"data_type": "FILE"}, {}, None),
    ],
)
def test_file_kind_does_not_overwrite_file_format(source, metadata, expected):
    item = {
        "data_type": "FILE",
        "list_id": 7,
        "catalog_id": "FILE:7",
        "title": "public",
        "detail_url": "https://www.data.go.kr/data/7/fileData.do",
    }
    _, fields = project_legacy(item, {"metadata": metadata}, datetime.now(timezone.utc), source)
    assert fields["data_type"] == "FILE"
    assert fields["data_format"] == expected
