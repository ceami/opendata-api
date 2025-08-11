import os
import asyncio
import logging
from typing import List, Dict, Any
from elasticsearch import Elasticsearch
from models import OpenDataInfo
from core.settings import get_settings


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TitleIndexer:
    def __init__(
        self, mongo_uri: str = None,
        es_hosts: List[str] = None,
    ):
        settings = get_settings()
        if mongo_uri is None:
            mongo_uri = settings.MONGO_URL
        if es_hosts is None:
            es_hosts = [settings.ELASTICSEARCH_URL]

        self.mongo_uri = mongo_uri
        self.es = Elasticsearch(es_hosts)
        self.index_name = settings.ELASTICSEARCH_INDEX_NAME

    async def initialize_beanie(self):
        from motor.motor_asyncio import AsyncIOMotorClient
        from beanie import init_beanie
        
        mongo_client = AsyncIOMotorClient(self.mongo_uri)
        await init_beanie(
            database=mongo_client.open_data,
            document_models=[OpenDataInfo]
        )
        return mongo_client

    async def get_all_open_data_info(self) -> List[Dict[str, Any]]:
        try:
            documents = await OpenDataInfo.find_all().to_list()
            return [doc.model_dump() for doc in documents]
        except Exception as e:
            logger.error(f"OpenDataInfo 조회 중 오류 발생: {e}")
            raise

    def create_elasticsearch_index(self):
        mapping = {
            "mappings": {
                "properties": {
                    "list_title": {
                        "type": "text",
                        "analyzer": "nori_analyzer",
                        "search_analyzer": "nori_analyzer"
                    },
                    "list_id": {
                        "type": "integer"
                    },
                    "title": {
                        "type": "text",
                        "analyzer": "nori_analyzer",
                        "search_analyzer": "nori_analyzer"
                    },
                    "category_nm": {
                        "type": "keyword"
                    },
                    "dept_nm": {
                        "type": "keyword"
                    },
                    "keywords": {
                        "type": "keyword"
                    }
                }
            },
            "settings": {
                "analysis": {
                    "analyzer": {
                        "nori_analyzer": {
                            "type": "nori",
                            "tokenizer": "nori_tokenizer",
                            "filter": ["nori_readingform", "lowercase"]
                        }
                    }
                }
            }
        }

        try:
            if not self.es.indices.exists(index=self.index_name):
                self.es.indices.create(index=self.index_name, body=mapping)
            else:
                logger.info(f"인덱스 {self.index_name}가 이미 존재합니다.")
        except Exception as e:
            logger.error(f"인덱스 생성 중 오류 발생: {e}")
            raise

    def index_documents(self, documents: List[Dict[str, Any]]):
        try:
            for doc in documents:
                es_doc = {
                    "list_id": doc.get("list_id"),
                    "list_title": doc.get("list_title", ""),
                    "title": doc.get("title", ""),
                    "category_nm": doc.get("category_nm", ""),
                    "dept_nm": doc.get("dept_nm", ""),
                    "keywords": doc.get("keywords", [])
                }

                self.es.index(
                    index=self.index_name,
                    id=doc.get("list_id"),
                    body=es_doc
                )

            self.es.indices.refresh(index=self.index_name)
            logger.info(f"{len(documents)}개의 문서가 성공적으로 인덱싱되었습니다.")
        except Exception as e:
            logger.error(f"문서 인덱싱 중 오류 발생: {e}")
            raise

    async def run_indexing(self):
        mongo_client = None
        try:
            mongo_client = await self.initialize_beanie()

            # 1. MongoDB에서 데이터 조회
            documents = await self.get_all_open_data_info()

            if not documents:
                logger.warning("인덱싱할 문서가 없습니다.")
                return

            # 2. Elasticsearch 인덱스 생성
            self.create_elasticsearch_index()

            # 3. 문서 인덱싱
            self.index_documents(documents)

            # 4. 인덱스 통계 출력
            stats = self.es.indices.stats(index=self.index_name)
            total_docs = stats["indices"][self.index_name]["total"]["docs"]["count"]
            logger.info(f"인덱싱 완료! 총 {total_docs}개의 문서가 인덱싱되었습니다.")

        except Exception as e:
            logger.error(f"인덱싱 프로세스 중 오류 발생: {e}")
            raise
        finally:
            if mongo_client:
                mongo_client.close()


async def main():
    indexer = TitleIndexer()
    await indexer.run_indexing()


if __name__ == "__main__":
    asyncio.run(main())
