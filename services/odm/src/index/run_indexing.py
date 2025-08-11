import asyncio
import sys
from index_titles import TitleIndexer


async def main():
    print("OpenDataInfo 데이터를 Elasticsearch에 인덱싱을 시작합니다...")

    try:
        indexer = TitleIndexer()
        await indexer.run_indexing()
        print("인덱싱이 성공적으로 완료되었습니다!")

    except Exception as e:
        print(f"인덱싱 중 오류가 발생했습니다: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
