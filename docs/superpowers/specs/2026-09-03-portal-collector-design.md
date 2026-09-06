# 공공데이터포털 메타데이터 수집기

사용자가 요청한 범위는 data.go.kr의 데이터셋/OpenAPI 정보 수집·적재이며 AI 이전까지다. 새 서브시스템으로 `services/opendata-collector`를 추가한다. 기존 API의 배포와 수집기의 실행·의존성을 분리한다.

## 수집 범위와 출처

- FILE, API, STD, LINKED 목록 전체와 공개 상세 메타정보, schema.org, DCAT, Swagger/OpenAPI, 참고문서 링크, 표준데이터 기관별 목록을 보존한다.
- 공식 목록 API: `https://api.odcloud.kr/api/15077093/v1/{file-data-list,open-data-list,standard-data-list}`. OAS: <https://infuser.odcloud.kr/oas/15077093>. 발급받은 키는 Authorization 헤더로 전달한다. 공식 원천의 한 목록에 여러 오퍼레이션/파일 레코드가 있어도 버리지 않는다.
- 공개 목록: `https://www.data.go.kr/tcs/dss/selectDataSetList.do`의 `dType`, `currentPage`, `perPage`. STD의 그룹 수와 구성 데이터 수를 구분한다. 국가중점은 독립 목록 유형이 아닌 FILE/API 등에 붙는 분류다.
- 상세의 실제 메타데이터 링크를 따라간다. 포털 자체의 AI 요약, 활용신청, 다운로드 횟수 갱신 API는 실행하지 않는다. 개별 업무 API의 전체 데이터 행, 다운로드 파일의 바이트, 외부 사이트 재귀 수집은 범위 밖이다.

## 구조

- http: 제한된 공개 메타데이터 호스트/경로, 요청 간격, timeout, bounded retry, 응답 크기 제한, 비밀키 비노출.
- sources/parsers: 공식 응답과 공개 HTML을 공통 목록 구조로 변환. 원천 행을 보존하고 ID/페이지/건수 이상을 오류로 처리한다.
- store: MongoDB의 `portal_catalog`, `portal_source_records`, `portal_run_items`, `portal_runs`, GridFS `portal_raw`. `(유형, 목록키)`로 충돌을 방지하고 각 실행의 발견/상세 완료 상태를 별도 보관한다.
- pipeline: 목록 페이지 저장 후 체크포인트 이동, 재개 시 완료된 상세를 건너뜀, 실패 상세 재시도. 페이지/건수 변동·중복·상세 실패·실행 제한이 있으면 완료로 보고하지 않는다. 삭제는 자동 추정하지 않는다.
- projection: FILE/API는 기존 `open_file_info`/`open_data_info`로 전달한다. 알려지지 않은 boolean은 None을 허용한다. 기존 AI 생성물과 파싱 상태를 초기화하지 않는다.
- CLI: collect/status, source auto/api/portal, 유형/페이지 크기, 재개, 소량 제한, Mongo 환경변수, JSON 요약. JSONL 미리보기는 DB 없이 실행 가능하다.

## 검증

Python >=3.10. 공개 포털 실제 HTML 일부를 고정 fixture로 사용한다. HTTP 재시도/인증키 격리, 마지막 페이지/빈 페이지/반복 페이지, 원천 오퍼레이션 충돌, Mongo 멱등성/AI 상태 유지, 재개/실패/완료 판정에 단위 테스트를 둔다. 실서비스 Mongo에는 검증 데이터를 쓰지 않고 격리 Mongo 또는 테스트 double을 사용한다. 실제 포털은 소량 미리보기만 조회한다. 전체 적재 코드를 제공하는 것과 실제 전량 적재를 완료하는 것은 구분한다.
