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
import asyncio
import logging
from typing import Any, Dict, List

from elasticsearch import Elasticsearch

from core.settings import get_settings
from models import OpenAPIInfo, OpenFileInfo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TitleIndexer:
    def __init__(
        self,
        mongo_uri: str = None,
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
        from beanie import init_beanie
        from motor.motor_asyncio import AsyncIOMotorClient

        mongo_client = AsyncIOMotorClient(self.mongo_uri)
        await init_beanie(
            database=mongo_client.open_data,
            document_models=[OpenAPIInfo, OpenFileInfo],
        )
        return mongo_client

    async def get_all_open_api_info(self) -> List[Dict[str, Any]]:
        try:
            documents = await OpenAPIInfo.find_all().to_list()
            return [doc.model_dump() for doc in documents]
        except Exception as e:
            logger.error(f"OpenAPIInfo 조회 중 오류 발생: {e}")
            raise

    async def get_all_open_file_info(self) -> List[Dict[str, Any]]:
        try:
            documents = await OpenFileInfo.find_all().to_list()
            return [doc.model_dump() for doc in documents]
        except Exception as e:
            logger.error(f"OpenFileInfo 조회 중 오류 발생: {e}")
            raise

    def create_elasticsearch_index(self):
        """
        Elasticsearch 인덱스 생성 및 매핑 설정
        
        검색 필드 구성:
        - 핵심 검색 필드 (높은 가중치): list_title, title, desc, keywords
        - 필터/태그 검색 (낮은 가중치): category_nm
        """
        mapping = {
            "mappings": {
                "properties": {
                    # 핵심 검색 필드 1: 목록 제목 (한글)
                    "list_title": {
                        "type": "text",
                        "analyzer": "nori_analyzer",
                        "search_analyzer": "nori_analyzer",
                        "fields": {
                            "keyword": {"type": "keyword", "ignore_above": 256},
                            "ngram": {
                                "type": "text",
                                "analyzer": "ngram_analyzer",
                            },
                        },
                    },
                    "list_id": {"type": "integer"},
                    # 핵심 검색 필드 2: 제목 (영문/한글)
                    "title": {
                        "type": "text",
                        "analyzer": "english_analyzer",
                        "search_analyzer": "english_analyzer",
                        "fields": {
                            "keyword": {"type": "keyword", "ignore_above": 256},
                            "korean": {
                                "type": "text",
                                "analyzer": "nori_analyzer",
                            },
                        },
                    },
                    # 필터/태그 검색용 (낮은 가중치)
                    "category_nm": {"type": "keyword"},
                    "dept_nm": {"type": "keyword"},
                    "org_nm": {
                        "type": "text",
                        "analyzer": "nori_analyzer",
                        "search_analyzer": "nori_analyzer",
                    },
                    # 핵심 검색 필드 3: 키워드 배열
                    "keywords": {"type": "keyword"},
                    # 핵심 검색 필드 4: 설명 (한글)
                    "desc": {
                        "type": "text",
                        "analyzer": "nori_analyzer",
                        "search_analyzer": "nori_analyzer",
                    },
                    "data_format": {"type": "keyword"},
                    "api_type": {"type": "keyword"},
                }
            },
            "settings": {
                "analysis": {
                    "analyzer": {
                        "nori_analyzer": {
                            "type": "nori",
                            "tokenizer": "nori_tokenizer",
                            "filter": ["nori_readingform", "lowercase", "trim"],
                        },
                        "english_analyzer": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": [
                                "lowercase",
                                "english_stop",
                                "english_stemmer",
                                "trim",
                            ],
                        },
                        "ngram_analyzer": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase", "ngram_filter"],
                        },
                    },
                    "filter": {
                        "ngram_filter": {
                            "type": "ngram",
                            "min_gram": 2,
                            "max_gram": 3,
                        },
                        "english_stop": {
                            "type": "stop",
                            "stopwords": "_english_",
                        },
                        "english_stemmer": {
                            "type": "stemmer",
                            "language": "english",
                        },
                    },
                },
                "index": {"max_ngram_diff": 50},
            },
        }

        try:
            if not self.es.indices.exists(index=self.index_name):
                self.es.indices.create(index=self.index_name, body=mapping)
        except Exception as e:
            logger.error(f"인덱스 생성 중 오류 발생: {e}")
            raise

    def index_documents(self, documents: List[Dict[str, Any]]):
        try:
            api_count = 0
            file_count = 0

            for doc in documents:
                if "request_cnt" in doc:
                    es_doc = {
                        "list_id": doc.get("list_id"),
                        "list_title": doc.get("list_title", ""),
                        "title": doc.get("title_en", ""),
                        "category_nm": doc.get("category_nm", ""),
                        "dept_nm": doc.get("dept_nm", ""),
                        "org_nm": doc.get("org_nm", ""),
                        "keywords": doc.get("keywords", []),
                        "desc": doc.get("desc", ""),
                        "data_format": doc.get("data_format", ""),
                        "api_type": doc.get("api_type", ""),
                        "data_type": "API",
                    }
                    api_count += 1
                else:
                    es_doc = {
                        "list_id": doc.get("list_id"),
                        "list_title": doc.get("list_title", ""),
                        "title": doc.get("title", ""),
                        "category_nm": doc.get("new_category_nm", ""),
                        "dept_nm": doc.get("dept_nm", ""),
                        "org_nm": doc.get("org_nm", ""),
                        "keywords": doc.get("keywords", []),
                        "desc": doc.get("desc", ""),
                        "data_format": doc.get("data_type", ""),
                        "api_type": "FILE",
                        "data_type": "FILE",
                    }
                    file_count += 1

                self.es.index(
                    index=self.index_name, id=doc.get("list_id"), body=es_doc
                )

            self.es.indices.refresh(index=self.index_name)
            logger.info(
                f"인덱싱 완료! API: {api_count}개, File: {file_count}개, 총 {len(documents)}개"
            )
        except Exception as e:
            logger.error(f"문서 인덱싱 중 오류 발생: {e}")
            raise

    async def run_indexing(self):
        mongo_client = None
        try:
            mongo_client = await self.initialize_beanie()

            api_documents = await self.get_all_open_api_info()
            logger.info(f"API 데이터 {len(api_documents)}개 조회 완료")

            file_documents = await self.get_all_open_file_info()
            logger.info(f"File 데이터 {len(file_documents)}개 조회 완료")

            all_documents = api_documents + file_documents
            logger.info(
                f"총 {len(all_documents)}개의 문서 "
                f"(API: {len(api_documents)}, File: {len(file_documents)})"
            )

            self.create_elasticsearch_index()
            self.index_documents(all_documents)

            stats = self.es.indices.stats(index=self.index_name)
            total_docs = stats["indices"][self.index_name]["total"]["docs"][
                "count"
            ]
            logger.info(
                f"인덱싱 완료! 총 {total_docs}개의 문서가 인덱싱되었습니다."
            )

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
