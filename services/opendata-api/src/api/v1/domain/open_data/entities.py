# Copyright 2025 Team Aeris
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DataKind(str, Enum):
    API = "API"
    FILE = "FILE"


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _ensure_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _ensure_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


@dataclass(slots=True)
class UnifiedDataItem:
    list_id: int
    title: str
    description: str | None
    department: str | None
    category: str | None
    data_type: str
    data_format: str | None
    pricing: Any | None
    copyright: Any | None
    third_party_copyright: Any | None
    keywords: list[str] = field(default_factory=list)
    register_status: str | None = None
    request_cnt: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    use_prmisn_ennc: str | None = None
    title_en: str | None = None
    api_type: str | None = None
    endpoints: Any | None = None
    has_generated_doc: bool = False
    token_count: int = 0
    score: float | None = None

    def __post_init__(self) -> None:
        self.title = str(self.title) if self.title is not None else ""
        self.description = _ensure_str_or_none(self.description)
        self.department = _ensure_str_or_none(self.department)
        self.category = _ensure_str_or_none(self.category)
        self.data_format = _ensure_str_or_none(self.data_format)
        self.register_status = _ensure_str_or_none(self.register_status)
        self.use_prmisn_ennc = _ensure_str_or_none(self.use_prmisn_ennc)
        self.title_en = _ensure_str_or_none(self.title_en)
        self.api_type = _ensure_str_or_none(self.api_type)

        self.keywords = _ensure_str_list(self.keywords)
        self.request_cnt = _coerce_int(self.request_cnt, default=0)
        self.token_count = _coerce_int(self.token_count, default=0)

        self.created_at = _coerce_datetime(self.created_at)
        self.updated_at = _coerce_datetime(self.updated_at)

        if isinstance(self.data_type, DataKind):
            self.data_type = self.data_type.value
        elif str(self.data_type) not in (
            DataKind.API.value,
            DataKind.FILE.value,
        ):
            self.data_type = DataKind.API.value


@dataclass(slots=True)
class GeneratedDocMeta:
    list_id: int
    data_type: str
    token_count: int = 0
    generated_at: datetime | None = None
    has_generated_doc: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.data_type, DataKind):
            self.data_type = self.data_type.value
        elif str(self.data_type) not in (
            DataKind.API.value,
            DataKind.FILE.value,
        ):
            self.data_type = DataKind.API.value
        self.token_count = _coerce_int(self.token_count, default=0)
        self.generated_at = _coerce_datetime(self.generated_at)


@dataclass(slots=True)
class RankedItem:
    list_id: int
    data_type: str
    list_title: str | None = None
    org_nm: str | None = None
    token_count: int = 0
    has_generated_doc: bool = False
    updated_at: datetime | None = None
    generated_at: datetime | None = None
    popularity_score: int = 0
    trending_score: float | None = None
    rank: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.data_type, DataKind):
            self.data_type = self.data_type.value
        elif str(self.data_type) not in (
            DataKind.API.value,
            DataKind.FILE.value,
        ):
            self.data_type = DataKind.API.value
        self.token_count = _coerce_int(self.token_count, default=0)
        self.popularity_score = _coerce_int(self.popularity_score, default=0)
        self.rank = (
            None if self.rank is None else _coerce_int(self.rank, default=0)
        )
        self.updated_at = _coerce_datetime(self.updated_at)
        self.generated_at = _coerce_datetime(self.generated_at)
