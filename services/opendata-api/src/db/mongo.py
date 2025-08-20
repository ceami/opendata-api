from beanie import init_beanie
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
