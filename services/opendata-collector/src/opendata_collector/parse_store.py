"""MongoDB reads and revision-aware writes for the deterministic parse stage."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

import gridfs

from .parse_normalizers import PARSER_VERSION, ParsedOutput, ParseInput

PARSED_COLLECTIONS = {
    "API": "parsed_api_info",
    "FILE": "parsed_file_info",
    "STD": "parsed_std_info",
    "LINKED": "parsed_linked_info",
}
LEGACY_COLLECTIONS = {"API": "open_data_info", "FILE": "open_file_info"}

CATALOG_FINGERPRINT_FIELDS = (
    "_id",
    "data_type",
    "list_id",
    "title",
    "detail_url",
    "summary",
    "metadata",
    "data_format",
    "parsed_detail_ref",
    "detail_format",
    "detail_status",
    "detail_errors",
    "api_spec_count",
    "attachment_count",
    "is_active",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def source_fingerprint(
    catalog: dict[str, Any],
    source_records: list[dict[str, Any]],
    resources: list[dict[str, Any]],
) -> str:
    """Hash only stable source values so run timestamps never trigger reparsing."""
    payload = {
        "parser_version": PARSER_VERSION,
        "catalog": {key: catalog.get(key) for key in CATALOG_FINGERPRINT_FIELDS},
        "source_records": [
            {
                "_id": value.get("_id"),
                "source": value.get("source"),
                "data_type": value.get("data_type"),
                "record": value.get("record", {}),
                "snapshot_run_id": value.get("snapshot_run_id"),
                "snapshot_source": value.get("snapshot_source"),
                "snapshot_raw_sha256": value.get("snapshot_raw_sha256"),
            }
            for value in source_records
        ],
        "resources": [
            {
                "_id": value.get("_id"),
                "kind": value.get("kind"),
                "url": value.get("url"),
                "raw_id": value.get("raw_id"),
                "content_type": value.get("content_type"),
            }
            for value in resources
        ],
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


class ParseStore:
    def __init__(self, database):
        self.db = database
        self.raw = gridfs.GridFS(database, collection="portal_raw")

    def initialize(self) -> None:
        self.db.portal_catalog.create_index([("data_type", 1), ("list_id", 1)], unique=True)
        for collection in PARSED_COLLECTIONS.values():
            self.db[collection].create_index("list_id")
            self.db[collection].create_index("source_catalog_id")
        self.db.parsed_std_members.create_index("source_catalog_id")
        self.db.parsed_std_members.create_index([("list_id", 1), ("is_active", 1)])

    def _load_raw(self, raw_id: Any) -> bytes:
        return gzip.decompress(self.raw.get(raw_id).read())

    def inputs(self, types: Iterable[str], limit: int | None = None):
        selected_types = list(dict.fromkeys(types))
        query = {
            "data_type": {"$in": selected_types},
            "detail_status": {"$in": ["completed", "partial", "failed"]},
            "is_active": {"$ne": False},
        }
        cursor = self.db.portal_catalog.find(query).sort([("data_type", 1), ("list_id", 1)])
        if limit is not None:
            cursor = cursor.limit(limit)
        snapshot_run = self.db.portal_snapshot_runs.find_one(
            {"status": "completed"}, sort=[("completed_at", -1), ("_id", -1)]
        )
        for catalog in cursor:
            source_records = list(
                self.db.portal_source_records.find(
                    {"catalog_id": catalog["_id"], "is_active": {"$ne": False}}
                ).sort("_id", 1)
            )
            stored_resources = list(
                self.db.portal_resources.find(
                    {"catalog_id": catalog["_id"], "is_active": {"$ne": False}}
                ).sort("_id", 1)
            )
            if snapshot_run is not None:
                snapshot = self.db.portal_snapshot_records.find_one(
                    {"run_id": snapshot_run["_id"], "catalog_id": catalog["_id"]}
                )
                raw_record = snapshot.get("source_record") if snapshot else None
                if isinstance(raw_record, dict):
                    source_records.append(
                        {
                            "_id": snapshot.get("_id"),
                            "source": "monthly_snapshot",
                            "data_type": snapshot.get("data_type"),
                            "record": dict(raw_record),
                            "snapshot_run_id": snapshot_run["_id"],
                            "snapshot_source": snapshot_run.get("source"),
                            "snapshot_raw_sha256": snapshot_run.get("raw_sha256"),
                        }
                    )
            errors = []
            detail: dict[str, Any] = {}
            detail_ref = catalog.get("parsed_detail_ref")
            if not detail_ref and catalog.get("detail_status") == "completed":
                errors.append({"error": "Completed catalog has no detail payload"})
            if detail_ref:
                try:
                    loaded = json.loads(self._load_raw(detail_ref))
                    if isinstance(loaded, dict):
                        detail = loaded
                    else:
                        errors.append({"error": "Collected detail is not a JSON object"})
                except (gridfs.errors.NoFile, gzip.BadGzipFile, json.JSONDecodeError, OSError):
                    errors.append({"error": "Cannot load collected detail payload"})

            resources = []
            for resource in stored_resources:
                value = dict(resource)
                needs_payload = catalog["data_type"] == "LINKED" and resource.get("kind") == "dcat"
                if needs_payload:
                    try:
                        value["content"] = self._load_raw(resource["raw_id"])
                    except (KeyError, gridfs.errors.NoFile, gzip.BadGzipFile, OSError):
                        errors.append(
                            {
                                "kind": resource.get("kind"),
                                "error": "Cannot load resource payload",
                            }
                        )
                        continue
                resources.append(value)
            yield ParseInput(
                catalog=catalog,
                detail=detail,
                source_records=source_records,
                resources=resources,
                source_fingerprint=source_fingerprint(catalog, source_records, stored_resources),
                input_errors=errors,
            )

    def is_current(self, parse_input: ParseInput) -> bool:
        collection = PARSED_COLLECTIONS[parse_input.catalog["data_type"]]
        rows = list(
            self.db[collection].find(
                {"list_id": parse_input.catalog["list_id"]},
                {"source_fingerprint": 1, "parser_version": 1},
            )
        )
        return (
            len(rows) == 1
            and rows[0].get("source_fingerprint") == parse_input.source_fingerprint
            and rows[0].get("parser_version") == PARSER_VERSION
        )

    def _upsert_parsed(self, output: ParsedOutput) -> None:
        collection = self.db[output.collection]
        list_id = output.document["list_id"]
        existing = list(collection.find({"list_id": list_id}).sort("parsed_at", -1))
        if existing:
            selected_id = existing[0]["_id"]
            collection.update_one({"_id": selected_id}, {"$set": output.document})
            collection.delete_many({"list_id": list_id, "_id": {"$ne": selected_id}})
        else:
            collection.update_one(
                {"list_id": list_id},
                {
                    "$set": output.document,
                    "$setOnInsert": {"_id": output.document["source_catalog_id"]},
                },
                upsert=True,
            )

    def _save_standard_members(self, output: ParsedOutput) -> None:
        catalog_id = output.document["source_catalog_id"]
        active_ids = [member["_id"] for member in output.members]
        if output.document["parse_status"] == "completed":
            self.db.parsed_std_members.update_many(
                {
                    "source_catalog_id": catalog_id,
                    "_id": {"$nin": active_ids},
                    "is_active": {"$ne": False},
                },
                {"$set": {"is_active": False, "removed_at": _now()}},
            )
        for member in output.members:
            member_id = member["_id"]
            fields = {key: value for key, value in member.items() if key != "_id"}
            existing = self.db.parsed_std_members.find_one({"_id": member_id}, {"_id": 1})
            if existing and member.get("detail_status") != "completed":
                for detail_field in ("metadata", "columns", "distributions"):
                    fields.pop(detail_field, None)
            self.db.parsed_std_members.update_one(
                {"_id": member_id},
                {"$set": fields, "$unset": {"removed_at": ""}},
                upsert=True,
            )

    def _set_legacy_status(self, document: dict[str, Any], status: str) -> None:
        kind = document["data_type"]
        collection = LEGACY_COLLECTIONS.get(kind)
        if not collection:
            return
        self.db[collection].update_one(
            {"list_id": document["list_id"]},
            {
                "$set": {
                    "is_parsed": "Y" if status == "completed" else "ERROR",
                    "parsed_at": document["parsed_at"],
                    "source_catalog_id": document["source_catalog_id"],
                },
            },
            upsert=False,
        )

    def save(self, output: ParsedOutput) -> None:
        document = output.document
        if output.collection == "parsed_std_info":
            self._save_standard_members(output)
        self._set_legacy_status(document, document["parse_status"])
        self.db.portal_catalog.update_one(
            {"_id": document["source_catalog_id"]},
            {
                "$set": {
                    "parse_status": document["parse_status"],
                    "parse_errors": document["parse_errors"],
                    "parsed_at": document["parsed_at"],
                    "parser_version": document["parser_version"],
                    "source_fingerprint": document["source_fingerprint"],
                }
            },
        )
        self._upsert_parsed(output)

    def fail(self, parse_input: ParseInput, error: Exception) -> None:
        parsed_at = _now()
        message = str(error).strip()[:500] or error.__class__.__name__
        fields = {
            "parse_status": "failed",
            "parse_errors": [{"error": message}],
            "parsed_at": parsed_at,
            "parser_version": PARSER_VERSION,
            "source_fingerprint": parse_input.source_fingerprint,
        }
        self.db.portal_catalog.update_one({"_id": parse_input.catalog["_id"]}, {"$set": fields})
        legacy = LEGACY_COLLECTIONS.get(parse_input.catalog["data_type"])
        if legacy:
            self.db[legacy].update_one(
                {"list_id": parse_input.catalog["list_id"]},
                {
                    "$set": {
                        "is_parsed": "ERROR",
                        "parsed_at": parsed_at,
                        "source_catalog_id": parse_input.catalog["_id"],
                    },
                },
                upsert=False,
            )
