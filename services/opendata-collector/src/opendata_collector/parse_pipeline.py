"""Orchestrate deterministic parsing of records already stored in MongoDB."""

from __future__ import annotations

from .parse_normalizers import normalize_catalog
from .parse_store import PARSED_COLLECTIONS, ParseStore


class ParsePipeline:
    def __init__(self, store: ParseStore):
        self.store = store

    def run(self, types, limit=None, force=False):
        selected_types = list(dict.fromkeys(types))
        invalid = [kind for kind in selected_types if kind not in PARSED_COLLECTIONS]
        if invalid:
            raise ValueError(f"Unsupported parse type: {invalid[0]}")
        self.store.initialize()
        report = {
            "status": "completed",
            "selected": 0,
            "parsed": 0,
            "partial": 0,
            "skipped": 0,
            "failed": 0,
            "types": {
                kind: {
                    "selected": 0,
                    "parsed": 0,
                    "partial": 0,
                    "skipped": 0,
                    "failed": 0,
                }
                for kind in selected_types
            },
        }
        for parse_input in self.store.inputs(selected_types, limit):
            kind = parse_input.catalog["data_type"]
            report["selected"] += 1
            report["types"][kind]["selected"] += 1
            if not force and self.store.is_current(parse_input):
                report["skipped"] += 1
                report["types"][kind]["skipped"] += 1
                current_status = parse_input.catalog.get("parse_status")
                if current_status in {"partial", "failed"}:
                    report[current_status] += 1
                    report["types"][kind][current_status] += 1
                continue
            try:
                output = normalize_catalog(parse_input)
            except Exception as error:
                self.store.fail(parse_input, error)
                report["failed"] += 1
                report["types"][kind]["failed"] += 1
                continue
            self.store.save(output)
            report["parsed"] += 1
            report["types"][kind]["parsed"] += 1
            if output.document["parse_status"] == "partial":
                report["partial"] += 1
                report["types"][kind]["partial"] += 1
        if report["failed"] or report["partial"]:
            report["status"] = "incomplete"
        return report
