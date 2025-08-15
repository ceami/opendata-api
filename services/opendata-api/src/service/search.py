from typing import List, Dict, Any

from elasticsearch import Elasticsearch


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
                    "fields": [
                        "list_title^3",
                        "title^2",
                        "title.korean^2",
                        "keywords^2",
                        "org_nm^1.5",
                        "category_nm^1.5",
                        "dept_nm^1.5",
                        "desc^0.8"
                    ],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                    "operator": "or"
                }
            },
            "highlight": {
                "fields": {
                    "list_title": {},
                    "title": {},
                    "title.korean": {},
                    "keywords": {},
                    "org_nm": {}
                }
            },
            "size": size,
            "from": from_
        }

        try:
            response = self.es.search(index=self.index_name, body=search_body)
            return response["hits"]
        except Exception:
            raise

    def search_titles_with_weights(
        self,
        queries: List[str],
        weights: List[float] = None,
        size: int = 10,
        from_: int = 0
    ) -> Dict[str, Any]:
        if not queries:
            return {"hits": []}

        if weights is None:
            weights = [1.0] * len(queries)

        should_clauses = []

        for i, query in enumerate(queries):
            weight = weights[i] if i < len(weights) else 1.0

            should_clauses.append({
                "multi_match": {
                    "query": query,
                    "fields": [
                        "list_title^3",
                        "title^2",
                        "title.korean^2",
                        "keywords^2",
                        "org_nm^1.5",
                        "category_nm^1.5",
                        "dept_nm^1.5",
                        "desc^0.8"
                    ],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                    "operator": "or",
                    "boost": weight
                }
            })

        search_body = {
            "query": {
                "bool": {
                    "should": should_clauses,
                    "minimum_should_match": 1
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
        except Exception:
            raise

    def search_titles_advanced(
        self,
        primary_queries: List[str] = None,
        secondary_queries: List[str] = None,
        excluded_queries: List[str] = None,
        size: int = 10,
        from_: int = 0
    ) -> Dict[str, Any]:
        bool_query = {}

        if primary_queries:
            must_clauses = []
            for query in primary_queries:
                must_clauses.append({
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "list_title^3",
                            "title^2",
                            "title.korean^2",
                            "keywords^2",
                            "org_nm^1.5",
                            "category_nm^1.5",
                            "dept_nm^1.5",
                            "desc^0.8"
                        ],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                        "operator": "or"
                    }
                })
            bool_query["must"] = must_clauses

        if secondary_queries:
            should_clauses = []
            for query in secondary_queries:
                should_clauses.append({
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "list_title^3",
                            "title^2",
                            "title.korean^2",
                            "keywords^2",
                            "org_nm^1.5",
                            "category_nm^1.5",
                            "dept_nm^1.5",
                            "desc^0.8"
                        ],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                        "operator": "or"
                    }
                })
            bool_query["should"] = should_clauses
            bool_query["minimum_should_match"] = 0

        if excluded_queries:
            must_not_clauses = []
            for query in excluded_queries:
                must_not_clauses.append({
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "list_title",
                            "title",
                            "title.korean",
                            "keywords",
                            "org_nm",
                            "category_nm",
                            "dept_nm",
                            "desc"
                        ],
                        "type": "best_fields"
                    }
                })
            bool_query["must_not"] = must_not_clauses

        search_body = {
            "query": {
                "bool": bool_query
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
        except Exception:
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
        except Exception:
            raise

    def get_index_stats(self) -> Dict[str, Any]:
        try:
            stats = self.es.indices.stats(index=self.index_name)
            return stats["indices"][self.index_name]
        except Exception:
            raise
