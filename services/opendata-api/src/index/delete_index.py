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

from elasticsearch import Elasticsearch

from core.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def delete_elasticsearch_index():
    settings = get_settings()
    es = Elasticsearch([settings.ELASTICSEARCH_URL])
    index_name = settings.ELASTICSEARCH_INDEX_NAME

    try:
        if es.indices.exists(index=index_name):
            es.indices.delete(index=index_name)
            logger.info(f"인덱스 '{index_name}'이 성공적으로 삭제되었습니다.")
        else:
            logger.info(f"인덱스 '{index_name}'이 존재하지 않습니다.")
    except Exception as e:
        logger.error(f"인덱스 삭제 중 오류 발생: {e}")
        raise


if __name__ == "__main__":
    delete_elasticsearch_index()
