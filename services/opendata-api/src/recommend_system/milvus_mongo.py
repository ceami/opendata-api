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
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from pymilvus import MilvusClient

from core.settings import get_settings
from db.mongo import MongoDB
from models import DocRecommendation
from models.open_data import RecommendationItem


def recommend_similar_documents(
    client: MilvusClient,
    collection_name: str,
    target_embedding: np.ndarray,
    target_doc_id: str,
    top_k: int = 4,
    threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Milvus를 사용하여 유사한 문서를 추천"""
    try:
        search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}

        results = client.search(
            collection_name=collection_name,
            data=[target_embedding.tolist()],
            anns_field="vector",
            search_params=search_params,
            limit=top_k + 1,
            output_fields=["doc_id", "doc_type"],
        )

        recommendations = []
        print(f"\n--- 추천 기준 문서: {target_doc_id} ---")

        for hit in results[0]:
            doc_id = hit.get("doc_id")
            score = hit.get("distance", 0)

            if doc_id != target_doc_id and score >= threshold:
                recommendations.append(
                    {
                        "doc_id": doc_id,
                        "doc_type": hit.get("doc_type", "API"),
                        "similarity_score": float(score),
                    }
                )

                if len(recommendations) >= top_k:
                    break

        print(f"{len(recommendations)}개 문서 추천 완료")
        return recommendations

    except Exception as e:
        print(f"문서 추천 실패: {e}")
        return []


async def store_recommendations_in_mongo(
    target_doc_id: str,
    target_doc_type: str,
    recommendations: list[dict[str, Any]],
    ttl_days: int = 7,
) -> bool:
    """추천 결과를 MongoDB에 저장"""
    try:
        recommendation_items = []
        for i, rec in enumerate(recommendations):
            item = RecommendationItem(
                doc_id=rec["doc_id"],
                doc_type=rec.get("doc_type", "API"),
                similarity_score=rec["similarity_score"],
                rank=i + 1,
            )
            recommendation_items.append(item)

        existing_rec = await DocRecommendation.find_one(
            DocRecommendation.target_doc_id == target_doc_id
        )

        now = datetime.utcnow()
        expires_at = now + timedelta(days=ttl_days)

        if existing_rec:
            existing_rec.recommendations = recommendation_items
            existing_rec.updated_at = now
            existing_rec.expires_at = expires_at
            existing_rec.version += 1
            await existing_rec.save()
            print(f"추천 결과 업데이트 완료: {target_doc_id}")
        else:
            new_rec = DocRecommendation(
                target_doc_id=target_doc_id,
                target_doc_type=target_doc_type,
                recommendations=recommendation_items,
                created_at=now,
                updated_at=now,
                expires_at=expires_at,
                version=1,
            )
            await new_rec.save()
            print(f"추천 결과 저장 완료: {target_doc_id}")

        return True

    except Exception as e:
        print(f"MongoDB 저장 실패: {e}")
        return False


async def recommend_and_store_in_mongo(
    client: MilvusClient,
    milvus_collection_name: str,
    target_embedding: np.ndarray,
    target_doc_id: str,
    target_doc_type: str = "API",
    top_k: int = 4,
    threshold: float = 0.6,
    ttl_days: int = 7,
) -> list[dict[str, Any]]:
    """문서 추천을 수행하고 결과를 MongoDB에 저장"""
    recommendations = recommend_similar_documents(
        client,
        milvus_collection_name,
        target_embedding,
        target_doc_id,
        top_k,
        threshold,
    )

    if recommendations:
        await store_recommendations_in_mongo(
            target_doc_id, target_doc_type, recommendations, ttl_days
        )

    return recommendations


async def get_stored_recommendations(
    target_doc_id: str, top_k: int = 4
) -> list[dict[str, Any]] | None:
    """MongoDB에서 저장된 추천 결과를 조회"""
    try:
        now = datetime.utcnow()
        result = await DocRecommendation.find_one(
            DocRecommendation.target_doc_id == target_doc_id,
            DocRecommendation.expires_at > now,
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

            print(
                f"저장된 추천 결과 조회 완료: {target_doc_id} ({len(recommendations)}개)"
            )
            return recommendations
        else:
            print(f"저장된 추천 결과 없음 또는 만료됨: {target_doc_id}")
            return None

    except Exception as e:
        print(f"추천 결과 조회 실패: {e}")
        return None


async def main():
    """테스트용 메인 함수"""
    settings = get_settings()
    await MongoDB.init(settings.MONGO_URL, settings.MONGO_DB)

    client = MilvusClient(uri=get_settings().MILVUS_URL)
    collection_name = "recommendation_db"

    target_doc_id = "15000017"
    target_doc_type = "API"

    try:
        result = client.query(
            collection_name=collection_name,
            filter=f'doc_id == "{target_doc_id}"',
            output_fields=["vector"],
        )

        if result:
            target_embedding = np.array(result[0]["vector"])
            recommendations = recommend_similar_documents(
                client, collection_name, target_embedding, target_doc_id
            )

            if recommendations:
                await store_recommendations_in_mongo(
                    target_doc_id, target_doc_type, recommendations
                )

            stored_recommendations = await get_stored_recommendations(
                target_doc_id
            )
            print("저장된 추천 결과:", stored_recommendations)
        else:
            print(f"문서 '{target_doc_id}'를 찾을 수 없습니다.")

    except Exception as e:
        print(f"오류 발생: {e}")


if __name__ == "__main__":
    asyncio.run(main())
