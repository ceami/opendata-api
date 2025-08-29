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
from pydantic import BaseModel


class HTTPExceptionResponse(BaseModel):
    success: bool = False
    status: str = "error"
    results: dict
    message: str = ""
    trace_id: str | None = None
    timestamp: str


def create_openapi_http_exception_doc(
    responses_status_code: list[int],
) -> dict:
    responses_status_code = sorted(responses_status_code)

    return {
        status_code: {
            "model": HTTPExceptionResponse,
            "description": {
                400: "잘못된 요청 - 입력 데이터가 올바르지 않습니다",
                422: "처리할 수 없는 엔티티 - 요청 데이터 검증 실패",
                500: "내부 서버 오류 - 서버 내부 처리 중 오류 발생",
                502: "Bad Gateway - 외부 서비스 호출 중 오류",
                503: "서비스 사용 불가 - 서비스가 일시적으로 사용할 수 없습니다",
                429: "요청 제한 초과 - 너무 많은 요청이 발생했습니다",
                404: "리소스를 찾을 수 없음 - 요청한 리소스가 존재하지 않습니다",
            }.get(status_code, f"HTTP {status_code} 오류"),
        }
        for status_code in responses_status_code
    }
