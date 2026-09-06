# Task 3 report: snapshot reference enrichment

## Delivered

- `ParseStore.inputs()` resolves the latest completed `portal_snapshot_runs` document once per iterator, then loads a matching `portal_snapshot_records` row by `snapshot_run_id` and `catalog_id`.
- Running and failed snapshot generations are excluded because records are only read through the selected completed run.
- A snapshot row is appended after live source records with `source="monthly_snapshot"`, so its normalized values fill blanks without overriding live values.
- The parser fingerprint now includes snapshot run, source, raw SHA-256, and raw row data. A snapshot change therefore triggers reparsing.
- The normalizer preserves the raw source row in `monthly_snapshot`, with `snapshot_run_id`, `snapshot_source`, and `snapshot_raw_sha256` as explicit provenance fields.
- Korean monthly columns are normalized for identity/title/organization/department/category/format/dates/license/download and view counts/provision type/standard flag/spatial and temporal coverage/API service URLs. Schema and detail spatial/temporal values remain higher priority.
- `PARSER_VERSION` is now `3`.
- Shared parsed API models serialize the provenance and explicit snapshot-derived fields: `monthly_snapshot`, `snapshot_run_id`, `snapshot_source`, `snapshot_raw_sha256`, `view_count`, `provision_type`, and `is_standard_data`.

## Test-first evidence

1. Added the ParseStore test and ran it before implementation. It failed because the source list contained only the live record.
2. Added the normalizer test and ran it before implementation. It failed because blank department data did not fall back to the monthly snapshot.
3. Added the API schema compatibility test before adding the Pydantic fields. The API project test runner could not start because its virtual environment has no `pytest`.

## Validation

Passed:

```text
cd services/opendata-collector
uv run pytest tests/test_parse_pipeline.py tests/test_parse_normalizers.py -q
41 passed in 0.21s

uv run ruff check src/opendata_collector/parse_store.py src/opendata_collector/parse_normalizers.py tests/test_parse_pipeline.py tests/test_parse_normalizers.py
All checks passed!

cd services/opendata-api
../opendata-collector/.venv/bin/ruff check --select E,F,I --ignore E501 src/models/open_data.py tests/test_schema_compat.py
All checks passed!
```

Direct Pydantic validation passed with the API environment plus collector dependencies on `PYTHONPATH`. It normalized a snapshot row and verified serialized raw snapshot/provenance/view/provision values through `ParsedMetadata.model_validate(...).model_dump(mode="json")`.

API pytest limitation:

```text
cd services/opendata-api
uv run pytest tests/test_schema_compat.py::test_parsed_api_model_serializes_monthly_snapshot_provenance_and_flags -q
error: Failed to spawn: `pytest`
Caused by: No such file or directory (os error 2)

.venv/bin/python -m pytest ...
No module named pytest
```

Trying the collector pytest environment instead reached the API test configuration but failed before collection because `pytest_asyncio` is absent. Direct validation of `ParsedAPIInfo` also requires initialized Beanie collections; validating `ParsedMetadata` confirms the shared Pydantic serialization contract introduced here.

## Scope and concerns

The only pre-existing working-tree change is the untracked plan at `docs/superpowers/plans/2026-09-06-snapshot-reference-enrichment.md`; it is not part of this task. The API compatibility test is committed but should be rerun in the fully provisioned API test environment during Task 6.

## Review-fix addendum

The review found three important defects. This follow-up corrects each one.

- Snapshot rows are no longer merged into the live source record. Shared fields now select live source, then schema/detail metadata, then the normalized monthly row, then listing/catalog fallback. Regression coverage verifies title, organization, category, format, created date, and update date retain schema/detail values while blank department/license/count/flag/API URL fields use the snapshot.
- Added monthly aliases for contact name, email, and phone labels including `관리부서 전화번호`, `담당자 전화번호`, and `연락처`; API aliases cover API type, development/production confirmation, traffic, review status, and application traffic/counts. `traffic_limit` and `review_status` are explicit parsed/API model fields. The regression test verifies live contact/API values and detail contact metadata win, while blank values fall back to the monthly row.
- Snapshot record lookup now uses `{run_id, catalog_id}`, matching the immutable storage compound index. The ParseStore regression initializes `SnapshotStore` and asserts that exact compound index exists before reading the selected completed generation.

Additional validation after review fixes:

```text
cd services/opendata-collector
uv run pytest tests/test_parse_pipeline.py tests/test_parse_normalizers.py -q
42 passed in 0.19s

uv run ruff check src/opendata_collector/parse_store.py src/opendata_collector/parse_normalizers.py tests/test_parse_pipeline.py tests/test_parse_normalizers.py
All checks passed!

cd services/opendata-api
../opendata-collector/.venv/bin/ruff check --select E,F,I --ignore E501 src/models/open_data.py tests/test_schema_compat.py
All checks passed!
```

The API schema compatibility test now uses `ParsedAPIInfo.model_construct(**output.document).model_dump(mode="json")` to assert concrete parsed document fields without initialized Beanie collections. A direct command using the API virtual environment plus collector dependencies passed for contact, API type, confirmation, traffic, and review fields. API pytest remains unavailable because `services/opendata-api/.venv` does not include `pytest`; this is unchanged from the original report.
