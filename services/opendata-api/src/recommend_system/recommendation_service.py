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
import logging
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from pymilvus import MilvusClient

from core.settings import get_settings
from models import DocRecommendation
from models.open_data import RecommendationItem

logger = logging.getLogger(__name__)


class RecommendationService:
    def __init__(
        self,
        milvus_uri: str | None = None,
        collection_name: str = "recommendation_db",
    ):
        if milvus_uri is None:
            milvus_uri = get_settings().MILVUS_URL
        self.milvus_client = MilvusClient(uri=milvus_uri)
        self.collection_name = collection_name

    def _create_embedding_text(self, doc: dict) -> str:
        """문서의 핵심 필드를 결합하여 임베딩용 텍스트를 생성"""
        title = doc.get("list_title", "")
        desc = doc.get("desc", "")
        keywords = " ".join(doc.get("keywords", []))

        embedding_text = f"{title}. {desc}. 핵심키워드: {keywords}"
        return embedding_text

    async def get_recommendations_from_cache(
        self, doc_id: str, top_k: int = 4
    ) -> list[dict[str, Any]] | None:
        """MongoDB 캐시에서 추천 결과 조회"""
        try:
            result = await DocRecommendation.find_one(
                DocRecommendation.target_doc_id == doc_id,
            )

            if result:
                recommendations = []
                for item in result.recommendations[:top_k]:
                    recommendations.append(
                        {
                            "doc_id": item.doc_id,
                            "doc_type": item.doc_type,
                            "similarity_score": item.similarity_score,
                            "rank": item.rank,
                        }
                    )

                logger.info(
                    f"캐시에서 추천 조회 완료: {doc_id} -> {len(recommendations)}개"
                )
                return recommendations
            else:
                logger.info(f"캐시에 추천 없음 또는 만료됨: {doc_id}")
                return None

        except Exception as e:
            logger.error(f"캐시 추천 조회 실패: {e}")
            return None

    def get_recommendations_realtime(
        self, doc_id: str, top_k: int = 4, threshold: float = 0.5
    ) -> list[dict[str, Any]]:
        """Milvus를 사용한 실시간 추천"""
        try:
            target_result = self.milvus_client.query(
                collection_name=self.collection_name,
                filter=f'doc_id == "{doc_id}"',
                output_fields=["vector"],
            )

            if not target_result:
                logger.warning(f"문서를 찾을 수 없음: {doc_id}")
                return []

            target_embedding = np.array(target_result[0]["vector"])

            search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}

            results = self.milvus_client.search(
                collection_name=self.collection_name,
                data=[target_embedding.tolist()],
                anns_field="vector",
                search_params=search_params,
                limit=top_k + 1,
                output_fields=["doc_id", "doc_type"],
            )

            recommendations = []
            for hit in results[0]:
                hit_doc_id = hit.get("doc_id")
                score = hit.get("distance", 0)

                if hit_doc_id != doc_id and score >= threshold:
                    recommendations.append(
                        {
                            "doc_id": hit_doc_id,
                            "doc_type": hit.get("doc_type", "API"),
                            "similarity_score": float(score),
                            "rank": len(recommendations) + 1,
                        }
                    )

                    if len(recommendations) >= top_k:
                        break

            logger.info(
                f"실시간 추천 완료: {doc_id} -> {len(recommendations)}개"
            )
            return recommendations

        except Exception as e:
            logger.error(f"실시간 추천 실패: {e}")
            return []

    async def store_recommendations(
        self,
        doc_id: str,
        target_doc_type: str,
        recommendations: list[dict[str, Any]],
        ttl_days: int = 7,
    ):
        """추천 결과를 MongoDB에 저장"""
        try:
            recommendation_items = []
            for i, rec in enumerate(recommendations):
                item = RecommendationItem(
                    doc_id=rec["doc_id"],
                    doc_type=rec.get("doc_type", "API"),
                    similarity_score=rec["similarity_score"],
                    rank=rec.get("rank", i + 1),
                )
                recommendation_items.append(item)

            existing_rec = await DocRecommendation.find_one(
                DocRecommendation.target_doc_id == doc_id
            )

            now = datetime.utcnow()
            expires_at = now + timedelta(days=ttl_days)

            if existing_rec:
                existing_rec.recommendations = recommendation_items
                existing_rec.updated_at = now
                existing_rec.expires_at = expires_at
                existing_rec.version += 1
                await existing_rec.save()
                logger.info(f"추천 결과 업데이트 완료: {doc_id}")
            else:
                new_rec = DocRecommendation(
                    target_doc_id=doc_id,
                    target_doc_type=target_doc_type,
                    recommendations=recommendation_items,
                    created_at=now,
                    updated_at=now,
                    expires_at=expires_at,
                    version=1,
                )
                await new_rec.save()
                logger.info(
                    f"추천 결과 저장 완료: {doc_id} -> {len(recommendations)}개"
                )

        except Exception as e:
            logger.error(f"추천 결과 저장 실패: {e}")

    async def get_recommendations(
        self,
        doc_id: str,
        target_doc_type: str = "API",
        top_k: int = 4,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """통합 추천 조회"""
        try:
            if use_cache:
                cached_recommendations = (
                    await self.get_recommendations_from_cache(doc_id, top_k)
                )
                if cached_recommendations:
                    return cached_recommendations

            realtime_recommendations = self.get_recommendations_realtime(
                doc_id, top_k
            )
            if realtime_recommendations:
                await self.store_recommendations(
                    doc_id, target_doc_type, realtime_recommendations
                )

            return realtime_recommendations

        except Exception as e:
            logger.error(f"추천 조회 실패: {e}")
            return []

    async def batch_generate_recommendations(
        self, doc_ids: list[str], target_doc_type: str = "API", top_k: int = 4
    ):
        """배치로 추천 생성 및 저장"""
        logger.info(f"배치 추천 생성 시작: {len(doc_ids)}개 문서")

        success_count = 0
        for doc_id in doc_ids:
            try:
                recommendations = self.get_recommendations_realtime(
                    doc_id, top_k
                )
                if recommendations:
                    await self.store_recommendations(
                        doc_id, target_doc_type, recommendations
                    )
                    success_count += 1

            except Exception as e:
                logger.error(f"문서 {doc_id} 추천 생성 실패: {e}")

        logger.info(
            f"배치 추천 생성 완료: {success_count}/{len(doc_ids)}개 성공"
        )
        return success_count
