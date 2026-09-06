"""Checkpointed listing discovery followed by detail enrichment."""

import logging
import uuid

from .http import FetchError
from .sources import TYPES

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, source, store, details):
        self.source, self.store, self.details = source, store, details

    def run(self, *, types=None, page_size=100, resume=None, max_pages=None, max_details=None):
        if any(limit is not None and limit < 1 for limit in (max_pages, max_details)):
            raise ValueError("Execution limits must be positive")
        kinds = list(dict.fromkeys(types or TYPES))
        if not kinds or any(kind not in TYPES for kind in kinds) or not 1 <= page_size <= 1000:
            raise ValueError("Invalid catalog types or page size")
        owner = str(uuid.uuid4())
        self.store.initialize()
        self.store.acquire(owner)
        try:
            run = (
                self.store.get_run(resume)
                if resume
                else self.store.start_run(self.source.mode, kinds, page_size)
            )
            if resume and run.get("status") == "completed":
                raise ValueError("Completed run cannot be resumed; start a new collection run")
            if resume and self.store.has_newer_overlapping_run(run):
                raise ValueError(
                    "Run was superseded by a newer overlapping run; start a new collection run"
                )
            if run["source"] != self.source.mode:
                raise ValueError("Resume must use the original source mode (and API key if needed)")
            run_id = run["_id"]
            logger.info("Collection run %s; source=%s", run_id, run["source"])
            processed_pages, limited = 0, False
            for kind in run["types"]:
                state = run["streams"][kind]
                while not state["complete"]:
                    if max_pages is not None and processed_pages >= max_pages:
                        limited = True
                        break
                    self.store.heartbeat()
                    number = state["next_page"]
                    try:
                        page, raw = self.source.page(kind, number, run["page_size"])
                        repeated = self.store.save_page(run_id, kind, page, raw)
                    except (ValueError, FetchError) as error:
                        self.store.set_stream(run_id, kind, error=str(error))
                        logger.warning("Listing failed: %s page %d: %s", kind, number, error)
                        break
                    initial_total = state["expected_total"]
                    changed = initial_total is not None and initial_total != page["total"]
                    state.update(
                        {
                            "expected_total": page["total"]
                            if initial_total is None
                            else initial_total,
                            "last_reported_total": page["total"],
                            "member_total": page.get("member_total"),
                            "count_changed": state["count_changed"] or changed,
                            "duplicate_records": state["duplicate_records"] or repeated,
                            "next_page": number + 1,
                            "complete": number * run["page_size"] >= page["total"],
                            "error": None,
                        }
                    )
                    # Advance only after every row and raw response have been acknowledged by Mongo.
                    self.store.set_stream(run_id, kind, **state)
                    processed_pages += 1
                    logger.info(
                        "%s page %d: %d records / expected %d",
                        kind,
                        number,
                        len(page["items"]),
                        page["total"],
                    )
                    if changed:
                        # A changed total invalidates the current page boundary immediately.
                        break
                    # Cross-page duplicates keep the run unverifiable, but later pages may
                    # still contain new records worth preserving in an incomplete snapshot.
            processed_details = 0
            for job in self.store.pending(run_id):
                if max_details is not None and processed_details >= max_details:
                    limited = True
                    break
                self.store.heartbeat()
                item = job["item"]
                try:
                    detail, resources, errors = self.details.collect(item, self.store.heartbeat)
                    self.store.save_detail(run_id, item, detail, resources, errors)
                except (ValueError, FetchError) as error:
                    self.store.fail_detail(run_id, item, str(error))
                    logger.warning("Detail failed: %s: %s", item["catalog_id"], error)
                processed_details += 1
            pending = self.store.db.portal_run_items.count_documents(
                {
                    "run_id": run_id,
                    "status": {"$ne": "completed"},
                }
            )
            if not limited and pending == 0:
                self.verify_listing(run_id)
            report = self.store.report(run_id, limited=limited)
            if report["status"] == "completed":
                self.store.finalize_snapshot(run_id)
            return self.store.report(run_id, limited=limited, persist=True)
        finally:
            self.store.release(owner)

    def verify_listing(self, run_id):
        """Re-read every listing page so equal-count replacements are not hidden.

        The provider offers no snapshot token: this is a stability check, not a
        claim of a transactional remote snapshot. Every resumed completion gets
        a fresh pass; interrupted validation can safely start over.
        """
        run = self.store.get_run(run_id)
        for kind, state in run["streams"].items():
            if (
                not state["complete"]
                or state["count_changed"]
                or state["duplicate_records"]
                or state.get("snapshot_changed")
            ):
                continue
            self.store.set_stream(run_id, kind, verified=False)
            try:
                for number in range(1, state["next_page"]):
                    self.store.heartbeat()
                    page, raw = self.source.page(kind, number, run["page_size"])
                    matches = self.store.verify_page(run_id, kind, page, raw)
                    if page["total"] != state["expected_total"] or not matches:
                        self.store.set_stream(
                            run_id,
                            kind,
                            snapshot_changed=True,
                            error="Listing membership changed during verification",
                        )
                        break
                    logger.info("Verified %s listing page %d", kind, number)
                else:
                    self.store.set_stream(run_id, kind, verified=True, error=None)
            except (ValueError, FetchError) as error:
                self.store.set_stream(run_id, kind, error=str(error))
