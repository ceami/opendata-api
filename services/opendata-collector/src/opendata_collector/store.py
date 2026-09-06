"""Idempotent Mongo persistence and content-addressed raw-response storage."""

import gzip
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

import gridfs
from pymongo import ReturnDocument
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
