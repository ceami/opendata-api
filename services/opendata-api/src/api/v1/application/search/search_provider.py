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
from typing import Any

from elasticsearch import Elasticsearch


class SearchProvider:
    def __init__(self, es_client: Elasticsearch):
        self.es = es_client
        self.index_name = "open_data_titles"

    def search_titles(
        self,
        query: str,
        size: int = 10,
        from_: int = 0,
        data_type: str | None = None,
        exact_match: bool = False,
        min_score: float | None = None,
    ) -> dict[str, Any]:
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
            "from": from_,
        }

        if min_score is not None:
            search_body["min_score"] = min_score

        try:
            response = self.es.search(index=self.index_name, body=search_body)
            return response["hits"]
        except Exception:
            raise

    def _build_exact_match_query(self, query: str) -> dict[str, Any]:
        return {
            "bool": {
                "should": [
                    {"match_phrase": {"list_title": {"query": query, "boost": 3.0}}},
                    {"match_phrase": {"title": {"query": query, "boost": 2.0}}},
                    {"match_phrase": {"org_nm": {"query": query, "boost": 1.5}}},
                ],
                "minimum_should_match": 1,
            }
        }

    def _build_fuzzy_match_query(self, query: str) -> dict[str, Any]:
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
                                "desc^0.8",
                            ],
                            "type": "best_fields",
                            "fuzziness": "1",
                            "operator": "and",
                            "minimum_should_match": "75%",
                        }
                    },
                    {
                        "multi_match": {
                            "query": query,
                            "fields": ["list_title^4", "title^3", "org_nm^2"],
                            "type": "phrase",
                            "boost": 2.0,
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        }

    def _add_data_type_filter(
        self, base_query: dict[str, Any], data_type: str | None
    ) -> dict[str, Any]:
        if data_type:
            return {"bool": {"must": [base_query, {"term": {"data_type": data_type}}]}}
        return base_query

    def _get_highlight_config(self) -> dict[str, Any]:
        return {
            "fields": {
                "list_title": {},
                "title": {},
                "title.korean": {},
                "keywords": {},
                "org_nm": {},
            }
        }

    def search_titles_with_weights(
        self,
        queries: list[str],
        weights: list[float] | None = None,
        size: int = 10,
        from_: int = 0,
    ) -> dict[str, Any]:
        if not queries:
            return {"hits": []}

        if weights is None:
            weights = [1.0] * len(queries)

        should_clauses = []
        for i, query in enumerate(queries):
            weight = weights[i] if i < len(weights) else 1.0
            should_clauses.append(self._build_weighted_query(query, weight))

        search_body = {
            "query": {"bool": {"should": should_clauses, "minimum_should_match": 1}},
            "highlight": {"fields": {"list_title": {}, "title": {}}},
            "size": size,
            "from": from_,
        }

        try:
            response = self.es.search(index=self.index_name, body=search_body)
            return response["hits"]
        except Exception:
            raise

    def _build_weighted_query(self, query: str, weight: float) -> dict[str, Any]:
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
                    "desc^0.8",
                ],
                "type": "best_fields",
                "fuzziness": "AUTO",
                "operator": "or",
                "boost": weight,
            }
        }

    def search_titles_with_adaptive_filtering(
        self,
        query: str,
        size: int = 10,
        from_: int = 0,
    ) -> dict[str, Any]:
        """적응형 필터링을 사용한 검색"""
        query = query.strip()

        strict_query = {
            "bool": {
                "should": [
                    {
                        "multi_match": {
                            "query": query,
                            "fields": ["list_title^3", "title^2", "org_nm^1.5"],
                            "type": "phrase",
                            "boost": 2.0,
                        }
                    },
                    {
                        "multi_match": {
                            "query": query,
                            "fields": [
                                "list_title^3",
                                "title^2",
                                "keywords^2",
                                "org_nm^1.5",
                            ],
                            "type": "best_fields",
                            "operator": "and",
                            "minimum_should_match": "100%",
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        }

        search_body = {
            "query": strict_query,
            "highlight": self._get_highlight_config(),
            "size": size,
            "from": from_,
        }

        try:
            response = self.es.search(index=self.index_name, body=search_body)
            hits = response["hits"]

            if hits["total"]["value"] >= size:
                return hits

            relaxed_query = self._build_fuzzy_match_query(query)
            search_body["query"] = relaxed_query

            response = self.es.search(index=self.index_name, body=search_body)
            return response["hits"]

        except Exception:
            raise

    def get_index_stats(self) -> dict[str, Any]:
        try:
            stats = self.es.indices.stats(index=self.index_name)
            return stats["indices"][self.index_name]
        except Exception:
            raise
