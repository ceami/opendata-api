# Portal Collector Implementation Plan

> **For agentic workers:** Use the independent parser/projection subtasks and root integration, reviewing each change before final verification.

**Goal:** Collect and persist public data.go.kr catalog metadata before AI processing.

**Architecture:** Standalone synchronous CLI with authenticated official catalog source and public HTML fallback. Raw resources, source rows, catalog records, and resumable run membership are persisted separately in MongoDB.

**Tech Stack:** Python >=3.10, httpx, Beautiful Soup, PyMongo, pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-portal-collector-design.md`.

## Global constraints

- Preserve existing unrelated working-tree edits and AI processing state.
- FILE/API/STD/LINKED; retain multiple official source rows per catalog ID.
- Never report complete if pagination, counts, details, or configured execution limits leave a gap.
- No execution of arbitrary JavaScript, business APIs, or usage-count mutations.

## Tasks

1. Parser agent: test real listing/detail fixtures, then implement `parse_listing`, `parse_detail`, `parse_standard_members`. STD group totals must use `300` in `300개 (12,692건)`.
2. Projection agent: test source-to-existing-model conversions, missing flags, and excluded AI fields; implement `project_legacy(item, detail, collected_at, source_record=None)`.
3. Root: write HTTP/source tests first, implement bounded safe GET requests and strict official envelope parsing. Check `currentCount == len(data)`, echoed page, unique source IDs, raw field preservation.
4. Root: test and implement Mongo persistence, run memberships, content-addressed raw resources, checkpoint/retry semantics and incomplete-run summaries. Verify two types with identical numeric IDs remain distinct.
5. Root: add CLI/configuration, isolated Docker execution example, operator README, runnable preview/status/collect commands. Run all unit tests, lint, a small live preview, and real isolated Mongo smoke if available.

## Verification commands

```bash
cd services/opendata-collector
uv sync --group dev
uv run pytest
uv run ruff check .
uv run opendata-collect preview --types FILE API STD LINKED --limit 1 --output /tmp/portal-preview.jsonl
```
