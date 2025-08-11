from typing import List, Dict, Any
from elasticsearch import Elasticsearch
import logging

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self, es_client: Elasticsearch):
        self.es = es_client
        self.index_name = "open_data_titles"

    def search_titles(
        self,
        query: str,
        size: int = 10,
        from_: int = 0
    ) -> Dict[str, Any]:
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

    def get_all_titles(self, size: int = 1000) -> List[Dict[str, Any]]:
        search_body = {
            "query": {
                "match_all": {}
            },
            "size": size,
            "_source": [
                "list_id",
                "list_title",
                "title",
                "category_nm",
                "dept_nm"
            ]
        }

        try:
            response = self.es.search(index=self.index_name, body=search_body)
            return response["hits"]["hits"]
        except Exception as e:
            logger.error(f"전체 제목 조회 중 오류 발생: {e}")
            raise

    def get_index_stats(self) -> Dict[str, Any]:
        try:
            stats = self.es.indices.stats(index=self.index_name)
            return stats["indices"][self.index_name]
        except Exception as e:
            logger.error(f"인덱스 통계 조회 중 오류 발생: {e}")
            raise
