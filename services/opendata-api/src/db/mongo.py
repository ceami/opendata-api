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
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from models import (
    Comment,
    DocRecommendation,
    GeneratedAPIDocs,
    GeneratedFileDocs,
    OpenAPIInfo,
    OpenFileInfo,
    RankLatest,
    RankMetadata,
    RankPopular,
    RankTrending,
    SavedRequest,
)


class MongoDB:
    _client: AsyncIOMotorClient | None = None
    _database: AsyncIOMotorDatabase | None = None

    @classmethod
    async def init(cls, mongo_uri: str, database_name: str):
        cls._client = AsyncIOMotorClient(mongo_uri)
        cls._database = AsyncIOMotorDatabase(cls._client, database_name)
        await init_beanie(
            database=cls._database,
            document_models=[
                Comment,
                OpenAPIInfo,
                OpenFileInfo,
                GeneratedFileDocs,
                GeneratedAPIDocs,
                RankLatest,
                RankPopular,
                RankTrending,
                RankMetadata,
                SavedRequest,
                DocRecommendation,
            ],
        )

    @classmethod
    def get_db(cls) -> AsyncIOMotorDatabase:
        if cls._database is None:
            raise RuntimeError("MongoDB가 초기화되지 않았습니다.")
        return cls._database

    @classmethod
    def get_client(cls) -> AsyncIOMotorClient:
        if cls._client is None:
            raise RuntimeError("MongoDB가 초기화되지 않았습니다.")
        return cls._client

    @classmethod
    async def close(cls):
        if cls._client:
            cls._client.close()
            cls._client = None
            cls._database = None
