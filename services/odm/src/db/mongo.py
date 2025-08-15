from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from models import APIStdDocument, OpenDataInfo, ParsedAPIInfo


class MongoDB:
    @classmethod
    async def init(cls, mongo_uri: str, database_name: str):
        client = AsyncIOMotorClient(mongo_uri)
        await init_beanie(
            database=AsyncIOMotorDatabase(client, database_name),
            document_models=[APIStdDocument, OpenDataInfo, ParsedAPIInfo],
        )

    @classmethod
    async def close(cls):
        await MongoDB.get_db().client.close()
