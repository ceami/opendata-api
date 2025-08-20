from typing import List, Dict, Any, Optional

from elasticsearch import Elasticsearch


class SearchService:
    def __init__(self, es_client: Elasticsearch):
        self.es = es_client
        self.index_name = "open_data_titles"

    def search_titles(
        self,
        query: str,
        size: int = 10,
        from_: int = 0,
        data_type: Optional[str] = None,
        exact_match: bool = False,
        min_score: Optional[float] = None
    ) -> Dict[str, Any]:
        """제목 기반 검색"""
        query = query.strip()

        if exact_match:
            base_query = self._build_exact_match_query(query)
        else:
            base_query = self._build_fuzzy_match_query(query)

        search_query = self._add_data_type_filter(base_query, data_type)
        search_body = {
            "query": search_query,
            "highlight": self._get_highlight_config(),
            "size": size,
            "from": from_
        }

        if min_score is not None:
            search_body["min_score"] = min_score

        try:
            response = self.es.search(index=self.index_name, body=search_body)
            return response["hits"]
        except Exception:
            raise

    def _build_exact_match_query(self, query: str) -> Dict[str, Any]:
        """정확한 매칭 쿼리를 구성"""
        return {
            "bool": {
                "should": [
                    {
                        "match_phrase": {
                            "list_title": {
                                "query": query,
                                "boost": 3.0
                            }
                        }
                    },
                    {
                        "match_phrase": {
                            "title": {
                                "query": query,
                                "boost": 2.0
                            }
                        }
                    },
                    {
                        "match_phrase": {
                            "org_nm": {
                                "query": query,
                                "boost": 1.5
                            }
                        }
                    }
                ],
                "minimum_should_match": 1
            }
        }

    def _build_fuzzy_match_query(self, query: str) -> Dict[str, Any]:
        """퍼지 매칭 쿼리를 구성"""
        return {
            "bool": {
                "should": [
                    {
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
                            "fuzziness": "1",
                            "operator": "and",
                            "minimum_should_match": "75%"
                        }
                    },
                    {
                        "multi_match": {
                            "query": query,
                            "fields": [
                                "list_title^4",
                                "title^3",
                                "org_nm^2"
                            ],
                            "type": "phrase",
                            "boost": 2.0
                        }
                    }
                ],
                "minimum_should_match": 1
            }
        }

    def _add_data_type_filter(
        self, 
        base_query: Dict[str, Any], 
        data_type: Optional[str]
    ) -> Dict[str, Any]:
        """데이터 타입 필터를 추가"""
        if data_type:
            return {
                "bool": {
                    "must": [
                        base_query,
                        {"term": {"data_type": data_type}}
                    ]
                }
            }
        return base_query

    def _get_highlight_config(self) -> Dict[str, Any]:
        """하이라이트 설정을 반환"""
        return {
            "fields": {
                "list_title": {},
                "title": {},
                "title.korean": {},
                "keywords": {},
                "org_nm": {}
            }
        }

    def search_titles_with_weights(
        self,
        queries: List[str],
        weights: Optional[List[float]] = None,
        size: int = 10,
        from_: int = 0
    ) -> Dict[str, Any]:
        """가중치를 적용한 다중 쿼리 검색"""
        if not queries:
            return {"hits": []}

        if weights is None:
            weights = [1.0] * len(queries)

        should_clauses = []
        for i, query in enumerate(queries):
            weight = weights[i] if i < len(weights) else 1.0
            should_clauses.append(self._build_weighted_query(query, weight))

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

    def _build_weighted_query(self, query: str, weight: float) -> Dict[str, Any]:
        """가중치가 적용된 쿼리를 구성"""
        return {
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
        }

    def search_titles_advanced(
        self,
        primary_queries: Optional[List[str]] = None,
        secondary_queries: Optional[List[str]] = None,
        excluded_queries: Optional[List[str]] = None,
        size: int = 10,
        from_: int = 0
    ) -> Dict[str, Any]:
        """고급 검색"""
        bool_query = {}

        if primary_queries:
            bool_query["must"] = [
                self._build_advanced_query(query) for query in primary_queries
            ]

        if secondary_queries:
            bool_query["should"] = [
                self._build_advanced_query(query) for query in secondary_queries
            ]
            bool_query["minimum_should_match"] = 0

        if excluded_queries:
            bool_query["must_not"] = [
                self._build_exclusion_query(query) for query in excluded_queries
            ]

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

    def _build_advanced_query(self, query: str) -> Dict[str, Any]:
        """고급 검색용 쿼리를 구성"""
        return {
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
        }

    def _build_exclusion_query(self, query: str) -> Dict[str, Any]:
        """제외 쿼리를 구성"""
        return {
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
        }

    def search_titles_with_adaptive_filtering(
        self,
        query: str,
        size: int = 10,
        from_: int = 0,
        data_type: Optional[str] = None,
        max_results_threshold: int = 1000
    ) -> Dict[str, Any]:
        """검색 결과가 너무 많을 때 자동으로 더 엄격한 필터링을 적용"""
        initial_search = self.search_titles(
            query=query,
            size=1,
            from_=0,
            data_type=data_type
        )

        total_results = initial_search["total"]["value"]

        if total_results > max_results_threshold:
            return self.search_titles(
                query=query,
                size=size,
                from_=from_,
                data_type=data_type,
                exact_match=True,
                min_score=10.0
            )
        else:
            return self.search_titles(
                query=query,
                size=size,
                from_=from_,
                data_type=data_type
            )

    def get_all_titles(self, size: int = 1000) -> List[Dict[str, Any]]:
        """모든 제목을 조회"""
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
        """인덱스 통계를 조회"""
        try:
            stats = self.es.indices.stats(index=self.index_name)
            return stats["indices"][self.index_name]
        except Exception:
            raise
