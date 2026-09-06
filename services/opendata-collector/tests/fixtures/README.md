# 공공데이터포털 HTML fixture 출처

이 디렉터리의 9개 HTML fixture는 **2026-09-03 UTC**에 인증 없이 조회한 공공데이터포털 공개 페이지를 바탕으로 작성했다. 공개 페이지의 현재 내용과 건수는 수집 시점에 따라 바뀔 수 있다. 로그인 정보, 인증키, 세션 쿠키는 포함하지 않는다.

## 목록 페이지

목록 fixture는 응답의 페이지 번호·페이지 크기 입력값, 결과 제목과 총건수, 첫 번째 데이터 항목의 HTML 구조를 남겼다. 페이지의 다른 항목, 탐색 메뉴, 검색 UI, 동작 버튼과 스크립트는 제거했다. 클래스와 상세 링크, 식별자, 표시 이름, 배지 및 일부 메타데이터를 유지하면서 공백을 정리했다. 설명문은 테스트에 필요한 짧은 문장으로 축약·재작성했다.

| 파일 | 공개 출처 URL | 보존한 항목과 검증 목적 |
| --- | --- | --- |
| `list-api.html` | <https://www.data.go.kr/tcs/dss/selectDataSetList.do?dType=API&currentPage=1&perPage=10> | `API:15075883`, 오픈API 총 11,910건, 제공기관·수정일·조회수·배지. API 식별자와 정규 상세 URL, 목록 요약 추출을 검증한다. |
| `list-file.html` | <https://www.data.go.kr/tcs/dss/selectDataSetList.do?dType=FILE&currentPage=1&perPage=10> | `FILE:3049380`, 파일데이터 총 84,179건, CSV 및 JSON + XML 배지. 파일 유형과 복수 포맷 표시 보존을 검증한다. |
| `list-std.html` | <https://www.data.go.kr/tcs/dss/selectDataSetList.do?dType=STD&currentPage=1&perPage=10> | `STD:15028204`, 표준데이터셋 300개 및 구성 데이터 12,692건. 그룹 수와 구성 데이터 수를 구분하는지 검증한다. |
| `list-linked.html` | <https://www.data.go.kr/tcs/dss/selectDataSetList.do?dType=LINKED&currentPage=1&perPage=10> | `LINKED:33643`, 연계데이터 총 262,684건. 실제 응답에서 키워드 문자열이 닫힌 `li` 뒤에 놓인 구조를 유지하여 요약 본문에 해당 값이 보존되는지 검증한다. |

각 목록 HTML 파일에는 발췌한 항목 하나만 들어 있다. `test_parsers.py`의 `fixture()` 함수는 목록을 읽을 때 그 항목을 9번 복제하고 상세 링크의 숫자 식별자를 증가시켜 10개 항목의 테스트 응답을 만든다. **추가된 9개 식별자는 테스트 데이터**이며, 해당 ID의 실제 데이터 존재를 의미하지 않는다. 이를 통해 원래 페이지 크기 10을 유지하면서 중복 식별자, 잘못된 유형, 누락된 링크·건수·페이지 정보, 서버가 무시한 페이지 요청, 비어 있거나 짧은 응답을 검증한다.

## 상세 페이지와 파일 이력

| 파일 | 공개 출처 URL | 발췌·축약 방식과 검증 목적 |
| --- | --- | --- |
| `detail-api.html` | <https://www.data.go.kr/data/15129394/openapi.do> | 조달청 입찰공고정보서비스의 숨은 식별자, 메타데이터 구조, 전화번호 문자열 선언, Schema.org/DCAT 링크, 참고문서 이름과 다운로드 식별자를 발췌했다. JSON-LD는 식별 URL을 유지한 작은 객체로 재구성하고 설명 안의 실제 개행 문자를 남겼다. 원본의 큰 `swaggerJson`은 같은 템플릿 문자열·백슬래시 이스케이프 구조를 사용하는 작은 **테스트용 명세**로 교체했다. 이 명세의 `/bids` 경로와 문구는 실제 API 계약을 나타내지 않는다. 메타데이터·참고문서 보존, 한국어와 개행 디코딩, 요청 매개변수 및 응답 명세 보존을 검증한다. 오류 코드 표도 최소한의 열과 한 행으로 축약했다. |
| `detail-file.html` | <https://www.data.go.kr/data/3049380/fileData.do> | 한국연구재단 KCI인용지수정보의 숨은 식별자, 제목·갱신주기, 메타데이터 링크, 파일 다운로드 호출 인수, 컬럼 정의서 링크를 발췌했다. 컬럼 표는 항목명·데이터타입·최대길이의 세 열과 한 행으로 축약했다. 원본 `SwaggerUIBundle` 호출은 실제 외부 명세 URL과 최소 옵션을 보존했다. 파일 식별자, 정의서 URL, 컬럼 정보 및 외부 OpenAPI 명세 발견을 검증한다. |
| `detail-std.html` | <https://www.data.go.kr/data/15028204/standard.do> | 전국자동차정비업체표준데이터의 식별자, 관련법령, 메타데이터 링크, `standDataVO` 폼, 제공기관 수 222건을 발췌했다. 구성 데이터 표는 실제 첫 번째 행 하나만, 페이지 링크는 1·2·45만 남겼다. 구성 데이터의 UDDI 식별자·제공기관·등록일 및 마지막 페이지 45를 추출하고 `stdFileList.do` 조회 정보를 구성하는지 검증한다. |
| `detail-linked.html` | <https://www.data.go.kr/data/33643/linkedData.do> | 법령 연계데이터의 `publicDataLinkedPk`, 제목, 제공처 URL, Schema.org/DCAT 링크와 제공처 바로가기 요소를 발췌했다. 제목은 짧게 줄였다. 제공처 링크에 붙은 사용횟수 갱신 호출을 그대로 남겨 링크형 메타데이터를 보존하면서 이를 다운로드 첨부로 취급하지 않는지 검증한다. |
| `file-history.html` | <https://www.data.go.kr/tcs/dss/selectHistAndCsvData.do?publicDataPk=3049380&publicDataDetailPk=uddi%3Aa7c1395d-5090-42f5-a3a1-8f4d41477dd1> | 파일 상세 페이지가 별도로 불러오는 공개 이력 응답이다. `tab-layer-file-04` 미리보기와 `tab-layer-file-05` 과거 데이터 영역을 유지했다. 원본 50행 미리보기는 한 열·한 행으로 축약·재구성했다. 원본 4개 이력 중 20211231 버전 한 행의 실제 제목·등록일·`data-public-pk`·`data-public-detail-sn`을 남겼다. 미리보기·이력 표 보존과 팝업 조회 식별자 추출을 검증한다. |

## 동적 메타데이터 요청의 근거

- [파일 상세 페이지 스크립트](https://www.data.go.kr/js/biz/datset/script_fileDetail.js)의 `fn_histAndCsvData(pk, detailPk)`가 `/tcs/dss/selectHistAndCsvData.do`에 `publicDataPk`, `publicDataDetailPk`를 전달한다. 위의 이력 fixture 출처는 공개 GET 응답으로 확인했다.
- 이력 응답의 팝업 스크립트는 `data-public-pk`를 `publicDataDetailPk`로, **`data-public-detail-sn`을 `publicDataHistSn`으로** 전달하여 `/tcs/dss/selectDpkDetailInfo.do`를 조회한다. HTML 속성 이름과 요청 매개변수 이름이 다르다는 점을 테스트에서 확인한다.
- API 상세 페이지의 `fn_selectApiDetailFunction`은 `/tcs/dss/selectApiDetailFunction.do`에 `oprtinSeqNo`, `publicDataDetailPk`를 전달한다. 위 API fixture의 원본은 Swagger 방식이므로 실제 선택 목록이 없다. 선택 가능한 오퍼레이션이 있는 경우의 테스트는 공개 스크립트의 호출 구조를 바탕으로 `test_parsers.py` 안에서 작은 선택 목록을 추가한다.

## 테스트 범위

fixture와 함께 사용하는 오류·경계 입력은 `test_parsers.py`에서 명시적으로 만든다. 여기에는 유지보수·로그인 HTML, 잘못된 식별자, 반복되는 메타데이터 라벨, 내부 식별자가 다른 표준데이터, 손상된 Swagger JSON, 이력 팝업 다운로드 인수 등이 포함된다. 파서는 HTML과 문자열 데이터를 읽으며 페이지 JavaScript나 다운로드·사용횟수 갱신 동작을 실행하지 않는다.

축약한 표와 페이지 링크는 선택자 및 메타데이터 보존을 검증하기 위한 것이므로 실제 전체 행 수를 재현하지 않는다. 전체 수집 동작은 별도의 수집기 테스트 및 원본 공개 응답을 사용한 통합 검증에서 확인한다.
