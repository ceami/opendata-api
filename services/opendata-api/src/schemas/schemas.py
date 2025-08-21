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
# limitations under the License.from pydantic import BaseModel, Field
from typing import Literal


class ParameterInfo(BaseModel):
    name: str
    description: str | None = Field(default=None)
    type: str | None = Field(default="string")
    required: bool | None = Field(default=None)
    in_: Literal["query", "header", "body"] | None = Field(default=None)


class RequestSchema(BaseModel):
    headers: dict[str, ParameterInfo] | None = Field(default=None)
    query_params: dict[str, ParameterInfo] | None = Field(default=None)
    request_body: dict[str, ParameterInfo] | None = Field(default=None)


class ResponseSchema(BaseModel):
    code: str
    data_schema: dict | None = Field(default=None)
    description: str | None = Field(default=None)


class ParsedEndpoint(BaseModel):
    id: str
    path: str
    method: str
    request_schema: RequestSchema | None = Field(default=None)
    response_schemas: dict[str, ResponseSchema] | None = Field(default=None)
    example_response_data: str | None = Field(default=None)
    example_request_string: str | None = Field(default=None)
