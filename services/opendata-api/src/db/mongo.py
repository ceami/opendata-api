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
# limitations under the License.from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from models import OpenAPIInfo, OpenFileInfo


class MongoDB:
    @classmethod
    async def init(cls, mongo_uri: str, database_name: str):
        client = AsyncIOMotorClient(mongo_uri)
        await init_beanie(
            database=AsyncIOMotorDatabase(client, database_name),
            document_models=[OpenAPIInfo, OpenFileInfo],
        )

    @classmethod
    async def close(cls):
        await MongoDB.get_db().client.close()
