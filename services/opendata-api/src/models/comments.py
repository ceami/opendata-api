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
from datetime import datetime

from beanie import Document
from pydantic import Field

from utils.datetime_util import now_kst


class Comment(Document):
    list_id: int
    content: str
    created_at: datetime = Field(default_factory=now_kst)
    updated_at: datetime | None = None

    class Settings:
        name = "comments"
