# 수집기 검증 기록

검증일: 2026-09-03 UTC. 운영 DB에는 적재하지 않았다. 아래 결과는 구현과 표본 검증이며, 공공데이터포털 전량 적재를 완료했다는 의미가 아니다.

## 자동 검증

Python 3.13.12, `uv.lock`에 고정한 의존성, 별도 MongoDB 8.0.12 컨테이너에서 실행했다.

```bash
uv sync --frozen --group dev
MONGO_TEST_URL=mongodb://127.0.0.1:32768 uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen opendata-collect --help
```

- 단위·기능 테스트 76개와 실제 MongoDB 통합 테스트 3개: **79개 통과**.
- Ruff lint와 format 검사 통과.
- 패키지 설치 및 CLI 진입점 실행 성공.
- 실제 Mongo 통합 테스트는 임의 UUID의 검증 DB를 만들고 종료 시 해당 DB만 삭제한다. `MONGO_TEST_URL`이 없으면 3개 통합 테스트를 건너뛴다.

자동 검증 범위:

| 영역 | 확인한 동작 |
| --- | --- |
| 목록 | FILE/API/STD/LINKED 파싱, 요청 페이지·크기·응답 길이·총건수 검증, 표준 그룹과 구성 건수 구분 |
| 원천 API | 응답 필드 보존, 같은 목록 ID의 복수 operation 보존, 인증 헤더 및 키 없는 실행 오류 |
| 상세 | 한국어 메타데이터, 반복 라벨, 표·컬럼, JSON-LD, Swagger, DCAT, 이력·구성 목록과 상세 팝업 |
| HTTP | 일시 오류 재시도, 인증 오류 처리, 리다이렉트 대상 검증, 키 전파 제한, 응답 크기 제한 |
| 수집 상태 | 제한 실행, 페이지 체크포인트, 실패 항목 재시도, 누락·중복·건수 변동 시 미완료 |
| 최종 검증 | 전체 목록 재조회, 총건수가 같아도 ID 교체가 있으면 완료 거부 |
| 실제 MongoDB | 재개·반복 적재, 기존 문서 ID/AI 상태 보존, 미지정 원천 필드, 복수 operation, writer lease |
| 큰 원본 | 17MiB 상세 JSON의 GridFS 저장·복원, 1MiB 비압축성 원문의 여러 chunk 저장·복원 |
| 기존 API 연결 | FILE/API 요약 필드와 타입, 미상 Y/N 값, STD/LINKED의 별도 저장 |

동일 총건수의 페이지 교체 문제는 독립 검토에서 발견했고, 재현 테스트와 전체 페이지 재검증으로 보완한 후 재검토했다. 원격 포털은 원자적 스냅샷 토큰을 제공하지 않으므로 마지막 검증 이후의 변경까지 보장하지 않는다.

## 실제 포털 표본

발급 키 없이 공개 포털에서 다음을 실행했다. MongoDB 연결 없이 JSONL을 생성한다.

```bash
uv run opendata-collect preview --source portal \
  --types FILE API STD LINKED --page-size 1 --limit 1 \
  --timeout 15 --retries 1 --output /tmp/opendata-live-preview.jsonl
```

결과: 종료코드 0, 유형별 1건, `has_errors=false`. 목록 요청을 제외한 상세·부가 응답은 합계 **284개**, 오류 0개다.

| 표본 | 응답 수 | 확인한 내용 |
| --- | ---: | --- |
| [FILE:3049380](https://www.data.go.kr/data/3049380/fileData.do) | 9 | HTML, schema.org, DCAT, 외부 Swagger, 파일 이력, 과거 버전 상세 4건 |
| [API:15075883](https://www.data.go.kr/data/15075883/openapi.do) | 3 | HTML에 포함된 Swagger 1개, schema.org, DCAT |
| [STD:15028204](https://www.data.go.kr/data/15028204/standard.do) | 269 | HTML/schema.org/DCAT 3개, 추가 구성 목록 44페이지, 구성 데이터 상세 222건 |
| [LINKED:33643](https://www.data.go.kr/data/33643/linkedData.do) | 3 | HTML, schema.org, DCAT, 원본 사이트 링크 |

추가로 실제 API 목록의 100건짜리 2페이지와 STD 내부 파일 ID가 표시 ID와 다른 상세 페이지를 확인했다. 재현용으로 축약한 HTML은 `tests/fixtures`에 두었고, [출처와 변형 내역](tests/fixtures/README.md)을 함께 기록했다. `/tmp`의 원본 표본 결과는 임시 검증 자료다.

## 실제 CLI → MongoDB 적재

위 통합 테스트와 같은 격리 MongoDB에서 `collector_live_validation` DB를 사용했다.

```bash
MONGO_URL=mongodb://127.0.0.1:32768 MONGO_DB=collector_live_validation \
  uv run --frozen opendata-collect collect --source portal --types API \
  --page-size 1 --max-pages 1 --max-details 1 --timeout 15 --retries 1
```

- `run_id`: `12d6ce06-fc9a-4e85-b7d9-65929e7ae9a7`.
- 실제 목록 표시 건수 11,910건 중 1건 적재. 의도한 제한 실행이므로 `paused`, 종료코드 2.
- `detail_completed=1`, `detail_failed=0`, `detail_pending=0`.
- `portal_catalog` 1건, `open_data_info` 1건, `portal_resources` 4건, GridFS 원문/파싱 결과 5건.
- 저장한 상세를 GridFS에서 다시 읽어 압축 해제와 JSON 파싱을 수행했고 Swagger 1개를 확인했다. 종료 후 lease 0건.

검증용 컨테이너는 검증 종료 후 제거한다. 운영 데이터에는 테스트 기록을 남기지 않는다.

## 확인하지 않은 범위

- 포털 전체 카탈로그의 실제 전량 적재와 장기간 운용.
- 승인된 사용자 키를 이용한 공식 목록 API의 실호출. [공식 OAS](https://infuser.odcloud.kr/oas/15077093)와 응답 계약 기반 테스트로 확인했다.
- 로그인·별도 권한이 필요한 정보, 전체 CSV/ZIP/HWP 파일 바이트, 업무 API의 모든 데이터 행, 외부 연계 사이트의 재귀 수집.
- AI 변환, Elasticsearch 재색인, STD/LINKED를 표시하기 위한 UI 확장, 배포·주기 실행 등록.


## 공통 스키마와 조회 API 검증

검증일: 2026-09-04 UTC. `portal_catalog`의 schema version 2, FILE/API/STD/LINKED 유형, 기존 FILE/API 모델 필드, 파일 종류/포맷 분리 및 `/api/v1/catalog` 조회 API를 추가했다.

- 서비스 `uv.lock`과 같은 Beanie 2.0.0, FastAPI 0.116.1, Motor 3.7.1, PyMongo 4.14.1, Pydantic 2.11.7을 사용했다.
- API 단위·계약 테스트는 인메모리 MongoDB와 별도 MongoDB 8.0.12 양쪽에서 실행한다.
- 네 유형이 같은 숫자 ID를 가져도 별도 카탈로그로 조회됨을 확인했다.
- 목록 필터·리터럴 검색·페이지 계산, 상세 JSON 복원, 원천 레코드 추가 필드, 원문 리소스 다운로드를 확인했다.
- 과거 FILE 포맷과 API 유형 필드, schema version이 없는 기존 카탈로그, `None` 키워드를 확인했다.
- 없는 자료는 404, 잘못된 입력은 422, 손상된 gzip/JSON/스키마는 세부 내부 오류를 노출하지 않고 503을 반환한다.
- 기존 AI 상태 필드는 수집기가 갱신하지 않는다. API 테스트용 DB 이름은 임의 UUID로 만들고 테스트 후 해당 DB만 삭제한다.
- 최종 결과: 수집기 인메모리 111개 통과·실DB 4개 조건부 건너뜀, 실제 MongoDB 연결 시 115개 통과; API 인메모리와 실제 MongoDB에서 각각 27개 통과; Ruff와 OpenAPI 신규 경로 5개 검증 통과.
- 독립 리뷰에서 발견한 상세 완전 실패 상태 불일치와 누락 `raw_id`의 500 응답을 회귀 테스트로 재현·수정했다.
- 반복 `collect`의 값 upsert, AI 상태 보존, 상세·리소스 revision 교체, 삭제 항목 비활성 이력, incomplete 실행의 미관측 항목 보존을 검증한다.
- 완료 run 및 더 최신 겹침 run이 존재하는 과거 체크포인트의 재개를 거부해 최신 스냅샷 rollback을 방지한다. 유형이 겹치지 않는 최신 run은 재개를 막지 않는다.
- 실제 MongoDB update 통합 테스트에서 제목·상세 revision 갱신, 삭제 catalog/source 비활성화, 이전 resource 원문 이력과 최신 원문 복원을 확인했다. 최종 독립 재검토에서 추가 정확성·호환성 결함은 없었다.

실행:

```bash
uv venv /tmp/opendata-api-schema-venv
uv pip install --python /tmp/opendata-api-schema-venv/bin/python \
  -r services/opendata-api/tests/requirements.txt
API_SCHEMA_TEST_MONGO_URL=mongodb://127.0.0.1:27017 \
  /tmp/opendata-api-schema-venv/bin/python -m pytest services/opendata-api/tests
```

## 유형별 최대 1,000건 실수집

검증일: 2026-09-04 UTC. FILE/API/LINKED 각각 1,000건과 STD 전체 300그룹을 격리 MongoDB에 적재해 원문 참조와 파싱 결과를 전수 검사했다. 실수집에서 확인한 파서·operation·OpenAPI 경로 문제와 수정 후 결과는 [유형별 최대 1,000건 실수집 리뷰](LIVE_SAMPLE_REVIEW_2026-09-04.md)에 기록했다.

## 유형별 최대 10,000건 실수집

검증 기간: 2026-09-04 ~ 2026-09-06 UTC. FILE/API/LINKED 각각 10,000건과 STD 전체 300그룹을 격리 MongoDB에 적재하고, 상세 JSON 30,258건과 GridFS blob 171,312건의 참조·복원을 전수 검사했다. 대량 표본에서 발견한 LINKED 교차 페이지 중복, Swagger 리터럴 두 패턴, DCAT `dct:conformsTo`, HTTP OpenAPI 명세 URL을 회귀 테스트와 함께 수정했다. 상세 결과와 남은 포털 HTTP 500은 [유형별 최대 10,000건 실수집 리뷰](LIVE_SAMPLE_REVIEW_10000_2026-09-06.md)에 기록했다.
