# 공공데이터포털 메타데이터 수집·적재

data.go.kr의 공개 데이터셋 정보를 MongoDB에 적재하는 독립 CLI입니다. AI를 호출하지 않습니다. API 서버나 Airflow 실행 여부와 관계없이 수동 실행하거나 cron/작업 스케줄러에서 실행할 수 있습니다.

## 수집 범위

| 대상 | 보존 정보 |
| --- | --- |
| 파일데이터(FILE) | 목록, 설명·기관·분류·이용조건 등 상세, 컬럼/표, 배포·다운로드 링크, 과거 버전 목록과 버전 상세 |
| OpenAPI(API) | 목록, 상세, endpoint, 공개 Swagger/OpenAPI 원문, 요청·응답 정의, 표 형식의 오퍼레이션별 상세, 참고문서 식별자 |
| 표준데이터(STD) | 표준 목록, 제공 범위·컬럼, 기관별 구성 목록의 모든 페이지와 개별 메타데이터 |
| 연계데이터(LINKED) | 포털에 공개된 목록·상세·원본 사이트 링크 |
| 공통 | 공개 schema.org JSON, DCAT RDF/XML, 원본 HTML, 공개 원천 레코드의 미지정 필드 |

국가중점데이터는 별도의 `CORE` 데이터 유형으로 취급하지 않습니다. FILE/API 등에 붙는 국가중점 속성은 원천 메타정보에 보존됩니다. STD 목록의 `300개 (12,692건)` 같은 표시는 표준 그룹 300개와 구성 데이터 수를 구분합니다.

이 도구의 전체 수집 대상은 **공개 카탈로그와 명세 메타데이터**입니다. 개별 업무 API의 모든 데이터 행, CSV/HWP/ZIP 등의 전체 파일 바이트, 외부 연계 사이트의 재귀 수집은 포함하지 않습니다. 참고문서·파일은 주소/식별자를 보존합니다. 화면의 AI 요약·활용신청·다운로드 횟수 증가 요청은 실행하지 않습니다.

## 설치

Python 3.10 이상과 MongoDB 5 이상이 필요합니다. 기존 API의 ML 의존성을 설치할 필요는 없습니다.

```bash
cd services/opendata-collector
uv sync --frozen --group dev
uv run opendata-collect --help
```

환경변수:

| 변수 | 설명 |
| --- | --- |
| `MONGO_URL` | MongoDB URI. 기본값 `mongodb://localhost:27017` |
| `MONGO_DB` | 적재 DB. 기본값 `open_data` |
| `ODP_SERVICE_KEY` | 선택. 공공데이터포털 목록 조회 API 사용 승인을 받은 키 |

기존 API 저장소의 환경파일을 명시적으로 사용할 수 있습니다. 환경파일은 코드에 저장하지 않습니다.

```bash
uv run --env-file ../../.env.dev opendata-collect collect
```

## 먼저 소량 확인

DB에 연결하지 않고 유형별 한 데이터셋의 상세 수집 결과를 JSONL로 저장합니다. 표준데이터 하나에도 여러 기관이 있어 상세 요청 수는 한 번을 넘을 수 있습니다.

```bash
uv run opendata-collect preview --source portal --types FILE API STD LINKED \
  --limit 1 --output /tmp/portal-preview.jsonl
```

`--max-member-pages 1`로 표준 구성 목록을 제한할 수 있습니다. 이 경우 미수집이 남으면 종료코드 2와 오류 항목을 반환합니다. 미리보기 성공은 표본의 성공이며 전량 수집을 뜻하지 않습니다.

실제 적재를 작게 시작하려면 아래 명령을 사용합니다. `--max-pages`는 **이번 실행 전체의 신규 목록 페이지 수** 제한입니다. 이 명령은 MongoDB에 씁니다.

```bash
uv run opendata-collect collect --types API --page-size 10 --max-pages 1 --max-details 2
```

## 전량 적재 및 재개

```bash
# 모든 유형의 목록과 상세를 순회; 제한 옵션을 두지 않으면 전체 대상
uv run opendata-collect collect

# 공식 목록 API 사용 강제: 키가 없거나 잘못되면 실패하며 조용히 경로를 바꾸지 않음
uv run opendata-collect collect --source api

# 발급 키 없이 공개 포털 목록 사용
uv run opendata-collect collect --source portal

# 로그/결과의 run_id로 중단한 실행 재개
uv run opendata-collect collect --source portal --resume RUN_ID
uv run opendata-collect status RUN_ID
```

`auto`는 키가 있으면 FILE/API/STD에 공식 API를 사용하고, 없으면 포털 HTML 목록을 사용합니다. LINKED는 두 모드 모두 포털 목록을 사용합니다. 재개는 원래 실행의 source·유형·페이지 크기를 유지하며 API 실행 재개에는 키가 필요합니다. 새 실행은 전체 목록과 상세를 다시 확인하는 전체 갱신입니다.

업데이트도 별도 명령 없이 같은 `collect`를 새로 실행합니다. 동일 ID의 최신 목록·상세·포맷·원천 레코드와 FILE/API projection은 upsert되고 기존 AI 상태는 유지됩니다. 데이터셋의 상세 수집이 성공하면 파싱 상세와 현재 리소스를 같은 revision으로 즉시 갱신하고 이전 리소스는 `is_active=false`, `removed_at` 이력으로 보존합니다. 상세 수집이 완전히 실패하면 이전 리소스를 유지하며 실패 상태와 이유를 기록합니다.

검증까지 완료된 전체 실행에서 사라진 카탈로그·operation은 비활성 이력으로 전환합니다. 제한·오류로 `paused` 또는 `incomplete`인 실행은 발견되지 않은 기존 카탈로그·operation을 비활성화하지 않습니다. `--resume`은 최신 미완료 실행의 체크포인트 재개용입니다. 이미 완료된 run이나 같은 유형의 더 최신 run이 시작된 뒤의 과거 run은 재개할 수 없으며 새 `collect`를 시작해야 합니다.

공식 API는 동일 목록키에 여러 오퍼레이션이나 파일 레코드를 반환할 수 있으므로 `id`와 `operation_seq`를 함께 사용해 원천 레코드를 구분합니다. 목록 ID만으로 덮어쓰지 않습니다. 공식 API 전체 조회와 공개 포털은 공개 시점/대상이 다를 수 있으므로 같은 전체 건수라고 가정하지 않습니다.

## 실행 순서와 월간 스냅샷·참고문서 보강

운영 순서는 `collect` → `snapshot` → `references` → `parse` → AI 처리다. `collect`가 포털의 현재 목록과 상세를 기준으로 `portal_catalog`·`portal_source_records`·`portal_resources`·`portal_raw`에 적재하는 권위 있는 단계다. 이후 단계는 현재 카탈로그를 대체하지 않는다.

`snapshot`은 공공데이터포털의 목록개방현황 월간 CSV를 **명시적으로** 가져와 검증·대조하는 명령이다. `collect`가 자동으로 실행하거나 월간 CSV를 자동으로 내려받지 않는다. 기본 실행은 공개 데이터셋 `15062804`의 읽기 전용 다운로드 정보를 확인한 뒤 CSV를 받고, 재현·복구에는 이미 확보해 검증할 CSV를 `--file`로 지정한다.

```bash
# 1. 현재 공개 카탈로그와 상세를 수집한다.
uv run --env-file ../../.env.dev opendata-collect collect

# 2. 공식 월간 CSV를 별도 generation으로 검증·적재한다.
uv run --env-file ../../.env.dev opendata-collect snapshot

# 네트워크 없이 같은 CSV generation을 다시 적재할 때만 사용한다.
uv run --env-file ../../.env.dev opendata-collect snapshot --file /safe/path/monthly.csv

# 3. 수집된 상세의 공식 참고 첨부문서를 보강한다. 기본 대상은 API다.
uv run --env-file ../../.env.dev opendata-collect references --types API --limit 100

# 4. 네트워크 없이 수집·스냅샷·참고문서 원천을 합쳐 파싱한다.
uv run --env-file ../../.env.dev opendata-collect parse

# 5. 이 결과를 입력으로 하는 AI 단계는 수집기 밖에서 별도로 실행한다.
```

월간 CSV는 전체 바이트·인코딩·필수 헤더·유형·목록 ID·상세 URL을 먼저 검증한 뒤에만 공개한다. 원본 CSV는 SHA-256 주소의 gzip GridFS blob으로 `portal_raw.files/chunks`에 저장하고, provenance(`source`, `raw_id`, `raw_sha256`, record hash, 원본 행)는 `portal_snapshot_runs`와 `portal_snapshot_records`에 남긴다. 완료 generation만 현재 generation으로 읽히며, 보고서의 `matched`·`snapshot_only`·`current_only` 대조는 **활성 API/FILE/STD** live `portal_catalog`만을 모집단으로 한다. 비활성 레코드와 LINKED 유형은 이 대조에서 제외된다. 실패하거나 지나치게 작은 CSV는 이전 완료 generation을 바꾸지 않는다. 기본 CSV/로컬 replay 한도는 **256 MiB**이고 `--max-bytes`로 더 낮출 수 있다. 이 명령은 `portal_catalog`, 기존 projection, AI 문서를 쓰지 않는다.

동일 CSV를 다시 실행하면 원본 blob과 immutable generation 행을 재사용하지만, 반환 보고서의 `reconciliation`은 실행 시점의 활성 live 카탈로그와 다시 계산한다. `reused_generation`, `reconciled_at`으로 재사용 여부와 대조 시각을 표시하며, 재사용 시 `publication_summary`에는 최초 공개 시점의 보고서를 별도로 담는다. 저장된 최초 보고서는 바뀌지 않는다.

`parse`는 최신 완료 `portal_snapshot_runs`의 같은 카탈로그 행을 live 원천 뒤에 추가한다. 따라서 live 목록·상세의 값이 우선하고 빈 값만 월간 행으로 보완된다. parsed 문서에는 원본 월간 열(`monthly_snapshot`)과 `snapshot_run_id`, `snapshot_source`, `snapshot_raw_sha256`가 함께 남는다.

`references`는 이미 수집된 활성 카탈로그의 data.go.kr 등록 첨부 중 PDF, DOCX, HWP, HWPX만 고른다. 등록 첨부 식별자와 다운로드 URL, 문서 원본/텍스트 SHA-256 GridFS 참조, 추출 상태·오류·문자 수는 `portal_reference_runs`, `portal_reference_run_items`, 그리고 `kind="reference_document"`인 `portal_resources`에 저장된다. `parse`는 이 metadata를 해당 `detail.attachments[].reference_document`에 다시 연결한다. 일반 상세·DCAT·OpenAPI resource는 reference refresh에서 retire하지 않는다.

각 canonical 첨부 ID에는 안정적인 ID를 갖는 resource head 하나만 공개된다. `reference_head`는 이 head의 ID이고 sparse unique index로 중복을 막는다. 성공한 원문·텍스트 blob을 저장한 다음 head를 단일 MongoDB update로 교체하며, 다운로드·추출·공개 실패는 이전 head를 바꾸지 않는다. 실패한 추출의 원본 hash와 상태는 run item에 남고, 이전 원문·텍스트 blob은 유지된다. API와 `parse`, 재수집 skip 판정은 head만 사용한다.

이전 버전의 revision resource가 있으면 `references` 시작 시 가장 최근 성공 revision을 head로 복사한 뒤 기존 revision을 비활성화한다. 이 마이그레이션은 모든 유형에 적용되고 반복 실행할 수 있으며, 복사나 정리 중 실패하면 같은 명령을 다시 실행한다. 기존 head는 덮어쓰지 않는다. 업그레이드 시 **collector의 이 마이그레이션을 완료한 뒤 head만 읽는 API/parse 버전을 사용**한다. 원문·텍스트 blob과 비활성 revision은 삭제하지 않는다.

완료된 상세 관찰에서 사라지거나 canonical ID가 교체된 참고문서는 다음 `references` 실행·재개에서 비활성화한다. 이 대조는 선택 유형 전체에 적용되고 `--limit`은 다운로드 대상 수만 제한하므로 0개 선택이나 한도 이후 카탈로그에서도 누락 ID를 정리한다. partial/failed 상세, 읽을 수 없는 원문, 첨부 목록·식별자 검증 실패에서는 이전 head를 유지한다.

참고문서의 기본 다운로드 한도는 파일당 **32 MiB**, 텍스트 한도는 **1,000,000자**다. 추출기는 PDF 페이지·스트림, 압축 archive, HWP stream도 별도 제한으로 검사한다. `--max-bytes`와 `--max-chars`로 더 엄격하게 제한할 수 있다. `--force`는 이미 성공한 같은 첨부도 다시 처리하고, `--resume RUN_ID`는 실패·보류 checkpoint를 다시 시도하며 최초 run에 저장한 대상·한도를 그대로 사용한다. 완료 run은 재개할 수 없다. 실행·재개 ID는 작업 시작 시 stderr에 즉시 출력하고, 최종 JSON 보고서는 stdout에 출력한다.

포털의 일시 오류, 다운로드 초과, 손상 파일, 사라진 첨부, 수집 상세 원문 누락은 문서별 오류 또는 `stale` 상태로 기록된다. 이런 provider-side 부분 실패가 남으면 reference run은 `incomplete`, 종료코드 2가 되며 이전 정상 reference resource는 유지된다. 재개 후 실패가 해소되면 완료될 수 있다. 이 단계는 공개 메타데이터의 허용된 data.go.kr 다운로드 경로만 요청하며, `ODP_SERVICE_KEY`가 필요 없고 개별 업무 API를 호출하지 않는다.

## AI 처리 전 파싱

수집이 끝난 뒤 별도 `parse` 명령으로 저장된 원천을 정규화합니다. 이 단계는 네트워크나 AI 서비스를 호출하지 않고 `portal_catalog`, `portal_source_records`, GridFS 상세 JSON 및 현재 리소스만 읽습니다.

```bash
# FILE/API/STD/LINKED 전체 파싱
uv run --env-file ../../.env.dev opendata-collect parse

# 선택 유형만 최대 1,000건 파싱
uv run --env-file ../../.env.dev opendata-collect parse \
  --types API FILE --limit 1000

# 원천이 같아도 다시 파싱
uv run --env-file ../../.env.dev opendata-collect parse --force
```

파싱 결과는 `list_id`로 upsert합니다. 원천 필드·상세 JSON·활성 리소스 ID와 parser version으로 fingerprint를 계산하여 변경이 없는 문서는 건너뜁니다. 원천이 바뀌거나 parser version이 올라가면 다시 파싱합니다. 기존 중복 `parsed_api_info`/`parsed_file_info` 문서는 해당 ID를 처리할 때 최신 `parsed_at`의 `_id` 하나를 유지합니다. 현재 parser version은 `3`이며 기존 version `1`·`2` 문서는 다음 `parse` 실행에서 자동으로 다시 파싱됩니다.

모든 parsed 문서는 상세 URL, 제공기관·부서·연락처, 등록·공개·수정일, 라이선스·보유근거, 갱신주기, 매체·행 수, 공간·시간 범위와 원본 metadata/schema.org/첨부자료를 보존합니다. 날짜는 UTC로 정규화하되 유효한 원천 날짜가 없으면 `null`로 둡니다.

| 원천 유형 | 파싱 결과 |
| --- | --- |
| API | `parsed_api_info`: OpenAPI 2/3 endpoint·요청·응답·예시·서버·보안·제약조건. OpenAPI와 operation 표를 endpoint별로 병합하고 명세·서비스 URL·첨부자료도 보존 |
| FILE | `parsed_file_info`: 배포 링크, 컬럼, 과거 버전과 상세, 포함된 OpenAPI endpoint와 명세 문맥 |
| STD | `parsed_std_info`: 표준 요약·컬럼·멤버 수. 기관별 자료는 `parsed_std_members`에 분리 |
| LINKED | `parsed_linked_info`: schema.org와 DCAT의 기관·라이선스·접근 URL |

`portal_catalog.parse_status`는 `completed`, `partial`, `failed` 중 하나이며 오류는 `parse_errors`에 저장합니다. 상세 수집이 부분 성공한 자료도 가능한 필드를 저장하고 `partial`로 표시합니다. 파서 자체가 실패하면 기존 정상 parsed 문서는 유지하고 상태만 `failed`로 기록합니다. API/FILE의 기존 원천 문서에는 `is_parsed=Y` 또는 `ERROR`와 `parsed_at`을 함께 갱신합니다. `generated_*` 컬렉션은 이 단계에서 읽거나 수정하지 않습니다. 부분 결과나 실패가 하나라도 있으면 명령 결과는 `incomplete`이고 종료코드는 2입니다.

수집 속도 기본값은 요청 간 최소 0.5초, timeout 30초, 일시적 실패에 최초 요청 + 최대 3회 재시도입니다. `--interval`, `--timeout`, `--retries`, `--page-size`로 조정합니다. 페이지 크기 기본값은 100이며 응답이 요청 크기/페이지를 다르게 반환하면 중단합니다. 표준 구성 데이터는 포털이 정한 별도 페이지 크기를 사용합니다.

## 완료 판정과 오류 복구

- `completed`: 선택한 모든 목록을 끝까지 순회했고, 실행별 고유 원천 레코드 수가 표시 건수와 일치하며, 발견된 데이터셋의 상세·부가 메타정보 수집이 성공함. 마지막으로 모든 목록 페이지를 다시 조회해 최초 페이지별 ID 집합과 건수를 대조한 결과도 일치해야 함.
- `paused`: 페이지/상세 수 제한으로 미처리 항목이 남음. 같은 `run_id`로 재개.
- `incomplete`: 목록/상세 오류, 건수 변동, 중복 페이지, 미수집 부가정보 등이 있음. 오류 원인을 확인하고 재개. 건수 변동·중복 페이지·목록 교체(`snapshot_changed`)가 발생한 실행은 새 실행으로 다시 수집.

종료코드: 0 완료(또는 성공한 미리보기/상태 조회), 2 제한·미완료, 1 설정/접속/치명적 오류, 130 사용자 중단. 프로세스 로그에 시작 `run_id`가 남으므로 예기치 않은 종료 후에도 재개할 수 있습니다. DB 쓰기가 실패한 페이지는 체크포인트를 전진시키지 않습니다.

완료 검증은 목록 페이지를 한 번 더 읽으므로 목록 요청 수가 증가합니다. 검증 도중 통신 오류만 발생했다면 재개할 수 있으며, 재개 시 전체 검증을 다시 수행합니다.

실행 중 하나의 DB에는 수집기 하나만 쓰도록 lease를 사용합니다. 정상 종료 시 해제하고, 강제 종료 시 마지막 heartbeat로부터 최대 10분 뒤 만료됩니다. 포털은 실시간으로 변하므로 원자적인 전체 시점 스냅샷을 보장하지 않습니다. 누락을 조용히 완료 처리하지 않습니다. 발견되지 않은 기존 데이터는 성공한 전체 갱신에서만 비활성 이력으로 전환하며 물리적으로 삭제하지 않습니다.

로그인·권한 제한, 외부 호스트의 명세, 포털 장애/화면 개편, 제공되지 않는 명세는 자동으로 우회하지 않습니다. 실패 이유와 가능한 원본을 저장하고 해당 상세를 미완료로 남깁니다. 허용되는 네트워크 대상은 공개 메타데이터용 data.go.kr/odcloud.kr의 지정 경로입니다.

## MongoDB 저장 구조

| 컬렉션 | 역할 |
| --- | --- |
| `portal_catalog` | `(data_type, list_id)`별 목록, 상세 상태, 현재/삭제 이력, 원본/파싱 결과 참조 |
| `portal_source_records` | 공식 API/포털의 원천 레코드; 추가 필드·복수 오퍼레이션 보존 |
| `portal_runs` | source·대상·페이지 체크포인트·건수·완료 요약 |
| `portal_run_records` | 실행별 고유 원천 레코드 membership, 첫 발견 페이지 |
| `portal_run_items` | 실행별 데이터셋 상세 상태와 실패 이유 |
| `portal_pages` | 저장한 목록 페이지, ID 집합 해시, 원본 참조 |
| `portal_resources` | 메타데이터 URL·종류·조회시각·원본 SHA256 |
| `portal_raw.files/chunks` | gzip 압축한 원본 및 전체 파싱 JSON. 큰 명세의 MongoDB 16MB 문서 제한 회피 |
| `portal_locks` | 동시 실행 제어 |
| `portal_snapshot_runs`, `portal_snapshot_records`, `portal_snapshot_locks` | 검증된 월간 CSV generation, 원본 행 provenance, generation 공개 lease; live 카탈로그와 분리 |
| `portal_reference_runs`, `portal_reference_run_items` | 공식 참고문서 선택·다운로드·추출의 run 설정과 문서별 resume checkpoint |
| `open_data_info`, `open_file_info` | 기존 API와 연결되는 요약 projection 및 파싱 상태 |
| `parsed_api_info`, `parsed_file_info` | AI 이전 API/FILE 정규화 결과 |
| `parsed_std_info`, `parsed_linked_info` | AI 이전 STD/LINKED 정규화 결과 |
| `parsed_std_members` | 표준데이터셋의 기관별 구성 자료; 현재/삭제 이력 포함 |

FILE/API 상세 수집이 성공한 경우 기존 컬렉션에 `list_id`로 upsert합니다. 기존 `_id`, `is_parsed`, `parsed_at`, AI 문서 컬렉션은 유지합니다. 출처에 없는 Y/N 값은 `None`으로 저장하며 기존 API 모델도 이를 허용합니다. STD/LINKED 원천 요약은 `portal_catalog`에 저장하고 파싱 결과는 각 `parsed_*` 컬렉션에 저장합니다. 기존 UI의 표시 유형 추가는 이 수집기 범위 밖입니다. Elasticsearch 재색인은 기존 API의 별도 색인 명령을 사용합니다.


새로 적재되는 FILE projection은 `data_type="FILE"`과 실제 `data_format`을 분리합니다. 기존 API 모델에는 수집 출처·시각·연락처·첨부·오퍼레이션 필드가 선언되어 있어 상세 응답에서 보존됩니다. 네 유형의 공통 메타데이터, 원천 레코드 및 GridFS 원문은 API 서버의 `/api/v1/catalog` 경로로 조회할 수 있습니다.

원본/파싱 결과 조회 예시:

```python
import gzip
import json
import os
import gridfs
from pymongo import MongoClient

db = MongoClient(os.environ["MONGO_URL"])[os.getenv("MONGO_DB", "open_data")]
record = db.portal_catalog.find_one({"_id": "API:15129394"})
fs = gridfs.GridFS(db, collection="portal_raw")
detail = json.loads(gzip.decompress(fs.get(record["parsed_detail_ref"]).read()))
print(detail["metadata"], detail["api_specs"])
```

## 검증

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .

# 별도로 준비한 검증용 MongoDB에 대해서만 실행
MONGO_TEST_URL=mongodb://127.0.0.1:27017 uv run pytest tests/test_mongo_integration.py
```

단위 테스트는 HTTP 경계의 응답만 대체하고 실제 페이지 파서·페이지 검증·수집 상태 전이·DB 적재 로직을 실행합니다. 기본 실행에서는 실제 Mongo 통합 테스트를 건너뜁니다. `MONGO_TEST_URL`을 지정하면 UUID로 생성한 검증 DB에서 테스트하고 해당 DB만 삭제합니다. Mongo 동작은 mongomock/GridFS와 실제 MongoDB에서 검증하며 결과는 [VALIDATION.md](VALIDATION.md)에 기록합니다. 공개 HTML fixture는 원본 페이지의 필요한 부분을 발췌했고 출처는 `tests/fixtures/README.md`에 기록합니다.

공식 제공 근거: [목록 조회 API 명세](https://infuser.odcloud.kr/oas/15077093), [공공데이터포털 목록](https://www.data.go.kr/tcs/dss/selectDataSetList.do), [목록개방현황](https://www.data.go.kr/data/15062804/fileData.do). 목록개방현황 CSV는 시점 스냅샷이므로 live `collect`의 자동 원천은 아니다. 대신 `snapshot`의 명시적 명령으로 전체 검증·대조 후 parsed 데이터의 최하위 우선순위 fallback으로 사용한다.
