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

from beanie.operators import Eq, In
from models import GeneratedAPIDocs, GeneratedFileDocs, OpenAPIInfo, OpenFileInfo, SavedRequest
from utils.datetime_util import now_kst
from api.v1.application.open_data.dto import SuccessRateDTO


class DocumentsAppService:
    async def get_generated_documents(
        self,
        *,
        list_ids: list[int] | None,
        page: int,
        page_size: int,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        if list_ids:
            api_docs = (
                await GeneratedAPIDocs.find(In(GeneratedAPIDocs.list_id, list_ids))
                .skip((page - 1) * page_size)
                .limit(page_size)
                .to_list()
            )
        else:
            api_docs = (
                await GeneratedAPIDocs.find()
                .skip((page - 1) * page_size)
                .limit(page_size)
                .to_list()
            )

        for doc in api_docs:
            results.append({"data_type": "API", **doc.model_dump()})

        if list_ids:
            file_docs = (
                await GeneratedFileDocs.find(In(GeneratedFileDocs.list_id, list_ids))
                .skip((page - 1) * page_size)
                .limit(page_size)
                .to_list()
            )
        else:
            file_docs = (
                await GeneratedFileDocs.find()
                .skip((page - 1) * page_size)
                .limit(page_size)
                .to_list()
            )

        for doc in file_docs:
            results.append({"data_type": "FILE", **doc.model_dump()})

        return results

    async def get_std_doc_detail(self, *, list_id: int) -> dict[str, Any]:
        api_document = await GeneratedAPIDocs.find_one(Eq(GeneratedAPIDocs.list_id, list_id))
        if api_document:
            open_api_info = await OpenAPIInfo.find_one(Eq(OpenAPIInfo.list_id, list_id))
            return {
                "list_id": api_document.list_id,
                "data_type": "API",
                "list_title": open_api_info.list_title if open_api_info else None,
                "detail_url": f"https://www.data.go.kr/data/{list_id}/openapi.do",
                "generated_status": True,
                "created_at": getattr(open_api_info, "created_at", None),
                "updated_at": getattr(open_api_info, "updated_at", None),
                "description": (open_api_info.desc.replace("<br/>", "\n") if (open_api_info and getattr(open_api_info, "desc", None)) else None),
                "org_nm": getattr(open_api_info, "org_nm", None),
                "dept_nm": getattr(open_api_info, "dept_nm", None),
                "is_charged": getattr(open_api_info, "is_charged", None),
                "share_scope_nm": getattr(open_api_info, "share_scope_nm", None),
                "keywords": getattr(open_api_info, "keywords", []) if open_api_info else [],
                "token_count": api_document.token_count,
                "generated_at": getattr(api_document, "generated_at", None),
                "markdown": api_document.markdown,
            }

        file_document = await GeneratedFileDocs.find_one(Eq(GeneratedFileDocs.list_id, list_id))
        if file_document:
            open_file_info = await OpenFileInfo.find_one(Eq(OpenFileInfo.list_id, list_id))
            return {
                "list_id": file_document.list_id,
                "data_type": "FILE",
                "list_title": getattr(open_file_info, "list_title", None) or getattr(open_file_info, "title", None),
                "detail_url": f"https://www.data.go.kr/data/{list_id}/fileData.do",
                "generated_status": file_document is not None,
                "created_at": getattr(open_file_info, "created_at", None),
                "updated_at": getattr(open_file_info, "updated_at", None),
                "description": (open_file_info.desc.replace("<br/>", "\n") if (open_file_info and getattr(open_file_info, "desc", None)) else None),
                "org_nm": getattr(open_file_info, "org_nm", None),
                "dept_nm": getattr(open_file_info, "dept_nm", None),
                "is_charged": getattr(open_file_info, "is_charged", None),
                "share_scope_nm": getattr(open_file_info, "share_scope_nm", None),
                "keywords": getattr(open_file_info, "keywords", []) if open_file_info else [],
                "token_count": getattr(file_document, "token_count", 0),
                "generated_at": getattr(file_document, "generated_at", None),
                "markdown": getattr(file_document, "markdown", None),
            }

        open_api_info = await OpenAPIInfo.find_one(Eq(OpenAPIInfo.list_id, list_id))
        if open_api_info:
            return {
                "list_id": open_api_info.list_id,
                "data_type": "API",
                "list_title": open_api_info.list_title,
                "detail_url": f"https://www.data.go.kr/data/{list_id}/openapi.do",
                "generated_status": False,
                "created_at": open_api_info.created_at,
                "updated_at": open_api_info.updated_at,
                "description": (open_api_info.desc.replace("<br/>", "\n") if getattr(open_api_info, "desc", None) else None),
                "org_nm": open_api_info.org_nm,
                "dept_nm": open_api_info.dept_nm,
                "is_charged": open_api_info.is_charged,
                "share_scope_nm": open_api_info.share_scope_nm,
                "keywords": open_api_info.keywords,
                "token_count": 0,
                "generated_at": None,
                "markdown": None,
            }

        open_file_info = await OpenFileInfo.find_one(Eq(OpenFileInfo.list_id, list_id))
        if open_file_info:
            return {
                "list_id": open_file_info.list_id,
                "data_type": "FILE",
                "list_title": getattr(open_file_info, "list_title", None) or getattr(open_file_info, "title", None),
                "detail_url": f"https://www.data.go.kr/data/{list_id}/fileData.do",
                "generated_status": False,
                "created_at": open_file_info.created_at,
                "updated_at": open_file_info.updated_at,
                "description": (open_file_info.desc.replace("<br/>", "\n") if getattr(open_file_info, "desc", None) else None),
                "org_nm": open_file_info.org_nm,
                "dept_nm": open_file_info.dept_nm,
                "is_charged": open_file_info.is_charged,
                "share_scope_nm": open_file_info.share_scope_nm,
                "keywords": open_file_info.keywords if open_file_info else [],
                "token_count": 0,
                "generated_at": None,
                "markdown": None,
            }

        raise ValueError(f"list_id {list_id}에 해당하는 데이터를 찾을 수 없습니다")

    async def save_request(
        self, *, list_id: int | None, url: str | None
    ) -> dict[str, str]:
        """요청 저장"""
        if not list_id and not url:
            raise ValueError("list_id나 url 중 하나는 필수입니다.")

        saved = SavedRequest(list_id=list_id, url=url, created_at=now_kst())
        await saved.insert()
        return {"message": "저장완료", "id": str(saved.id)}

    async def get_success_rate(self) -> SuccessRateDTO:
        """문서 생성 성공률 조회"""
        total_open_data = await OpenAPIInfo.count()
        total_std_docs = await GeneratedAPIDocs.count()
        success_rate = (total_std_docs / total_open_data * 100) if total_open_data > 0 else 0
        return SuccessRateDTO(
            total_open_data=total_open_data,
            total_std_docs=total_std_docs,
            success_rate=round(success_rate, 2),
        )
