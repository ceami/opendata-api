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
from .dependencies import (
    ServiceContainer,
    get_cross_collection_service,
    get_elasticsearch_client,
    get_health_status,
    get_mongo_client,
    get_search_service,
    get_service_container,
    get_service_container_with_settings,
    get_settings_dependency,
    lifespan,
)
from .exceptions import create_openapi_http_exception_doc
from .settings import (
    Settings,
    get_development_settings,
    get_production_settings,
    get_settings,
    get_test_settings,
)

__all__ = [
    "Settings",
    "get_settings",
    "get_development_settings",
    "get_production_settings",
    "get_test_settings",
    "ServiceContainer",
    "get_service_container",
    "get_health_status",
    "get_settings_dependency",
    "get_service_container_with_settings",
    "get_elasticsearch_client",
    "get_mongo_client",
    "get_cross_collection_service",
    "get_search_service",
    "lifespan",
    "create_openapi_http_exception_doc",
]
