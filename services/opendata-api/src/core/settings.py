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
import os
from functools import lru_cache
from typing import Type

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pydantic_settings.sources import PyprojectTomlConfigSettingsSource


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        toml_file="pyproject.toml",
        pyproject_toml_table_header=("project",),
        extra="ignore",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            PyprojectTomlConfigSettingsSource(settings_cls),
            env_settings,
            dotenv_settings,
        )

    env: str = Field(default="development", alias="ENV")
    debug: bool = Field(default=False)

    host: str = Field(default="0.0.0.0", alias="host")
    port: int = Field(default=8000, alias="port")

    log_level: str = Field(default="INFO", alias="log_level")

    title: str = Field(default="ODM API", alias="title")
    description: str = Field(
        default="ODM API 서비스를 위한 REST API", alias="description"
    )
    version: str = Field(default="0.0.1", alias="version")
    root_path: str = Field(default="", alias="root_path")

    cors_origins: list[str] = Field(default_factory=list)
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = Field(default_factory=lambda: ["*"])
    cors_allow_headers: list[str] = Field(default_factory=lambda: ["*"])

    enable_docs: bool = Field(default=True)
    enable_redoc: bool = Field(default=True)

    request_id_header: str = "X-Custom-Request-ID"
    trace_id_key: str = "trace_id"
    enable_request_logging: bool = True
    request_timeout: int = 60

    MONGO_URL: str = Field(
        default="mongodb://localhost:27017", alias="MONGO_URL"
    )
    MONGO_DB: str = Field(default="open_data", alias="MONGO_DB")

    ELASTICSEARCH_URL: str = Field(
        default="http://localhost:9200", alias="ELASTICSEARCH_URL"
    )
    ELASTICSEARCH_INDEX_NAME: str = Field(
        default="open_data_titles", alias="ELASTICSEARCH_INDEX"
    )

    MILVUS_URL: str = Field(default="http://milvus:19530", alias="MILVUS_URL")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._setup_environment_specific_settings()

    def _setup_environment_specific_settings(self):
        if self.env == "development":
            self.debug = True
            self.log_level = "DEBUG"
            self.cors_origins = ["*"]
            self.enable_docs = True
            self.enable_redoc = True

        elif self.env == "production":
            self.debug = False
            self.log_level = "INFO"
            self.cors_origins = self._get_production_cors_origins()
            self.enable_docs = False
            self.enable_redoc = False

        elif self.env == "testing":
            self.debug = True
            self.log_level = "DEBUG"
            self.cors_origins = ["*"]
            self.enable_docs = False
            self.enable_redoc = False

    def _get_production_cors_origins(self) -> list[str]:
        cors_origins_env = self.cors_origins
        if cors_origins_env:
            return [origin.strip() for origin in cors_origins_env]

        return ["*"]

    @property
    def docs_url(self) -> str | None:
        return "/docs" if self.enable_docs else None

    @property
    def redoc_url(self) -> str | None:
        return "/redoc" if self.enable_redoc else None

    @property
    def is_local(self) -> bool:
        return self.env == "local"

    @property
    def is_development(self) -> bool:
        return self.env == "development"

    @property
    def is_production(self) -> bool:
        return self.env == "production"


_settings_instance: Settings | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


def reset_settings() -> None:
    global _settings_instance
    _settings_instance = None
    get_settings.cache_clear()


def get_development_settings() -> Settings:
    os.environ["ENV"] = "development"
    return get_settings()


def get_production_settings() -> Settings:
    os.environ["ENV"] = "production"
    return get_settings()


def get_test_settings() -> Settings:
    os.environ["ENV"] = "test"
    return get_settings()
