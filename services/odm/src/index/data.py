from elasticsearch import Elasticsearch
from typing import List, Dict, Any
import logging
from core.settings import get_settings

logger = logging.getLogger(__name__)


class ElasticsearchService:
    def __init__(self, hosts: List[str] = None):
        settings = get_settings()
        if hosts is None:
            hosts = [settings.ELASTICSEARCH_URL]

        self.es = Elasticsearch(hosts)
        self.index_name = settings.ELASTICSEARCH_INDEX_NAME

    def create_index(self):
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
                logger.info(f"인덱스 {self.index_name}가 성공적으로 생성되었습니다.")
            else:
                logger.info(f"인덱스 {self.index_name}가 이미 존재합니다.")
        except Exception as e:
            logger.error(f"인덱스 생성 중 오류 발생: {e}")
            raise

    def index_documents(self, documents: List[Dict[str, Any]]):
        try:
            for doc in documents:
                self.es.index(
                    index=self.index_name,
                    id=doc["list_id"],
                    body=doc
                )
            self.es.indices.refresh(index=self.index_name)
            logger.info(f"{len(documents)}개의 문서가 성공적으로 인덱싱되었습니다.")
        except Exception as e:
            logger.error(f"문서 인덱싱 중 오류 발생: {e}")
            raise

    def search_titles(self, query: str, size: int = 10, from_: int = 0):
        search_body = {
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["list_title^2", "title"],
                    "type": "best_fields",
                    "fuzziness": "AUTO"
                }
            },
            "highlight": {
                "fields": {
                    "list_title": {},
                    "title": {}
                }
            },
            "size": size,
            "from": from_
        }

        try:
            response = self.es.search(index=self.index_name, body=search_body)
            return response["hits"]
        except Exception as e:
            logger.error(f"검색 중 오류 발생: {e}")
            raise

    def get_all_titles(self, size: int = 1000):
        search_body = {
            "query": {
                "match_all": {}
            },
            "size": size,
            "_source": ["list_id", "list_title", "title", "category_nm", "dept_nm"]
        }

        try:
            response = self.es.search(index=self.index_name, body=search_body)
            return response["hits"]["hits"]
        except Exception as e:
            logger.error(f"전체 제목 조회 중 오류 발생: {e}")
            raise

    def get_index_stats(self):
        try:
            stats = self.es.indices.stats(index=self.index_name)
            return stats["indices"][self.index_name]
        except Exception as e:
            logger.error(f"인덱스 통계 조회 중 오류 발생: {e}")
            raise
