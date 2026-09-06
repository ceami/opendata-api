# Catalog Schema and API Integration Plan

> Execution: apply the approved schema changes in the current workspace, with regression tests before behavior changes. Existing collector work and unrelated user edits remain intact.

**Goal:** Expose the collected FILE/API/STD/LINKED metadata through typed models and the API, while keeping existing FILE/API consumers compatible.

**Architecture:** `portal_catalog` is the common collected catalog. Add a typed document and response contract, and a paginated `/api/v1/catalog` read API for metadata, source records, and raw resources. The existing document API continues to serve its current AI document/ranking use case with declared collection fields and corrected file formats. A catalog's identity is `(data_type, list_id)`.

**Constraints:** Python >=3.10; no AI or external API calls from read routes; no production DB migration or indexing run; existing documents missing new fields remain readable; raw provider fields and GridFS payloads remain lossless; user changes to Docker Compose and Elasticsearch are preserved.

## 1. File format and legacy schema compatibility

Files: collector `projection.py`, `store.py`; API `models/catalog.py`, `models/open_data.py`, `models/__init__.py`, domain `entities.py`, DTO `dto.py`; affected file-format readers in catalog and indexing.

- [x] Add regressions proving FILE:3049380 is CSV, not FILE, and old `data_type=CSV` documents still read as FILE with CSV format.
- [x] Test that STD/LINKED identities survive domain normalization and invalid types do not become API silently.
- [x] Define optional collection fields (`source_catalog_id`, `collected_at`, `detail_url`, `contact`, `summary`, `attachments`, `operations`) and normalize file kind/format on read.
- [x] Set explicit `data_format` in new file projections; preserve the provider's full row in `portal_source_records`.
- [x] Update existing detail responses and index builders to consume `data_format`, with compatibility for old file rows.
- [x] Run collector unit tests and focused API schema tests.

## 2. Typed common catalog and read endpoints

Files: API `models/catalog.py`, `db/mongo.py`, catalog `portal_catalog_service.py`, `dto.py`, router `catalog.py`, `api/__init__.py`, `main.py`; collector `store.py`.

Public interfaces:

```text
GET /api/v1/catalog?data_type=STD&page=1&size=20&q=...
GET /api/v1/catalog/{data_type}/{list_id}
GET /api/v1/catalog/{data_type}/{list_id}/sources?page=1&size=20
GET /api/v1/catalog/{data_type}/{list_id}/resources?page=1&size=20
GET /api/v1/catalog/{data_type}/{list_id}/resources/{resource_id}/raw
```

- [x] Write route/service tests for four types sharing numeric IDs, type filters, deterministic pagination, empty catalogs, missing records, and raw-resource ownership.
- [x] Add `PortalCatalog` document with collection status, metadata, format, timestamps and GridFS reference; register it with Beanie.
- [x] List compact catalog records without decompressing every detail. Detail reads reconstruct the complete parsed JSON from GridFS.
- [x] Paginate original source rows and resource metadata; raw downloads validate catalog membership and use attachment headers.
- [x] Missing catalog/resource returns 404; malformed stored payload returns a controlled 503; invalid type/page parameters return 422.
- [x] Include schema version and format in new canonical writes; default missing fields on old records.

## 3. Integration and documentation

Files: API `tests/`, `tests/requirements.txt`, API and collector documentation.

- [x] Install only API test dependencies into an isolated virtual environment.
- [x] Run the collector through real MongoStore against a disposable MongoDB, then read those documents through the real API models/routes.
- [x] Verify old-format rows and new rows, legacy fields, raw-detail reconstruction, unchanged AI state, and absent optional fields.
- [x] Run the full collector suite, focused API suite, formatting and diff checks.
- [x] Document endpoints, schema compatibility, test commands and validation limits. Remove the disposable DB container.

Test commands (Mongo integration uses an explicitly supplied disposable instance):

```bash
uv run --project services/opendata-collector --frozen pytest
PYTHONPATH=services/opendata-api/src:services/opendata-collector/src \
  /tmp/opendata-api-schema-venv/bin/python -m pytest services/opendata-api/tests
```
