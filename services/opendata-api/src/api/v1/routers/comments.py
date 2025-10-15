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
from typing import Any

from beanie import PydanticObjectId
from beanie.operators import Eq
from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
)

from api.v1.application.open_data.dto import CreateCommentDTO
from core.dependencies import get_logger_service, limiter
from models import Comment
from utils.datetime_util import now_kst

comments_router = APIRouter(prefix="/comments", tags=["comments"])


@comments_router.post(path="", response_model=dict[str, Any])
@limiter.limit("60/minute")
async def create_comment(
    request: Request,
    body: CreateCommentDTO = Body(...),
    logger: logging.Logger = Depends(lambda: get_logger_service("comments")),
):
    try:
        doc = Comment(
            list_id=body.list_id, content=body.content, created_at=now_kst()
        )
        await doc.insert()
        return {"id": str(doc.id)}
    except Exception as e:
        logger.exception(f"[Comments] create 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@comments_router.get(path="/{list_id}", response_model=dict[str, Any])
@limiter.limit("60/minute")
async def list_comments(
    request: Request,
    list_id: int = Path(..., ge=1),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    skip = (page - 1) * size
    docs = (
        await Comment.find(Eq(Comment.list_id, list_id))
        .sort("-created_at")
        .skip(skip)
        .limit(size)
        .to_list()
    )
    total = await Comment.find(Eq(Comment.list_id, list_id)).count()
    items = [
        {
            "id": str(d.id),
            "list_id": d.list_id,
            "content": d.content,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }
        for d in docs
    ]
    return {"items": items, "total": total, "page": page, "size": size}


@comments_router.delete(path="/{comment_id}", response_model=dict)
@limiter.limit("60/minute")
async def delete_comment(request: Request, comment_id: str = Path(...)):
    oid = PydanticObjectId(comment_id)
    deleted = await Comment.find_one(Comment.id == oid)
    if not deleted:
        raise HTTPException(status_code=404, detail="not found")
    await deleted.delete()
    return {"ok": True}
