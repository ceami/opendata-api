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
from datetime import datetime
from typing import Any

import numpy as np
from pymilvus import MilvusClient
from tqdm import tqdm

from core.settings import get_settings
from db.mongo import MongoDB
from models import DocRecommendation, OpenAPIInfo, OpenFileInfo
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
            limit=top_k + 5,
            output_fields=["doc_id", "doc_type"],
        )

        recommendations = []

        for hit in results[0]:
            doc_id = hit.get("doc_id")
            distance = hit.get("distance", 0)
            similarity = float(distance)

            if doc_id != target_doc_id and similarity >= threshold:
                recommendations.append(
                    {
                        "doc_id": doc_id,
                        "doc_type": hit.get("doc_type", "API"),
                        "similarity_score": float(similarity),
                    }
                )

        recommendations = sorted(
            recommendations,
            key=lambda x: x["similarity_score"],
            reverse=True,
        )[:top_k]

        return recommendations

    except Exception as e:
        print(f"문서 추천 실패: {e}")
        return []


async def store_recommendations_in_mongo(
    target_doc_id: str,
    target_doc_type: str,
    recommendations: list[dict[str, Any]],
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

        if existing_rec:
            existing_rec.recommendations = recommendation_items
            existing_rec.updated_at = now
            existing_rec.version += 1
            await existing_rec.save()
        else:
            new_rec = DocRecommendation(
                target_doc_id=target_doc_id,
                target_doc_type=target_doc_type,
                recommendations=recommendation_items,
                created_at=now,
                updated_at=now,
                version=1,
            )
            await new_rec.save()

        return True

    except Exception as e:
        print(f"MongoDB 저장 실패: {e}")
        return False


async def get_all_documents():
    """모든 문서 데이터를 가져오는 함수 (Beanie ODM 사용)"""
    api_docs = await OpenAPIInfo.find({}, projection_model=None).to_list()
    file_docs = await OpenFileInfo.find({}, projection_model=None).to_list()

    processed_data = []

    for doc in file_docs:
        processed_data.append(
            {
                "_id": int(doc.list_id) if doc.list_id else 0,
                "list_title": getattr(doc, "list_title", None)
                or getattr(doc, "title", None)
                or "",
                "desc": doc.desc or "",
                "keywords": doc.keywords
                if isinstance(doc.keywords, list)
                else [],
                "doc_type": "FILE",
            }
        )

    for doc in api_docs:
        processed_data.append(
            {
                "_id": doc.list_id,
                "list_title": doc.list_title or "",
                "desc": doc.desc or "",
                "keywords": doc.keywords
                if isinstance(doc.keywords, list)
                else [],
                "doc_type": "API",
            }
        )

    return processed_data


async def main():
    """모든 문서에 대해 추천 아이템을 생성하고 저장하는 메인 함수"""
    settings = get_settings()
    await MongoDB.init(settings.MONGO_URL, settings.MONGO_DB)

    client = MilvusClient(uri=get_settings().MILVUS_URL)
    collection_name = "recommendation_db"

    all_documents = await get_all_documents()

    successful_count = 0
    failed_count = 0

    print("\n=== 모든 문서에 대한 추천 생성 시작 ===")
    print(f"총 {len(all_documents)}개 문서 처리 예정")

    try:
        for doc in tqdm(all_documents, desc="문서 추천 생성 중"):
            doc_id = doc["_id"]
            doc_type = doc["doc_type"]

            try:
                filter_expr = f'doc_id == "{str(doc_id)}"'
                result = client.query(
                    collection_name=collection_name,
                    filter=filter_expr,
                    output_fields=["vector"],
                )

                if result and len(result) > 0 and result[0]["vector"]:
                    target_embedding = np.array(result[0]["vector"])

                    recommendations = recommend_similar_documents(
                        client, collection_name, target_embedding, str(doc_id)
                    )

                    # 빈 리스트라도 저장하여 "조회 완료했지만 추천 없음" 상태 표시
                    await store_recommendations_in_mongo(
                        str(doc_id), doc_type, recommendations
                    )
                    successful_count += 1

                else:
                    # Milvus에 벡터가 없는 경우에도 빈 추천으로 저장
                    await store_recommendations_in_mongo(
                        str(doc_id), doc_type, []
                    )
                    failed_count += 1

            except Exception:
                failed_count += 1
                continue

        print("\n=== 추천 생성 완료 ===")
        print(f"성공: {successful_count}개")
        print(f"실패: {failed_count}개")
        print(f"총 처리: {successful_count + failed_count}개")

    except Exception as e:
        print(f"전체 프로세스 오류 발생: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
