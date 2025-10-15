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

import numpy as np
from pymilvus import Collection, MilvusClient


def get_vector_by_doc_id(collection: Collection, doc_id: str) -> dict | None:
    """특정 문서 ID로 벡터와 메타데이터를 조회"""
    try:
        expr = f'doc_id == "{doc_id}"'
        results = collection.query(expr, output_fields=["doc_id", "embedding"])

        if results:
            print(f"문서 '{doc_id}' 조회 완료")
            return results[0]
        else:
            print(f"문서 '{doc_id}'를 찾을 수 없습니다")
            return None

    except Exception as e:
        print(f"문서 조회 실패: {e}")
        raise


def update_vector_by_doc_id(
    collection: Collection, doc_id: str, new_embedding: np.ndarray
) -> bool:
    """특정 문서의 임베딩 벡터를 업데이트"""
    try:
        collection.delete(f'doc_id == "{doc_id}"')
        print(f"문서 '{doc_id}' 기존 데이터 삭제 완료")

        entities = [[doc_id], [new_embedding.tolist()]]
        collection.insert(entities)
        collection.flush()

        print(f"문서 '{doc_id}' 업데이트 완료")
        return True

    except Exception as e:
        print(f"문서 업데이트 실패: {e}")
        return False


def delete_vector_by_doc_id(collection: Collection, doc_id: str) -> bool:
    """특정 문서를 삭제"""
    try:
        existing = get_vector_by_doc_id(collection, doc_id)
        if not existing:
            print(f"삭제할 문서 '{doc_id}'가 존재하지 않습니다")
            return False

        collection.delete(f'doc_id == "{doc_id}"')
        collection.flush()

        print(f"문서 '{doc_id}' 삭제 완료")
        return True

    except Exception as e:
        print(f"문서 삭제 실패: {e}")
        return False


def batch_delete_vectors(collection: Collection, doc_ids: list[str]) -> int:
    """여러 문서를 일괄 삭제"""
    try:
        if not doc_ids:
            print("삭제할 문서 ID가 없습니다")
            return 0

        expr = f"doc_id in {doc_ids}"
        collection.delete(expr)
        collection.flush()

        print(f"{len(doc_ids)}개 문서 일괄 삭제 완료")
        return len(doc_ids)

    except Exception as e:
        print(f"일괄 삭제 실패: {e}")
        return 0


def get_collection_stats(
    collection: Collection, milvus_client: MilvusClient | None = None
) -> dict[str, Any]:
    """컬렉션의 통계 정보를 조회"""
    try:
        if milvus_client:
            detailed_stats = milvus_client.get_collection_stats(
                collection_name=collection.name
            )
            stats = {
                "name": collection.name,
                "description": collection.description,
                "num_entities": collection.num_entities,
                "schema": collection.schema,
                "detailed_stats": detailed_stats,
            }
        else:
            stats = {
                "name": collection.name,
                "description": collection.description,
                "num_entities": collection.num_entities,
                "schema": collection.schema,
            }

        print("컬렉션 통계 조회 완료")
        return stats

    except Exception as e:
        print(f"통계 조회 실패: {e}")
        return {}
