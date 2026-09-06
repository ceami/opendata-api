# Parsed Catalog Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Parse collected FILE, API, STD, and LINKED metadata into stable MongoDB `parsed_*` collections without calling AI services.

**Architecture:** Add a deterministic parse stage after `collect`. It reads `portal_catalog`, lossless detail JSON, source records, and active raw resources; pure normalizers produce type-specific documents; a Mongo parse store performs revision-aware upserts, records status, and collapses legacy duplicates by `list_id`.

**Tech Stack:** Python 3.10+, PyMongo/GridFS, BeautifulSoup, stdlib XML/JSON, pytest, mongomock, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-03-portal-collector-design.md`

## Global Constraints

- No LLM or AI service calls in the parse stage.
- No new HTTP requests; parse only already-collected MongoDB/GridFS data.
- Preserve `generated_*` documents.
- Support FILE, API, STD, and LINKED.
- Reparse only when the source fingerprint or parser version changes, unless forced.
- Parse partial source data into a partial result and retain explicit errors.
- Use `list_id` as the compatibility upsert key and preserve an existing MongoDB `_id`.
- Do not create a unique index on legacy parsed collections until duplicates are removed.

---

### Task 1: Pure OpenAPI endpoint parser

**Files:**
- Create: `services/opendata-collector/tests/test_parse_normalizers.py`
- Create: `services/opendata-collector/src/opendata_collector/parse_normalizers.py`

**Interfaces:**
- Produces: `parse_openapi_endpoints(spec: dict, list_id: int) -> list[dict]`

- [x] Write failing Swagger 2 and OpenAPI 3 tests covering parameters, request bodies, responses, local refs, examples, and cyclic refs.
- [x] Run the focused tests and confirm they fail because the module is missing.
- [x] Implement bounded local-reference resolution and endpoint normalization.
- [x] Run the focused tests and refactor while green.

### Task 2: Four catalog normalizers

**Files:**
- Modify: `services/opendata-collector/tests/test_parse_normalizers.py`
- Modify: `services/opendata-collector/src/opendata_collector/parse_normalizers.py`

**Interfaces:**
- Consumes: canonical catalog, detail JSON, source records, and active resource payloads.
- Produces: `normalize_catalog(parse_input: ParseInput) -> ParsedOutput`.

- [x] Add failing API tests for Swagger, operation-table, and official source-record fallbacks.
- [x] Add failing FILE tests for distributions, columns, history, and embedded API specs.
- [x] Add failing STD tests for standard columns and separately emitted member documents.
- [x] Add failing LINKED tests for schema.org, repaired DCAT, licenses, publishers, and access URLs.
- [x] Implement common metadata precedence and type dispatch.
- [x] Run all normalizer tests.

### Task 3: Revision-aware Mongo parse store

**Files:**
- Create: `services/opendata-collector/tests/test_parse_pipeline.py`
- Create: `services/opendata-collector/src/opendata_collector/parse_store.py`
- Create: `services/opendata-collector/src/opendata_collector/parse_pipeline.py`

**Interfaces:**
- Produces: `ParseStore.inputs(types, limit)`, `ParseStore.save(output)`, and `ParsePipeline.run(types, limit=None, force=False) -> dict`.

- [x] Add failing tests for GridFS detail loading and deterministic source fingerprints.
- [x] Add failing tests for unchanged skips, changed-source reparsing, forced parsing, partial results, and failed status.
- [x] Add failing test proving duplicate legacy `parsed_file_info` rows collapse to one while the selected `_id` is preserved.
- [x] Add failing test proving STD members use `parsed_std_members` and stale members become inactive.
- [x] Implement the store and pipeline with per-catalog status updates.
- [x] Run focused pipeline tests.

### Task 4: CLI integration

**Files:**
- Modify: `services/opendata-collector/tests/test_cli.py`
- Modify: `services/opendata-collector/src/opendata_collector/cli.py`

**Interfaces:**
- Produces: `opendata-collect parse --types ... [--limit N] [--force]`.

- [x] Add failing parser/dispatch/error-exit tests proving the command does not construct an HTTP client.
- [x] Implement CLI arguments and JSON report output.
- [x] Run CLI tests.

### Task 5: API schema compatibility

**Files:**
- Modify: `services/opendata-api/src/models/open_data.py`
- Modify: `services/opendata-api/src/models/__init__.py`
- Modify: `services/opendata-api/src/db/mongo.py`
- Modify: `services/opendata-api/tests/test_schema_compat.py`

**Interfaces:**
- Produces: Beanie models for `parsed_std_info`, `parsed_linked_info`, and `parsed_std_members`; existing parsed models accept parser metadata.

- [x] Add failing model-validation tests for all four parser outputs.
- [x] Add optional parser metadata fields and new models.
- [x] Register parsed models without a legacy unique-index migration.
- [x] Run API schema tests.

### Task 6: Real Mongo and documentation verification

**Files:**
- Modify: `services/opendata-collector/tests/test_mongo_integration.py`
- Modify: `services/opendata-collector/README.md`
- Modify: `services/opendata-collector/VALIDATION.md`

**Interfaces:**
- Consumes: the completed parser CLI and disposable MongoDB.
- Produces: repeatable validation instructions and recorded outcomes.

- [x] Add a real-Mongo collect-then-parse integration test.
- [x] Run collector tests in-memory and against disposable MongoDB.
- [x] Run API tests in-memory and against disposable MongoDB.
- [x] Run Ruff check/format and CLI help.
- [x] Document the collect → parse → AI boundary, collections, status fields, and retry semantics.
