import os
import sys
import uuid
from pathlib import Path

import pytest_asyncio
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient
from motor.motor_asyncio import AsyncIOMotorClient

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE / "src"))
sys.path.insert(0, str(SERVICE.parent / "opendata-collector" / "src"))

from models import (  # noqa: E402
    GeneratedAPIDocs,
    GeneratedFileDocs,
    OpenAPIInfo,
    OpenFileInfo,
    ParsedAPIInfo,
    ParsedFileInfo,
    ParsedLinkedInfo,
    ParsedSTDInfo,
    ParsedSTDMember,
    PortalCatalog,
)


@pytest_asyncio.fixture
async def database():
    # Only this explicit test URI is consulted; never use the application's URI.
    test_uri = os.environ.get("API_SCHEMA_TEST_MONGO_URL")
    client = (
        AsyncIOMotorClient(
            test_uri, tz_aware=True, serverSelectionTimeoutMS=5000
        )
        if test_uri
        else AsyncMongoMockClient(tz_aware=True)
    )
    db = client[f"opendata_schema_test_{uuid.uuid4().hex}"]
    connected = False
    try:
        if test_uri:
            await client.admin.command("ping")
        connected = True
        await init_beanie(
            database=db,
            document_models=[
                OpenAPIInfo,
                OpenFileInfo,
                PortalCatalog,
                ParsedAPIInfo,
                ParsedFileInfo,
                ParsedSTDInfo,
                ParsedLinkedInfo,
                ParsedSTDMember,
                GeneratedAPIDocs,
                GeneratedFileDocs,
            ],
            skip_indexes=True,
        )
        yield db
    finally:
        if connected:
            await client.drop_database(db.name)
        client.close()
