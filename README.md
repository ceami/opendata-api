# Open Data API

한국 공공데이터포털(OpenAPI)을 더 쉽게 탐색할 수 있도록 돕는 REST API 서버입니다. 다음과 같은 API 엔드포인트를 제공합니다:

- **검색 API**: 키워드로 공공데이터 API를 검색
- **문서 API**: 생성된 API/File 문서 목록 조회
- **문서 상세 API**: 특정 list_id의 API 표준 문서 상세 정보 조회

내부적으로 검색/문서 도구는 `mcp.dev.ezrnd.co.kr`(HTTPS) 백엔드를 사용합니다.

## 요구사항

- Python 3.8+
- MongoDB (데이터 저장용)
- Elasticsearch (검색 엔진용)
- Docker & Docker Compose (권장)

## 설치

### 1. 저장소 클론

```bash
git clone http://github.com/ceami/open-data-mcp-api.git
cd open-data-mcp-api
```

### 2. 환경변수 설정

- `ODP_SERVICE_KEY`: 공공데이터포털 서비스 키
  - 파라미터 이름에 `serviceKey`가 포함되어 있으면 자동 주입
  - 헤더 이름에 `Authorization`이 포함되어 있으면 `Infuser {키}` 형식으로 자동 주입
- `MONGODB_URI`: MongoDB 연결 URI (기본값: `mongodb://localhost:27017`)
- `ELASTICSEARCH_URL`: Elasticsearch URL (기본값: `http://localhost:9200`)
- `API_HOST`: API 서버 호스트 (기본값: `0.0.0.0`)
- `API_PORT`: API 서버 포트 (기본값: `8000`)

## 실행

### Makefile을 사용한 실행 (권장)

```bash
# 모든 서비스 시작
make up

# 서비스 재시작
make restart

# 서비스 중지
make down

# 개발 환경으로 실행
ENV=dev make up

# 프로덕션 환경으로 실행
ENV=prod make up
```

### Docker Compose 직접 실행

```bash
# 모든 서비스 시작
docker-compose up -d

# 로그 확인
docker-compose logs -f opendata-api

# 서비스 중지
docker-compose down
```

### 개별 서비스 실행

```bash
# MongoDB 시작
docker-compose up -d elasticsearch

# Elasticsearch 시작
docker-compose up -d elasticsearch

# API 서버 시작
cd services/opendata-api
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

## API 엔드포인트

### 1. 검색 API

**엔드포인트**: `GET /api/v1/search`

**설명**: 공공데이터포털에서 키워드로 API 목록을 검색합니다.

**쿼리 파라미터**:
- `query`: 검색 키워드 (공백으로 구분, 최대 5개 권장)
- `page`: 페이지 번호 (기본값: 1)
- `page_size`: 페이지 크기 (기본값: 10)
- `data_type`: 데이터 타입 필터 (선택사항)

**예시 요청**:
```bash
curl "http://localhost:8000/api/v1/search?query=기상%20단기예보&page=1&page_size=10"
```

**응답 예시**:
```json
{
  "total": 150,
  "page": 1,
  "page_size": 10,
  "results": [
    {
      "list_id": 12345,
      "title": "기상청 단기예보 API",
      "org_nm": "기상청",
      "desc": "단기예보 정보를 제공하는 API입니다."
    }
  ]
}
```

### 2. 문서 API

**엔드포인트**: `GET /api/v1/document/std-docs`

**설명**: 생성된 API/File 문서 목록을 조회합니다.

**쿼리 파라미터**:
- `list_ids`: 조회할 list_id 목록 (선택사항, 미입력시 전체 조회)
- `page`: 페이지 번호 (기본값: 1)
- `page_size`: 페이지 크기 (기본값: 10, 최대: 100)

**예시 요청**:
```bash
# 특정 list_id들의 문서 조회
curl "http://localhost:8000/api/v1/document/std-docs?list_ids=12345&list_ids=23456&page=1&page_size=10"

# 전체 문서 조회
curl "http://localhost:8000/api/v1/document/std-docs?page=1&page_size=10"
```

**응답 예시**:
```json
[
  {
    "listId": 12345,
    "dataType": "API",
    "listTitle": "기상청 단기예보 API",
    "detailUrl": "https://www.data.go.kr/data/12345/openapi.do",
    "generatedStatus": true,
    "createdAt": "2024-01-15T10:30:00",
    "updatedAt": "2024-01-15T14:30:00",
    "description": "단기예보 정보를 제공하는 API입니다.",
    "orgNm": "기상청",
    "deptNm": "기상청",
    "isCharged": "N",
    "shareScopeNm": "공개",
    "keywords": ["기상", "예보", "날씨"],
    "tokenCount": 150,
    "generatedAt": "2024-01-15T14:30:00",
    "markdown": "# 기상청 단기예보 API\n\n## 개요\n\n단기예보 정보를 제공하는 API입니다..."
  }
]
```

### 3. 문서 상세 API

**엔드포인트**: `GET /api/v1/document/std-docs/{list_id}`

**설명**: 특정 list_id의 API 표준 문서 상세 정보를 조회합니다.

**예시 요청**:
```bash
curl "http://localhost:8000/api/v1/document/std-docs/12345"
```

**응답 예시**:
```json
{
  "listId": 12345,
  "dataType": "API",
  "listTitle": "기상청 단기예보 API",
  "detailUrl": "https://www.data.go.kr/data/12345/openapi.do",
  "generatedStatus": true,
  "createdAt": "2024-01-15T10:30:00",
  "updatedAt": "2024-01-15T14:30:00",
  "description": "단기예보 정보를 제공하는 API입니다.",
  "orgNm": "기상청",
  "deptNm": "기상청",
  "isCharged": "N",
  "shareScopeNm": "공개",
  "keywords": ["기상", "예보", "날씨"],
  "tokenCount": 150,
  "generatedAt": "2024-01-15T14:30:00",
  "markdown": "# 기상청 단기예보 API\n\n## 개요\n\n단기예보 정보를 제공하는 API입니다..."
}
```

## 프로젝트 구조

```
open-data-mcp-api/
├── docker-compose.yml          # Docker Compose 설정
├── LICENSE                     # 라이선스 파일
├── Makefile                    # 빌드 및 실행 스크립트
├── README.md                   # 프로젝트 문서
└── services/
    ├── elasticsearch/          # Elasticsearch 서비스
    │   ├── Dockerfile
    │   └── elasticsearch.yml
    └── opendata-api/           # 메인 API 서비스
        ├── Dockerfile
        ├── pyproject.toml
        └── src/
            ├── api/            # API 라우터
            │   └── v1/
            │       └── routers/
            │           ├── document.py
            │           └── search.py
            ├── core/           # 핵심 설정
            │   ├── dependencies.py
            │   ├── exceptions.py
            │   ├── gunicorn_config.py
            │   └── settings.py
            ├── db/             # 데이터베이스 연결
            │   └── mongo.py
            ├── index/          # 인덱싱 스크립트
            │   ├── delete_index.py
            │   ├── index_titles.py
            │   └── run_indexing.py
            ├── main.py         # 애플리케이션 진입점
            ├── models/         # 데이터 모델
            │   └── open_data.py
            ├── schemas/        # Pydantic 스키마
            │   ├── response.py
            │   └── schemas.py
            ├── service/        # 비즈니스 로직
            │   ├── cross_collection.py
            │   └── search.py
            └── utils/          # 유틸리티
                └── logger.py
```

## API 문서

API 문서는 서버 실행 후 다음 URL에서 확인할 수 있습니다:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## 라이선스

이 저장소의 라이선스는 루트의 `LICENSE` 파일을 참고하세요.