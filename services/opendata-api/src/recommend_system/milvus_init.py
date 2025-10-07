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
from pymilvus import DataType, MilvusClient
from pymongo import MongoClient
from sentence_transformers import SentenceTransformer

from core.settings import get_settings


def init_milvus_collection(col_name: str, dim: int) -> MilvusClient:
    """Milvus 컬렉션을 초기화하고 인덱스를 생성"""
    try:
        client = MilvusClient(uri=get_settings().MILVUS_URL)
        print("Milvus 연결 완료")

        if client.has_collection(collection_name=col_name):
            print(f"기존 컬렉션 '{col_name}' 삭제 중...")
            client.drop_collection(collection_name=col_name)

        schema = client.create_schema(
            auto_id=False,
            enable_dynamic_field=True,
            description="문서 임베딩 컬렉션",
        )
        schema.add_field(
            field_name="doc_id",
            datatype=DataType.VARCHAR,
            is_primary=True,
            max_length=64,
        )
        schema.add_field(
            field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=dim
        )

        client.create_collection(collection_name=col_name, schema=schema)
        print(f"컬렉션 '{col_name}' 생성 완료")

        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="IVF_FLAT",
            metric_type="COSINE",
            params={"nlist": 128},
        )

        client.create_index(
            collection_name=col_name,
            index_params=index_params,
        )
        client.load_collection(collection_name=col_name)
        print("컬렉션 로드 완료")
        return client

    except Exception as e:
        print(f"Milvus 컬렉션 초기화 실패: {e}")
        raise


def insert_vectors_milvus(
    client: MilvusClient,
    collection_name: str,
    doc_ids: list[str],
    embeddings: np.ndarray,
    batch_size: int = 50,
) -> Any:
    """문서 ID와 임베딩 벡터를 Milvus에 배치로 삽입"""
    try:
        total_inserted = 0

        for i in range(0, len(doc_ids), batch_size):
            batch_ids = doc_ids[i:i + batch_size]
            batch_embeddings = embeddings[i:i + batch_size]

            data = [
                {"doc_id": doc_id, "vector": vec.tolist()}
                for doc_id, vec in zip(batch_ids, batch_embeddings)
            ]

            client.insert(collection_name=collection_name, data=data)
            total_inserted += len(data)
            print(f"배치 삽입 완료: {len(data)}개 (총 {total_inserted}개)")

        client.flush(collection_name=collection_name)
        print(f"모든 데이터 삽입 완료! 총 {total_inserted}개 문서")
        return total_inserted

    except Exception as e:
        print(f"벡터 삽입 실패: {e}")
        raise


def create_embedding_text(doc: dict) -> str:
    """문서의 핵심 필드를 결합하여 임베딩용 텍스트를 생성"""

    title = doc.get("list_title", "")
    desc = doc.get("desc", "")
    keywords = " ".join(doc.get("keywords", []))
    org_nm = doc.get("org_nm", "")
    category_nm = doc.get("new_category_nm", "")

    embedding_text = f"{title}. {desc}. 핵심키워드: {keywords}. 기관: {org_nm}. 카테고리: {category_nm}"

    return embedding_text


def emb_texts(model: SentenceTransformer, texts: list[str]) -> np.ndarray:
    """SentenceTransformer를 사용하여 텍스트 리스트를 임베딩 벡터로 변환"""
    try:
        res = model.encode(
            texts, convert_to_numpy=True, show_progress_bar=True, batch_size=32
        )
        return res
    except Exception as e:
        print(f"임베딩 생성 실패: {e}")
        raise


def get_data():
    settings = get_settings()
    client = MongoClient(settings.MONGO_URL)

    db = client["open_data"]
    api_data = list(db["open_api_info"].find({}, {"_id": 0}))
    file_data = list(db["open_file_info"].find({}, {"_id": 0}))
    processed_data = []

    for src, dtype in [(api_data, "API"), (file_data, "FILE")]:
        for item in src:
            processed_data.append({
                "_id": str(item.get("list_id", "")),
                "list_title": item.get("list_title", ""),
                "desc": item.get("desc", ""),
                "keywords": item.get("keywords", []),
                "doc_type": dtype,
            })

    print(
        f"총 {len(processed_data)}개 문서 로드 완료 "
        f"(API: {len(api_data)}, File: {len(file_data)})"
    )
    return processed_data


if __name__ == "__main__":
    sample_data: list[dict] = [
        {
            "_id": "doc_tour_01",
            "list_title": "한국문화관광연구원_관광실태조사서비스",
            "desc": "관광실태 정보를 조회하기 위한 서비스로서 국민여행조사, 외래관광객조사, 관광사업체조사의 주요지수를 조회할 수 있다.",
            "keywords": ["조사통계", "국민여행조사", "외래관광객조사"],
        },
        {
            "_id": "doc_traffic_02",
            "list_title": "도로교통공단_교통사고분석시스템",
            "desc": "전국 교통사고 발생 건수, 사상자 수 등 통계 정보를 제공합니다. 교통 안전 정책 수립에 활용됩니다.",
            "keywords": ["교통사고", "도로안전", "교통통계"],
        },
        {
            "_id": "doc_culture_03",
            "list_title": "문화체육관광부_지역축제 개최 현황 및 통계",
            "desc": "지역별 축제 목록과 방문객 수, 기간 등의 통계 정보를 제공합니다. 관광 산업 분석에 유용합니다.",
            "keywords": ["지역축제", "문화행사", "통계조사", "관광"],
        },
        {
            "_id": "doc_tour_04",
            "list_title": "국민 여가 활동 및 여행 트렌드 데이터",
            "desc": "국민들의 주말 여가 활동 패턴, 여행 형태 변화 등 최신 트렌드를 담고 있습니다. 문화, 관광 분야 연구에 활용됩니다.",
            "keywords": ["여행트렌드", "여가활동", "국민조사"],
        },
    ]
    data = get_data()

    try:
        MODEL_NAME = "snunlp/KR-SBERT-V40K-klueNLI-augSTS"
        print(f"모델 로드 중: {MODEL_NAME}")
        model = SentenceTransformer(MODEL_NAME)
        print("모델 로드 완료")

        embedding_texts = [create_embedding_text(doc) for doc in data]
        print(f"{len(embedding_texts)}개 임베딩 텍스트 생성 완료")

        embeddings = emb_texts(model, embedding_texts)

        print("Milvus 컬렉션 초기화 중...")
        client = init_milvus_collection(
            "recommendation_db", embeddings.shape[1]
        )

        print("임베딩 삽입 중...")
        insert_vectors_milvus(
            client,
            "recommendation_db",
            [d["_id"] for d in data],
            embeddings,
            batch_size=50
        )

        print("모든 과정 완료!")

    except Exception as e:
        print(f"오류 발생: {e}")
        import traceback

        traceback.print_exc()
