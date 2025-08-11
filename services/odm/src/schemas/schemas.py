from pydantic import BaseModel, Field
from typing import Literal


class ParameterInfo(BaseModel):
    name: str
    description: str
    type: str | None = Field(default="string")
    required: bool | None = Field(default=None)
    in_: Literal["query", "header", "body"]


class RequestSchema(BaseModel):
    headers: dict[str, ParameterInfo]
    query_params: dict[str, ParameterInfo]
    request_body: dict[str, ParameterInfo]


class ResponseSchema(BaseModel):
    code: str
    data_schema: dict | None = Field(default=None)
    description: str


class ParsedEndpoint(BaseModel):
    id: str
    path: str
    method: str
    request_schema: RequestSchema
    response_schemas: dict[str, ResponseSchema]
    example_response_data: str | None = Field(default=None)
    example_request_string: str | None = Field(default=None)
