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
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    """현재 한국 시간(KST)을 반환"""
    return datetime.now(KST)


def utc_to_kst(utc_dt: datetime) -> datetime:
    """UTC datetime을 KST로 변환"""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(KST)


def kst_to_utc(kst_dt: datetime) -> datetime:
    """KST datetime을 UTC로 변환"""
    if kst_dt.tzinfo is None:
        kst_dt = kst_dt.replace(tzinfo=KST)
    return kst_dt.astimezone(timezone.utc)


def format_datetime(dt: datetime | None) -> str | None:
    """datetime을 ISO 형식 문자열로 변환"""
    if dt is None:
        return None
    return dt.isoformat()
