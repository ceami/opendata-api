# Monthly Snapshot and Reference Document Enrichment Plan

> **For Codex:** Use superpowers:executing-plans and implement each task with a failing test first.

**Goal:** Add the official monthly data.go.kr catalog CSV as a validated reconciliation/fallback source, and collect approved API reference attachments with bounded text extraction for the later AI stage.

**Architecture:** Keep the live catalog collector authoritative. Store the latest validated monthly rows in `portal_snapshot_records`, retain each raw CSV in the existing content-addressed GridFS bucket, and append the matching normalized snapshot row as the lowest-priority parse source. Collect reference documents in a separate resumable command so ordinary metadata collection stays bounded; store document bytes and extracted text by hash in GridFS and attach their references/status to parsed attachment metadata.

**Tech Stack:** Python 3.10, httpx, BeautifulSoup, PyMongo/GridFS, pypdf, olefile, pytest, mongomock, Ruff.

---

## Task 1: Add monthly snapshot parsing and download discovery

**Files:**
- Create: `services/opendata-collector/src/opendata_collector/snapshot.py`
- Create: `services/opendata-collector/tests/test_snapshot.py`
- Modify: `services/opendata-collector/src/opendata_collector/http.py`
- Modify: `services/opendata-collector/tests/test_http.py`

1. Add failing tests for BOM/UTF-8 and CP949 CSV input, required headers, list-type and URL identity validation, duplicate IDs, normalized parser fields, and the official download descriptor response.
2. Run `uv run pytest tests/test_snapshot.py tests/test_http.py -q` and confirm the new tests fail.
3. Implement strict CSV iteration and validation. Accept the official `FILE`, `API`, `STD`, and known Korean aliases; reject unknown types or a URL whose ID/type disagrees with the row.
4. Implement the official snapshot detail-page discovery flow for data ID `15062804`: parse the attachment, POST only to `/tcs/dss/selectFileDataDownload.do`, validate the JSON, then build the `/cmm/cmm/fileDownload.do` URL.
5. Extend the HTTP allowlist only for those two read/download endpoints and enforce the existing redirect, retry, and byte limits.
6. Re-run the focused tests.

## Task 2: Persist and reconcile the monthly snapshot

**Files:**
- Modify: `services/opendata-collector/src/opendata_collector/snapshot.py`
- Modify: `services/opendata-collector/src/opendata_collector/store.py`
- Modify: `services/opendata-collector/src/opendata_collector/cli.py`
- Modify: `services/opendata-collector/tests/test_snapshot.py`
- Modify: `services/opendata-collector/tests/test_cli.py`

1. Add failing Mongo tests proving raw CSV deduplication, idempotent latest-row upserts, no retirement after invalid input, retirement only after a complete snapshot, and reconciliation counts for matched, snapshot-only, and current-only records.
2. Add failing CLI tests for `snapshot --file` and the default official download path, including configurable `--max-bytes` and machine-readable reports.
3. Implement `SnapshotStore` indexes/runs/current records. Validate the entire byte payload before publishing any row; batch writes; keep raw bytes and source/detail hashes; mark unseen rows inactive only after successful validation and persistence.
4. Implement `SnapshotPipeline` and CLI dispatch. Default to official download, permit a local CSV for replay/recovery, and never require `ODP_SERVICE_KEY`.
5. Re-run the focused tests.

## Task 3: Use the snapshot as lower-priority parsed-data enrichment

**Files:**
- Modify: `services/opendata-collector/src/opendata_collector/parse_store.py`
- Modify: `services/opendata-collector/src/opendata_collector/parse_normalizers.py`
- Modify: `services/opendata-collector/tests/test_parse_pipeline.py`
- Modify: `services/opendata-collector/tests/test_parse_normalizers.py`
- Modify: `services/opendata-api/src/models/open_data.py`
- Modify: `services/opendata-api/tests/test_schema_compat.py`

1. Add failing tests proving live/detail values win, blank fields fall back to the snapshot, all raw monthly columns and provenance remain available, and changing a snapshot row changes the parser fingerprint.
2. Load one active `portal_snapshot_records` row per catalog and append its normalized record after live source records.
3. Add snapshot fallbacks for organization/contact/category/format/dates/license/counts/spatial/temporal/API metadata and expose `monthly_snapshot` plus provenance on parsed documents.
4. Increment `PARSER_VERSION` and extend API models so the fields remain visible through Pydantic serialization.
5. Re-run collector and API focused tests.

## Task 4: Add bounded reference-document extraction

**Files:**
- Create: `services/opendata-collector/src/opendata_collector/reference_docs.py`
- Create: `services/opendata-collector/tests/test_reference_docs.py`
- Modify: `services/opendata-collector/pyproject.toml`

1. Add failing pure tests for attachment selection, URL construction, stable attachment identity, format detection, malformed archives, and text extraction from PDF, DOCX, HWPX, and compressed/uncompressed HWP paragraph streams.
2. Add `pypdf` and `olefile` runtime dependencies and refresh `uv.lock`.
3. Implement strict reference selection for registered data.go.kr PDF/DOCX/HWP/HWPX attachments. Do not follow arbitrary external links or call business API endpoints.
4. Implement best-effort extraction with explicit status/error values and a character ceiling. Preserve page/paragraph boundaries when practical.
5. Re-run the focused pure tests.

## Task 5: Persist, resume, and expose reference documents

**Files:**
- Modify: `services/opendata-collector/src/opendata_collector/reference_docs.py`
- Modify: `services/opendata-collector/src/opendata_collector/store.py`
- Modify: `services/opendata-collector/src/opendata_collector/parse_store.py`
- Modify: `services/opendata-collector/src/opendata_collector/cli.py`
- Modify: `services/opendata-collector/tests/test_reference_docs.py`
- Modify: `services/opendata-collector/tests/test_parse_pipeline.py`
- Modify: `services/opendata-collector/tests/test_cli.py`

1. Add failing Mongo/CLI tests for API-first candidate selection, per-file byte limits, descriptor-based skip/resume, force refresh, partial failures, raw/text hashes, and independent resource activation.
2. Implement `ReferenceStore`/`ReferencePipeline` with a run collection, per-document checkpoints, stable descriptor IDs, raw and extracted-text GridFS references, and safe partial completion reports.
3. Add `references --types API --limit ... --max-bytes ... --max-chars ... --force`. Default to API and a conservative per-file bound.
4. Join active reference resource metadata back onto matching `detail.attachments` in `ParseStore`; include the resource IDs, hashes, extraction status, character count, and error. Ensure reference runs never retire DCAT/OpenAPI/detail resources.
5. Re-run focused tests.

## Task 6: Documentation, full validation, and commits

**Files:**
- Modify: `services/opendata-collector/README.md`
- Modify: `services/opendata-collector/VALIDATION.md`

1. Document command order: `collect` -> `snapshot` -> `references` -> `parse` -> AI. Document collection names, provenance, limits, local replay, and expected provider-side partial failures.
2. Run `uv run ruff check .` and `uv run pytest -q` in `services/opendata-collector`.
3. Run the API test suite in `services/opendata-api` and validate representative parsed documents with the Pydantic models.
4. Review the diff for credentials, accidental production writes, unbounded downloads, and unrelated changes.
5. Commit the monthly snapshot work and reference-document work on `feat/update-collect`. Do not push unless requested.
