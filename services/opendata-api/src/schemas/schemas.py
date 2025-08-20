from pydantic import BaseModel, Field
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
