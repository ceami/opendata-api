"""Idempotent Mongo persistence and content-addressed raw-response storage."""

import gzip
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

import gridfs
from pymongo import ReturnDocument, UpdateOne
from pymongo.errors import DuplicateKeyError


def now():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def resource_digest(catalog_id, resource, raw_id):
    return digest(f"{catalog_id}\n{resource.kind}\n{resource.url}\n{raw_id}")


class MongoStore:
    def __init__(self, database):
        self.db = database
        self.raw = gridfs.GridFS(database, collection="portal_raw")
        self.owner = None

    def initialize(self):
        self.db.portal_catalog.create_index([("data_type", 1), ("list_id", 1)], unique=True)
        self.db.portal_source_records.create_index("catalog_id")
        self.db.portal_run_items.create_index([("run_id", 1), ("status", 1)])
        self.db.portal_run_records.create_index([("run_id", 1), ("data_type", 1)])
        self.db.portal_resources.create_index([("catalog_id", 1), ("kind", 1)])
        self.db.portal_runs.create_index("started_at")

    def acquire(self, owner):
        instant = now()
        try:
            lease = self.db.portal_locks.find_one_and_update(
                {"_id": "collector", "$or": [{"expires_at": {"$lte": instant}}, {"owner": owner}]},
                {"$set": {"owner": owner, "expires_at": instant + timedelta(minutes=10)}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            raise RuntimeError(
                "Database is locked by another collector; retry after its lease expires"
            ) from None
        if not lease or lease["owner"] != owner:
            raise RuntimeError("Database is locked by another collector")
        self.owner = owner

    def heartbeat(self):
        if self.owner:
            result = self.db.portal_locks.update_one(
                {"_id": "collector", "owner": self.owner},
                {"$set": {"expires_at": now() + timedelta(minutes=10)}},
            )
            if result.matched_count != 1:
                raise RuntimeError("Collector database lease lost")

    def release(self, owner):
        self.db.portal_locks.delete_one({"_id": "collector", "owner": owner})
        if self.owner == owner:
            self.owner = None

    def start_run(self, source, types, page_size):
        run_id = str(uuid.uuid4())
        run = {
            "_id": run_id,
            "source": source,
            "types": list(types),
            "page_size": page_size,
            "started_at": now(),
            "updated_at": now(),
            "status": "running",
            "streams": {
                kind: {
                    "next_page": 1,
                    "expected_total": None,
                    "complete": False,
                    "count_changed": False,
                    "duplicate_records": False,
                    "snapshot_changed": False,
                    "verified": False,
                    "error": None,
                }
                for kind in types
            },
        }
        self.db.portal_runs.insert_one(run)
        return run

    def get_run(self, run_id):
        run = self.db.portal_runs.find_one({"_id": run_id})
        if run is None:
            raise ValueError("Unknown collection run ID")
        return run

    def has_newer_overlapping_run(self, run):
        return (
            self.db.portal_runs.find_one(
                {
                    "_id": {"$ne": run["_id"]},
                    "started_at": {"$gt": run["started_at"]},
                    "types": {"$in": run["types"]},
                },
                {"_id": 1},
            )
            is not None
        )

    def set_stream(self, run_id, kind, **fields):
        self.db.portal_runs.update_one(
            {"_id": run_id},
            {
                "$set": {
                    **{f"streams.{kind}.{key}": value for key, value in fields.items()},
                    "updated_at": now(),
                }
            },
        )

    def save_raw(self, content):
        raw_id = hashlib.sha256(content).hexdigest()
        if not self.raw.exists(raw_id):
            try:
                self.raw.put(
                    gzip.compress(content, mtime=0),
                    _id=raw_id,
                    compression="gzip",
                    original_bytes=len(content),
                )
            except gridfs.errors.FileExists:
                pass
        return raw_id

    def save_resource(self, catalog_id, run_id, resource):
        raw_id = self.save_raw(resource.content)
        resource_id = resource_digest(catalog_id, resource, raw_id)
        self.db.portal_resources.update_one(
            {"_id": resource_id},
            {
                "$set": {
                    "catalog_id": catalog_id,
                    "last_seen_run": run_id,
                    "kind": resource.kind,
                    "url": resource.url,
                    "raw_id": raw_id,
                    "content_type": resource.content_type,
                    "fetched_at": resource.fetched_at,
                    "is_active": True,
                },
                "$unset": {"removed_at": ""},
            },
            upsert=True,
        )
        return raw_id

    def save_page(self, run_id, kind, page, raw):
        raw_id = self.save_resource(f"listing:{kind}:{page['page']}", run_id, raw)
        repeated = False
        for item in page["items"]:
            source_id, catalog_id = item["source_id"], item["catalog_id"]
            member_id = digest(run_id + "\n" + source_id)
            previous = self.db.portal_run_records.find_one({"_id": member_id})
            if previous and previous["first_page"] != page["page"]:
                repeated = True
            self.db.portal_run_records.update_one(
                {"_id": member_id},
                {
                    "$setOnInsert": {
                        "run_id": run_id,
                        "data_type": kind,
                        "source_id": source_id,
                        "first_page": page["page"],
                        "catalog_id": catalog_id,
                    }
                },
                upsert=True,
            )
            self.db.portal_source_records.update_one(
                {"_id": source_id},
                {
                    "$set": {
                        "catalog_id": catalog_id,
                        "data_type": kind,
                        "source": page["source"],
                        "record": item["source_record"],
                        "collected_at": raw.fetched_at,
                        "last_seen_run": run_id,
                        "is_active": True,
                    },
                    "$unset": {"removed_at": ""},
                },
                upsert=True,
            )
            summary = {
                key: item[key] for key in ("list_id", "data_type", "detail_url", "title", "summary")
            }
            self.db.portal_catalog.update_one(
                {"_id": catalog_id},
                {
                    "$set": {
                        **summary,
                        "schema_version": 2,
                        "last_seen_at": raw.fetched_at,
                        "last_seen_run": run_id,
                        "representative_source_id": source_id,
                        "is_active": True,
                    },
                    "$unset": {"removed_at": ""},
                    "$setOnInsert": {"first_seen_at": raw.fetched_at, "detail_status": "pending"},
                },
                upsert=True,
            )
            self.db.portal_run_items.update_one(
                {"_id": digest(run_id + "\n" + catalog_id)},
                {
                    "$set": {"item": item},
                    "$setOnInsert": {
                        "run_id": run_id,
                        "catalog_id": catalog_id,
                        "status": "pending",
                        "attempts": 0,
                    },
                },
                upsert=True,
            )
        page_id = f"{run_id}:{kind}:{page['page']}"
        self.db.portal_pages.update_one(
            {"_id": page_id},
            {
                "$set": {
                    "run_id": run_id,
                    "data_type": kind,
                    "page": page["page"],
                    "record_count": len(page["items"]),
                    "membership_digest": self.membership_digest(page),
                    "raw_id": raw_id,
                    "collected_at": raw.fetched_at,
                }
            },
            upsert=True,
        )
        return repeated

    def pending(self, run_id):
        return self.db.portal_run_items.find({"run_id": run_id, "status": {"$ne": "completed"}})

    def save_detail(self, run_id, item, detail, resources, errors):
        current_resource_ids = []
        for resource in resources:
            raw_id = self.save_resource(item["catalog_id"], run_id, resource)
            current_resource_ids.append(resource_digest(item["catalog_id"], resource, raw_id))
        serialized = json.dumps(detail, ensure_ascii=False, default=str).encode()
        detail_ref = self.save_raw(serialized)
        status = "partial" if errors else "completed"
        from .projection import project_legacy

        collected_at = now()
        projection = project_legacy(item, detail, collected_at, item.get("source_record"))
        data_format = projection[1].get("data_format") if projection else None
        self.db.portal_catalog.update_one(
            {"_id": item["catalog_id"]},
            {
                "$set": {
                    "schema_version": 2,
                    "metadata": detail.get("metadata", {}),
                    "data_format": data_format,
                    "parsed_detail_ref": detail_ref,
                    "detail_format": detail.get("detail_format"),
                    "detail_status": status,
                    "detail_collected_at": collected_at,
                    "api_spec_count": len(detail.get("api_specs", [])),
                    "attachment_count": len(detail.get("attachments", [])),
                    "detail_errors": errors,
                }
            },
        )
        if not errors:
            self.db.portal_resources.update_many(
                {
                    "catalog_id": item["catalog_id"],
                    "_id": {"$nin": current_resource_ids},
                    "kind": {"$ne": "reference_document"},
                    "is_active": {"$ne": False},
                },
                {"$set": {"is_active": False, "removed_at": collected_at}},
            )
            if projection is not None:
                collection, fields = projection
                # Never replace documents or reset AI results when refreshing source metadata.
                self.db[collection].update_one(
                    {"list_id": item["list_id"]},
                    {
                        "$set": {**fields, "source_catalog_id": item["catalog_id"]},
                        "$setOnInsert": {"_id": item["catalog_id"]},
                    },
                    upsert=True,
                )
        self.db.portal_run_items.update_one(
            {"_id": digest(run_id + "\n" + item["catalog_id"])},
            {
                "$set": {
                    "status": "failed" if errors else "completed",
                    "errors": errors,
                    "updated_at": now(),
                },
                "$inc": {"attempts": 1},
            },
        )

    def fail_detail(self, run_id, item, error):
        failed_at = now()
        errors = [{"error": error}]
        self.db.portal_catalog.update_one(
            {"_id": item["catalog_id"]},
            {
                "$set": {
                    "detail_status": "failed",
                    "detail_errors": errors,
                    "detail_collected_at": failed_at,
                }
            },
        )
        self.db.portal_run_items.update_one(
            {"_id": digest(run_id + "\n" + item["catalog_id"])},
            {
                "$set": {"status": "failed", "errors": errors, "updated_at": failed_at},
                "$inc": {"attempts": 1},
            },
        )

    def finalize_snapshot(self, run_id):
        """Retire unseen catalogs/sources only after a verified full run."""
        run = self.get_run(run_id)
        removed_at = now()
        for kind in run["types"]:
            stale = {
                "data_type": kind,
                "last_seen_run": {"$ne": run_id},
                "is_active": {"$ne": False},
            }
            update = {"$set": {"is_active": False, "removed_at": removed_at}}
            self.db.portal_catalog.update_many(stale, update)
            self.db.portal_source_records.update_many(stale, update)

    @staticmethod
    def membership_digest(page):
        return digest(json.dumps(sorted(item["source_id"] for item in page["items"])))

    def verify_page(self, run_id, kind, page, raw):
        previous = self.db.portal_pages.find_one({"_id": f"{run_id}:{kind}:{page['page']}"})
        self.save_resource(f"verification:{kind}:{page['page']}", run_id, raw)
        return bool(previous and previous.get("membership_digest") == self.membership_digest(page))

    def report(self, run_id, *, limited=False, persist=False):
        run = self.get_run(run_id)
        streams, source_count, all_complete = {}, 0, True
        for kind, state in run["streams"].items():
            count = self.db.portal_run_records.count_documents(
                {"run_id": run_id, "data_type": kind}
            )
            streams[kind] = {**state, "unique_records": count}
            source_count += count
            all_complete &= (
                state["complete"]
                and count == state["expected_total"]
                and not state["count_changed"]
                and not state["duplicate_records"]
                and state.get("verified", False)
                and not state.get("snapshot_changed", False)
                and not state["error"]
            )
        count_by_status = {
            state: self.db.portal_run_items.count_documents({"run_id": run_id, "status": state})
            for state in ("pending", "completed", "failed")
        }
        if all_complete and not count_by_status["pending"] and not count_by_status["failed"]:
            status = "completed"
        else:
            status = "paused" if limited else "incomplete"
        report = {
            "run_id": run_id,
            "source": run["source"],
            "status": status,
            "streams": streams,
            "source_record_count": source_count,
            "catalog_count": sum(count_by_status.values()),
            **{f"detail_{key}": value for key, value in count_by_status.items()},
        }
        if persist:
            self.db.portal_runs.update_one(
                {"_id": run_id},
                {
                    "$set": {
                        "status": status,
                        "summary": report,
                        "updated_at": now(),
                    }
                },
            )
        return report


class SnapshotStore:
    """Persist immutable snapshot generations without changing live catalog authority."""

    SUPPORTED_TYPES = ("API", "FILE", "STD")
    MIN_COMPLETENESS_RATIO = 0.8

    def __init__(self, database, *, batch_size=1000):
        if batch_size < 1:
            raise ValueError("Snapshot batch size must be positive")
        self.db = database
        self.raw = gridfs.GridFS(database, collection="portal_raw")
        self.batch_size = batch_size
        self.owner = None

    def initialize(self):
        self._drop_legacy_identity_index()
        self._migrate_legacy_records()
        self.db.portal_snapshot_records.create_index(
            [("run_id", 1), ("catalog_id", 1)], unique=True
        )
        self.db.portal_snapshot_records.create_index([("run_id", 1), ("data_type", 1)])
        self.db.portal_snapshot_runs.create_index([("status", 1), ("completed_at", -1)])
        self.db.portal_snapshot_runs.create_index("raw_sha256")

    def _drop_legacy_identity_index(self):
        legacy_keys = (("data_type", 1), ("list_id", 1))
        for index in list(self.db.portal_snapshot_records.list_indexes()):
            key_items = tuple(index["key"].items())
            if index.get("unique") and key_items == legacy_keys:
                self.db.portal_snapshot_records.drop_index(index["name"])

    def _migrate_legacy_records(self):
        legacy_rows = self.db.portal_snapshot_records.find({"snapshot_run_id": {"$exists": False}})
        for legacy in legacy_rows:
            if legacy.get("run_id"):
                self.db.portal_snapshot_records.update_one(
                    {"_id": legacy["_id"], "snapshot_run_id": {"$exists": False}},
                    {"$set": {"snapshot_run_id": legacy["run_id"]}},
                )
                continue
            run_id = legacy.get("published_run") or legacy.get("last_seen_run")
            if not run_id:
                continue
            run = self.db.portal_snapshot_runs.find_one({"_id": run_id, "status": "completed"})
            if run is None:
                continue
            if "completed_at" not in run:
                completed_at = run.get("updated_at") or run.get("started_at") or now()
                self.db.portal_snapshot_runs.update_one(
                    {"_id": run_id, "completed_at": {"$exists": False}},
                    {"$set": {"completed_at": completed_at, "updated_at": now()}},
                )
            catalog_id = legacy.get("catalog_id", legacy["_id"])
            migrated = dict(legacy)
            migrated["_id"] = f"{run_id}:{catalog_id}"
            migrated["run_id"] = run_id
            migrated["snapshot_run_id"] = run_id
            migrated["catalog_id"] = catalog_id
            migrated["migrated_at"] = now()
            for field in (
                "published_run",
                "last_seen_run",
                "last_seen_at",
                "is_active",
                "removed_at",
                "removed_by_run",
            ):
                migrated.pop(field, None)
            self.db.portal_snapshot_records.update_one(
                {"_id": migrated["_id"]}, {"$setOnInsert": migrated}, upsert=True
            )
            # The copy is durable before a rerun can remove the legacy row.
            self.db.portal_snapshot_records.delete_one(
                {
                    "_id": legacy["_id"],
                    "snapshot_run_id": {"$exists": False},
                }
            )

    def acquire(self, owner):
        instant = now()
        try:
            lease = self.db.portal_snapshot_locks.find_one_and_update(
                {
                    "_id": "publisher",
                    "$or": [{"expires_at": {"$lte": instant}}, {"owner": owner}],
                },
                {"$set": {"owner": owner, "expires_at": instant + timedelta(minutes=10)}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            raise RuntimeError(
                "Snapshot publication is locked by another snapshot publisher"
            ) from None
        if not lease or lease["owner"] != owner:
            raise RuntimeError("Snapshot publication is locked by another snapshot publisher")
        self.owner = owner

    def heartbeat(self):
        if self.owner:
            result = self.db.portal_snapshot_locks.update_one(
                {"_id": "publisher", "owner": self.owner},
                {"$set": {"expires_at": now() + timedelta(minutes=10)}},
            )
            if result.matched_count != 1:
                raise RuntimeError("Snapshot publication lease lost")

    def release(self, owner):
        self.db.portal_snapshot_locks.delete_one({"_id": "publisher", "owner": owner})
        if self.owner == owner:
            self.owner = None

    def save_raw(self, content):
        raw_id = hashlib.sha256(content).hexdigest()
        if not self.raw.exists(raw_id):
            try:
                self.raw.put(
                    gzip.compress(content, mtime=0),
                    _id=raw_id,
                    compression="gzip",
                    original_bytes=len(content),
                )
            except gridfs.errors.FileExists:
                pass
        return raw_id

    @staticmethod
    def _hash_json(value):
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _batches(values, size):
        for start in range(0, len(values), size):
            yield values[start : start + size]

    def latest_completed_run(self):
        return self.db.portal_snapshot_runs.find_one(
            {"status": "completed"}, sort=[("completed_at", -1), ("_id", -1)]
        )

    def current_records(self):
        run = self.latest_completed_run()
        if run is None:
            return []
        return self.db.portal_snapshot_records.find({"snapshot_run_id": run["_id"]}).sort(
            [("data_type", 1), ("list_id", 1)]
        )

    def _generation_matches(self, run, rows):
        expected = {row["catalog_id"] for row in rows}
        actual = {
            record["catalog_id"]
            for record in self.db.portal_snapshot_records.find(
                {"snapshot_run_id": run["_id"]}, {"catalog_id": 1}
            )
        }
        return len(actual) == len(rows) and actual == expected

    def _assert_complete_enough(self, rows):
        previous = self.latest_completed_run()
        previous_count = previous["record_count"] if previous else 0
        minimum = (previous_count * 4 + 4) // 5
        if previous_count and len(rows) < minimum:
            raise ValueError(
                "Snapshot is too incomplete to replace current generation "
                f"({len(rows)} of {previous_count})"
            )

    def start_run(self, *, source, raw_id, raw_sha256, record_count):
        run = {
            "_id": str(uuid.uuid4()),
            "source": source,
            "source_hash": self._hash_json(source),
            "raw_id": raw_id,
            "raw_sha256": raw_sha256,
            "record_count": record_count,
            "started_at": now(),
            "updated_at": now(),
            "status": "running",
        }
        self.db.portal_snapshot_runs.insert_one(run)
        return run

    def _write_batch(self, operations, updates):
        try:
            self.db.portal_snapshot_records.bulk_write(operations, ordered=False)
        except TypeError as error:
            # mongomock 4.3 cannot accept PyMongo's current UpdateOne(sort=...) API.
            if not type(self.db).__module__.startswith("mongomock.") or (
                "unexpected keyword argument 'sort'" not in str(error)
            ):
                raise
            for selector, update in updates:
                self.db.portal_snapshot_records.update_one(selector, update, upsert=True)

    def _save_rows(self, rows, run_id, raw_id, raw_sha256):
        staged_at = now()
        for batch in self._batches(rows, self.batch_size):
            self.heartbeat()
            operations, updates = [], []
            for row in batch:
                selector = {"_id": f"{run_id}:{row['catalog_id']}"}
                fields = {
                    "run_id": run_id,
                    "snapshot_run_id": run_id,
                    "catalog_id": row["catalog_id"],
                    "data_type": row["data_type"],
                    "list_id": row["list_id"],
                    "title": row["title"],
                    "detail_url": row["detail_url"],
                    "source_id": row["source_id"],
                    "source_record": row["source_record"],
                    "source_hash": self._hash_json(row["source_record"]),
                    "detail_hash": hashlib.sha256(row["detail_url"].encode()).hexdigest(),
                    "raw_id": raw_id,
                    "raw_sha256": raw_sha256,
                    "staged_at": staged_at,
                }
                update = {"$setOnInsert": fields}
                updates.append((selector, update))
                operations.append(UpdateOne(selector, update, upsert=True))
            if operations:
                self._write_batch(operations, updates)

    def _fail_run(self, run, error):
        if run is not None:
            self.db.portal_snapshot_runs.update_one(
                {"_id": run["_id"], "status": "running"},
                {
                    "$set": {
                        "status": "failed",
                        "error": str(error),
                        "failed_at": now(),
                        "updated_at": now(),
                    }
                },
            )

    def persist(self, rows, *, source, raw_content):
        """Stage an immutable generation; one completed run document publishes it."""
        self.initialize()
        owner = str(uuid.uuid4())
        self.acquire(owner)
        run = None
        try:
            raw_sha256 = hashlib.sha256(raw_content).hexdigest()
            existing = self.db.portal_snapshot_runs.find_one(
                {"raw_sha256": raw_sha256, "status": "completed"},
                sort=[("completed_at", -1), ("_id", -1)],
            )
            if existing is not None and self._generation_matches(existing, rows):
                return existing["summary"]
            self._assert_complete_enough(rows)
            raw_id = self.save_raw(raw_content)
            run = self.start_run(
                source=source,
                raw_id=raw_id,
                raw_sha256=raw_sha256,
                record_count=len(rows),
            )
            self._save_rows(rows, run["_id"], raw_id, raw_sha256)
            reconciliation = self.reconciliation(run["_id"])
            report = {
                "run_id": run["_id"],
                "status": "completed",
                "source": source,
                "raw_id": raw_id,
                "raw_sha256": raw_sha256,
                "record_count": len(rows),
                "reconciliation": reconciliation,
            }
            result = self.db.portal_snapshot_runs.update_one(
                {"_id": run["_id"], "status": "running"},
                {
                    "$set": {
                        "status": "completed",
                        "summary": report,
                        "completed_at": now(),
                        "updated_at": now(),
                    }
                },
            )
            if result.matched_count != 1:
                raise RuntimeError("Snapshot run cannot be published")
            return report
        except Exception as error:
            self._fail_run(run, error)
            raise
        finally:
            self.release(owner)

    def reconciliation(self, run_id):
        candidate = {"snapshot_run_id": run_id}
        active_current = {
            "is_active": {"$ne": False},
            "data_type": {"$in": self.SUPPORTED_TYPES},
        }
        snapshot_count = self.db.portal_snapshot_records.count_documents(candidate)
        current_count = self.db.portal_catalog.count_documents(active_current)
        matched = 0
        identifiers = []
        for record in self.db.portal_snapshot_records.find(candidate, {"catalog_id": 1}):
            identifiers.append(record["catalog_id"])
            if len(identifiers) == self.batch_size:
                matched += self.db.portal_catalog.count_documents(
                    {"_id": {"$in": identifiers}, **active_current}
                )
                identifiers = []
        if identifiers:
            matched += self.db.portal_catalog.count_documents(
                {"_id": {"$in": identifiers}, **active_current}
            )
        return {
            "matched": matched,
            "snapshot_only": snapshot_count - matched,
            "current_only": current_count - matched,
        }


class ReferenceStore:
    """Persist independently refreshable official reference-document attachments."""

    SUCCESS_STATUSES = {"EXTRACTED", "TRUNCATED", "UNSUPPORTED"}

    def __init__(self, database):
        self.db = database
        self.raw = gridfs.GridFS(database, collection="portal_raw")

    def initialize(self):
        self.db.portal_reference_runs.create_index("started_at")
        self.db.portal_reference_run_items.create_index([("run_id", 1), ("status", 1)])
        self.db.portal_reference_run_items.create_index(
            [("run_id", 1), ("attachment_id", 1)], unique=True
        )
        self.db.portal_resources.create_index(
            [("catalog_id", 1), ("kind", 1), ("attachment_id", 1)]
        )

    def save_raw(self, content):
        raw_id = hashlib.sha256(content).hexdigest()
        if not self.raw.exists(raw_id):
            try:
                self.raw.put(
                    gzip.compress(content, mtime=0),
                    _id=raw_id,
                    compression="gzip",
                    original_bytes=len(content),
                )
            except gridfs.errors.FileExists:
                pass
        return raw_id

    def load_detail(self, detail_ref):
        detail = json.loads(gzip.decompress(self.raw.get(detail_ref).read()))
        if not isinstance(detail, dict):
            raise ValueError("Collected detail is not a JSON object")
        return detail

    def catalogs(self, types):
        query = {
            "data_type": {"$in": list(types)},
            "is_active": {"$ne": False},
            "detail_status": {"$in": ["completed", "partial"]},
            "parsed_detail_ref": {"$exists": True},
        }
        for catalog in self.db.portal_catalog.find(query).sort([("data_type", 1), ("list_id", 1)]):
            try:
                yield catalog, self.load_detail(catalog["parsed_detail_ref"]), None
            except (
                KeyError,
                gridfs.errors.NoFile,
                gzip.BadGzipFile,
                json.JSONDecodeError,
                OSError,
                EOFError,
                ValueError,
            ):
                yield catalog, None, "Cannot load collected detail payload"

    def start_run(self, types, limit, max_bytes, max_chars, force):
        run = {
            "_id": str(uuid.uuid4()),
            "types": list(types),
            "limit": limit,
            "max_bytes": max_bytes,
            "max_chars": max_chars,
            "force": force,
            "selection_complete": False,
            "started_at": now(),
            "updated_at": now(),
            "status": "running",
        }
        self.db.portal_reference_runs.insert_one(run)
        return run

    def get_run(self, run_id):
        run = self.db.portal_reference_runs.find_one({"_id": run_id})
        if run is None:
            raise ValueError("Unknown reference run ID")
        return run

    def selection_complete(self, run_id, complete):
        self.db.portal_reference_runs.update_one(
            {"_id": run_id}, {"$set": {"selection_complete": complete, "updated_at": now()}}
        )

    def _item_id(self, run_id, attachment_id):
        return digest(run_id + "\n" + attachment_id)

    def add_item(self, run_id, descriptor, *, force):
        existing = self.db.portal_resources.find_one(
            {
                "catalog_id": descriptor["catalog_id"],
                "kind": "reference_document",
                "attachment_id": descriptor["attachment_id"],
                "is_active": {"$ne": False},
                "extraction_status": {"$in": list(self.SUCCESS_STATUSES)},
            },
            {"_id": 1},
        )
        item = {
            "_id": self._item_id(run_id, descriptor["attachment_id"]),
            "run_id": run_id,
            "attachment_id": descriptor["attachment_id"],
            "descriptor": descriptor,
            "item_type": "document",
            "status": "pending" if force or existing is None else "skipped",
            "attempts": 0,
            "updated_at": now(),
        }
        self.db.portal_reference_run_items.update_one(
            {"_id": item["_id"]}, {"$setOnInsert": item}, upsert=True
        )

    def catalog_error(self, run_id, catalog_id, error):
        attachment_id = "catalog:" + catalog_id
        self.db.portal_reference_run_items.update_one(
            {"_id": self._item_id(run_id, attachment_id)},
            {
                "$set": {
                    "run_id": run_id,
                    "attachment_id": attachment_id,
                    "item_type": "catalog",
                    "catalog_id": catalog_id,
                    "status": "failed",
                    "errors": [{"error": error}],
                    "updated_at": now(),
                },
                "$setOnInsert": {"attempts": 0},
            },
            upsert=True,
        )

    def catalog_loaded(self, run_id, catalog_id):
        self.db.portal_reference_run_items.update_one(
            {"_id": self._item_id(run_id, "catalog:" + catalog_id)},
            {"$set": {"status": "skipped", "errors": [], "updated_at": now()}},
        )

    def pending(self, run_id):
        return self.db.portal_reference_run_items.find(
            {"run_id": run_id, "item_type": "document", "status": {"$in": ["pending", "failed"]}}
        ).sort("attachment_id", 1)

    def current_descriptor(self, descriptor):
        catalog = self.db.portal_catalog.find_one(
            {
                "_id": descriptor["catalog_id"],
                "is_active": {"$ne": False},
                "detail_status": {"$in": ["completed", "partial"]},
            }
        )
        if not catalog or not catalog.get("parsed_detail_ref"):
            return None
        try:
            detail = self.load_detail(catalog["parsed_detail_ref"])
        except (
            KeyError,
            gridfs.errors.NoFile,
            gzip.BadGzipFile,
            json.JSONDecodeError,
            OSError,
            EOFError,
            ValueError,
        ):
            return None
        from .reference_docs import select_reference_attachments

        item = {**catalog, "catalog_id": catalog["_id"]}
        return next(
            (
                value
                for value in select_reference_attachments(item, detail)
                if value["attachment_id"] == descriptor["attachment_id"]
            ),
            None,
        )

    def stale_document(self, run_id, descriptor):
        self.db.portal_reference_run_items.update_one(
            {"_id": self._item_id(run_id, descriptor["attachment_id"])},
            {"$set": {"status": "stale", "errors": [], "updated_at": now()}},
        )

    def save_document(self, run_id, descriptor, resource, extracted):
        raw_id = self.save_raw(resource.content)
        text_raw_id = self.save_raw(extracted["text"].encode("utf-8"))
        resource_id = digest(
            "\n".join((descriptor["catalog_id"], descriptor["attachment_id"], raw_id))
        )
        terminal = extracted["status"] in self.SUCCESS_STATUSES
        collected_at = now()
        fields = {
            "catalog_id": descriptor["catalog_id"],
            "kind": "reference_document",
            "attachment_id": descriptor["attachment_id"],
            "url": resource.url,
            "source": "official_attachment",
            "name": descriptor["name"],
            "format": descriptor["format"],
            "public_data_pk": descriptor["public_data_pk"],
            "public_data_detail_pk": descriptor["public_data_detail_pk"],
            "file_id": descriptor["file_id"],
            "file_detail_sn": descriptor["file_detail_sn"],
            "raw_id": raw_id,
            "document_sha256": raw_id,
            "text_raw_id": text_raw_id,
            "text_sha256": text_raw_id,
            "extraction_status": extracted["status"],
            "extraction_error": extracted["error"],
            "char_count": extracted["char_count"],
            "last_seen_run": run_id,
            "collected_at": collected_at,
            "is_active": terminal,
        }
        self.db.portal_resources.update_one(
            {"_id": resource_id}, {"$set": fields, "$unset": {"removed_at": ""}}, upsert=True
        )
        if terminal:
            self.db.portal_resources.update_many(
                {
                    "catalog_id": descriptor["catalog_id"],
                    "kind": "reference_document",
                    "attachment_id": descriptor["attachment_id"],
                    "_id": {"$ne": resource_id},
                    "is_active": {"$ne": False},
                },
                {"$set": {"is_active": False, "removed_at": collected_at}},
            )
        self.db.portal_reference_run_items.update_one(
            {"_id": self._item_id(run_id, descriptor["attachment_id"])},
            {
                "$set": {
                    "status": "completed" if terminal else "failed",
                    "resource_id": resource_id,
                    "errors": []
                    if terminal
                    else [{"error": extracted["error"] or "Reference extraction failed"}],
                    "updated_at": collected_at,
                },
                "$inc": {"attempts": 1},
            },
        )

    def fail_document(self, run_id, descriptor, error):
        self.db.portal_reference_run_items.update_one(
            {"_id": self._item_id(run_id, descriptor["attachment_id"])},
            {
                "$set": {"status": "failed", "errors": [{"error": error}], "updated_at": now()},
                "$inc": {"attempts": 1},
            },
        )

    def report(self, run_id, *, persist=False):
        run = self.get_run(run_id)
        counts = {
            state: self.db.portal_reference_run_items.count_documents(
                {"run_id": run_id, "status": state}
            )
            for state in ("pending", "completed", "skipped", "failed", "stale")
        }
        status = (
            "completed"
            if run.get("selection_complete") and not counts["pending"] and not counts["failed"]
            else "incomplete"
        )
        report = {
            "run_id": run_id,
            "status": status,
            "types": run["types"],
            "selection_complete": run.get("selection_complete", False),
            **counts,
        }
        report["selected"] = sum(counts.values())
        if persist:
            self.db.portal_reference_runs.update_one(
                {"_id": run_id},
                {"$set": {"status": status, "summary": report, "updated_at": now()}},
            )
        return report
