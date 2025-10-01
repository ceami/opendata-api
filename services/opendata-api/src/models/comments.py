from datetime import datetime

from beanie import Document, Indexed
from pydantic import Field

from utils.datetime_util import now_kst


class Comment(Document):
    list_id: Indexed(int)
    content: str
    created_at: datetime = Field(default_factory=now_kst)
    updated_at: datetime | None = None

    class Settings:
        name = "comments"
