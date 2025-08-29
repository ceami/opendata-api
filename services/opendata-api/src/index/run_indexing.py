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
