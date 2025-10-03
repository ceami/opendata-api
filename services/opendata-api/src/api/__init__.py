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
from .v1.routers.search_titles import search_titles_router
from .v1.routers.search_titles_docs import search_titles_docs_router
from .v1.routers.document_list import list_router
from .v1.routers.document_docs import docs_router
from .v1.routers.document_stats import stats_router
from .v1.routers.document_admin import admin_router
from .v1.routers.comments import comments_router
from .v1.routers.recommendation import router as recommendation_router

__all__ = [
    "list_router",
    "docs_router",
    "stats_router",
    "admin_router",
    "search_titles_router",
    "search_titles_docs_router",
    "comments_router",
    "recommendation_router",
]
