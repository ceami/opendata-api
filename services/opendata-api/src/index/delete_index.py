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
