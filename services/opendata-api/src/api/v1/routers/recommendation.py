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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.dependencies import get_recommendation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recommendation", tags=["recommendation"])


class RecommendationItem(BaseModel):
    """추천 아이템 모델"""

    doc_id: str = Field(..., description="문서 ID")
    similarity_score: float = Field(..., description="유사도 점수")
    rank: int = Field(..., description="추천 순위")


class RecommendationResponse(BaseModel):
    """추천 응답 모델"""

    target_doc_id: str = Field(..., description="추천 기준 문서 ID")
    recommendations: list[RecommendationItem] = Field(
        ..., description="추천 문서 리스트"
    )
    total_count: int = Field(..., description="추천 문서 수")
    source: str = Field(..., description="추천 소스 (cache/realtime)")
    cached: bool = Field(..., description="캐시 사용 여부")


class RecommendationStatsResponse(BaseModel):
    """추천 통계 응답 모델"""

    total_cached_docs: int = Field(..., description="캐시된 문서 수")
    recent_recommendations: int = Field(..., description="최근 24시간 추천 수")
    avg_recommendations_per_doc: float = Field(
        ..., description="문서당 평균 추천 수"
    )
    cache_hit_ratio: str = Field(..., description="캐시 적중률")


@router.get("/{doc_id}", response_model=RecommendationResponse)
async def get_recommendations(
    doc_id: str,
    top_k: int = Query(4, ge=1, le=20, description="추천할 문서 수"),
    use_cache: bool = Query(True, description="캐시 사용 여부"),
    target_doc_type: str = Query(
        "API", description="대상 문서 타입 (API/FILE)"
    ),
    service=Depends(get_recommendation_service),
):
    """문서 추천 조회"""
    try:
        logger.info(
            f"추천 요청: doc_id={doc_id}, top_k={top_k}, use_cache={use_cache}"
        )
        recommendations = await service.get_recommendations(
            doc_id, target_doc_type, top_k, use_cache
        )
        cached_recommendations = service.get_recommendations_from_cache(
            doc_id, top_k
        )
        is_cached = (
            cached_recommendations is not None
            and len(cached_recommendations) > 0
        )
        recommendation_items = [
            RecommendationItem(
                doc_id=rec["doc_id"],
                similarity_score=rec["similarity_score"],
                rank=rec.get("rank", idx + 1),
            )
            for idx, rec in enumerate(recommendations)
        ]

        return RecommendationResponse(
            target_doc_id=doc_id,
            recommendations=recommendation_items,
            total_count=len(recommendation_items),
            source="cache" if is_cached else "realtime",
            cached=is_cached,
        )
    except Exception as e:
        logger.error(f"추천 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=f"추천 조회 실패: {str(e)}")


@router.get("/realtime/{doc_id}", response_model=RecommendationResponse)
async def get_recommendations_realtime(
    doc_id: str,
    top_k: int = Query(4, ge=1, le=20, description="추천할 문서 수"),
    threshold: float = Query(0.5, ge=0.0, le=1.0, description="유사도 임계값"),
    service=Depends(get_recommendation_service),
):
    """실시간 문서 추천 조회"""
    try:
        logger.info(
            f"실시간 추천 요청: doc_id={doc_id}, top_k={top_k}, threshold={threshold}"
        )
        recommendations = service.get_recommendations_realtime(
            doc_id, top_k, threshold
        )
        recommendation_items = [
            RecommendationItem(
                doc_id=rec["doc_id"],
                similarity_score=rec["similarity_score"],
                rank=rec.get("rank", idx + 1),
            )
            for idx, rec in enumerate(recommendations)
        ]

        return RecommendationResponse(
            target_doc_id=doc_id,
            recommendations=recommendation_items,
            total_count=len(recommendation_items),
            source="realtime",
            cached=False,
        )
    except Exception as e:
        logger.error(f"실시간 추천 조회 실패: {e}")
        raise HTTPException(
            status_code=500, detail=f"실시간 추천 조회 실패: {str(e)}"
        )


@router.get("/cache/{doc_id}", response_model=RecommendationResponse)
async def get_recommendations_from_cache(
    doc_id: str,
    top_k: int = Query(4, ge=1, le=20, description="추천할 문서 수"),
    service=Depends(get_recommendation_service),
):
    """캐시에서 문서 추천 조회"""
    try:
        logger.info(f"캐시 추천 요청: doc_id={doc_id}, top_k={top_k}")
        recommendations = service.get_recommendations_from_cache(doc_id, top_k)
        if not recommendations:
            return RecommendationResponse(
                target_doc_id=doc_id,
                recommendations=[],
                total_count=0,
                source="cache",
                cached=False,
            )
        recommendation_items = [
            RecommendationItem(
                doc_id=rec["doc_id"],
                similarity_score=rec["similarity_score"],
                rank=rec.get("rank", idx + 1),
            )
            for idx, rec in enumerate(recommendations)
        ]

        return RecommendationResponse(
            target_doc_id=doc_id,
            recommendations=recommendation_items,
            total_count=len(recommendation_items),
            source="cache",
            cached=True,
        )
    except Exception as e:
        logger.error(f"캐시 추천 조회 실패: {e}")
        raise HTTPException(
            status_code=500, detail=f"캐시 추천 조회 실패: {str(e)}"
        )


@router.post("/batch/generate")
async def batch_generate_recommendations(
    doc_ids: list[str],
    top_k: int = Query(4, ge=1, le=20, description="추천할 문서 수"),
    target_doc_type: str = Query(
        "API", description="대상 문서 타입 (API/FILE)"
    ),
    service=Depends(get_recommendation_service),
):
    """배치 추천 생성"""
    try:
        logger.info(
            f"배치 추천 생성 요청: {len(doc_ids)}개 문서, top_k={top_k}"
        )
        if len(doc_ids) > 100:
            raise HTTPException(
                status_code=400,
                detail="한 번에 최대 100개 문서까지 처리 가능합니다",
            )
        success_count = await service.batch_generate_recommendations(
            doc_ids, target_doc_type, top_k
        )

        return {
            "message": "배치 추천 생성 완료",
            "total_requested": len(doc_ids),
            "success_count": success_count,
            "failed_count": len(doc_ids) - success_count,
        }
    except Exception as e:
        logger.error(f"배치 추천 생성 실패: {e}")
        raise HTTPException(
            status_code=500, detail=f"배치 추천 생성 실패: {str(e)}"
        )


@router.get("/stats", response_model=RecommendationStatsResponse)
async def get_recommendation_stats(service=Depends(get_recommendation_service)):
    """추천 시스템 통계 조회"""
    try:
        logger.info("추천 통계 조회 요청")

        stats = service.get_recommendation_stats()

        return RecommendationStatsResponse(
            total_cached_docs=stats.get("total_cached_docs", 0),
            recent_recommendations=stats.get("recent_recommendations", 0),
            avg_recommendations_per_doc=stats.get(
                "avg_recommendations_per_doc", 0.0
            ),
            cache_hit_ratio=stats.get("cache_hit_ratio", "N/A"),
        )
    except Exception as e:
        logger.error(f"추천 통계 조회 실패: {e}")
        raise HTTPException(
            status_code=500, detail=f"추천 통계 조회 실패: {str(e)}"
        )


@router.delete("/cache/{doc_id}")
async def clear_recommendation_cache(
    doc_id: str, service=Depends(get_recommendation_service)
):
    """
    특정 문서의 추천 캐시 삭제

    - **doc_id**: 캐시를 삭제할 문서 ID
    """
    try:
        logger.info(f"캐시 삭제 요청: doc_id={doc_id}")
        result = service.recommend_collection.delete_one(
            {"target_doc_id": doc_id}
        )

        if result.deleted_count > 0:
            return {"message": f"문서 '{doc_id}'의 추천 캐시가 삭제되었습니다"}
        else:
            return {
                "message": f"문서 '{doc_id}'의 추천 캐시를 찾을 수 없습니다"
            }

    except Exception as e:
        logger.error(f"캐시 삭제 실패: {e}")
        raise HTTPException(status_code=500, detail=f"캐시 삭제 실패: {str(e)}")


@router.delete("/cache")
async def clear_all_recommendation_cache(
    service=Depends(get_recommendation_service),
):
    """모든 추천 캐시 삭제"""
    try:
        logger.info("전체 캐시 삭제 요청")
        result = service.recommend_collection.delete_many({})

        return {
            "message": "모든 추천 캐시가 삭제되었습니다",
            "deleted_count": result.deleted_count,
        }
    except Exception as e:
        logger.error(f"전체 캐시 삭제 실패: {e}")
        raise HTTPException(
            status_code=500, detail=f"전체 캐시 삭제 실패: {str(e)}"
        )
