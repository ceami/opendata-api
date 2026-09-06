"""Command line entry point; importing this module never starts collection."""

import argparse
import hashlib
import json
import logging
import os
import sys
from contextlib import nullcontext
from pathlib import Path

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from .details import DetailCollector
from .http import FetchError, PortalHTTP
from .parse_pipeline import ParsePipeline
from .parse_store import ParseStore
from .pipeline import Pipeline
from .snapshot import SNAPSHOT_MAX_BYTES, SnapshotPipeline, discover_snapshot_download
from .sources import TYPES, CatalogSource
from .store import MongoStore, SnapshotStore


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def parser():
    root = argparse.ArgumentParser(description="Collect public data.go.kr metadata before AI")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("collect", "preview"):
        command = commands.add_parser(name)
        command.add_argument("--source", choices=["auto", "api", "portal"], default="auto")
        command.add_argument("--types", choices=TYPES, nargs="+", default=list(TYPES))
        command.add_argument("--page-size", type=positive, default=100)
        command.add_argument("--interval", type=float, default=0.5)
        command.add_argument("--retries", type=int, default=3)
        command.add_argument("--timeout", type=positive, default=30)
        command.add_argument("--max-member-pages", type=positive)
        if name == "collect":
            command.add_argument("--resume", metavar="RUN_ID")
            command.add_argument(
                "--max-pages",
                type=positive,
                help="Stop after this many new listing pages in this invocation",
            )
            command.add_argument("--max-details", type=positive)
        else:
            command.add_argument("--limit", type=positive, default=1, help="Records per type")
            command.add_argument(
                "--output", default="-", help="JSONL path or - for stdout; no DB writes"
            )
    parse_command = commands.add_parser(
        "parse", help="Normalize collected metadata without AI or network requests"
    )
    parse_command.add_argument("--types", choices=TYPES, nargs="+", default=list(TYPES))
    parse_command.add_argument("--limit", type=positive)
    parse_command.add_argument("--force", action="store_true")
    snapshot_command = commands.add_parser(
        "snapshot", help="Persist the official monthly catalog CSV without live-catalog writes"
    )
    snapshot_command.add_argument("--file", help="Validated local CSV path for replay or recovery")
    snapshot_command.add_argument("--interval", type=float, default=0.5)
    snapshot_command.add_argument("--retries", type=int, default=3)
    snapshot_command.add_argument("--timeout", type=positive, default=30)
    snapshot_command.add_argument("--max-bytes", type=positive, default=SNAPSHOT_MAX_BYTES)
    status = commands.add_parser("status")
    status.add_argument("run_id")
    return root


def _mongo():
    client = MongoClient(
        os.environ.get("MONGO_URL", "mongodb://localhost:27017"),
        serverSelectionTimeoutMS=10000,
        tz_aware=True,
    )
    # No Beanie initialization or index changes to existing application collections.
    return client, MongoStore(client[os.environ.get("MONGO_DB", "open_data")])


def preview(source, details, args):
    destination = (
        nullcontext(sys.stdout) if args.output == "-" else open(args.output, "w", encoding="utf-8")
    )
    failed, counts = False, {}
    with destination as output:
        for kind in dict.fromkeys(args.types):
            emitted, number, seen = 0, 1, set()
            while emitted < args.limit:
                page, _ = source.page(kind, number, args.page_size)
                for item in page["items"]:
                    if item["catalog_id"] in seen:
                        continue
                    seen.add(item["catalog_id"])
                    detail, resources, errors = details.collect(item)
                    row = {
                        "item": item,
                        "detail": detail,
                        "errors": errors,
                        "resources": [
                            {
                                "url": raw.url,
                                "kind": raw.kind,
                                "bytes": len(raw.content),
                                "sha256": hashlib.sha256(raw.content).hexdigest(),
                            }
                            for raw in resources
                        ],
                    }
                    output.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                    output.flush()
                    failed |= bool(errors)
                    emitted += 1
                    if emitted >= args.limit:
                        break
                if number * args.page_size >= page["total"]:
                    break
                number += 1
            counts[kind] = emitted
    print(
        json.dumps({"preview_counts": counts, "has_errors": failed}, ensure_ascii=False),
        file=sys.stderr,
    )
    return 2 if failed else 0


def main(argv=None):
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # httpx request logging can expose arbitrary response redirect queries; suppress it.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        if args.command == "status":
            client, store = _mongo()
            with client:
                report = store.report(args.run_id)
                report["status"] = store.get_run(args.run_id)["status"]
            print(json.dumps(report, ensure_ascii=False, default=str, indent=2))
            return 0
        if args.command == "parse":
            client, mongo_store = _mongo()
            with client:
                report = ParsePipeline(ParseStore(mongo_store.db)).run(
                    types=args.types,
                    limit=args.limit,
                    force=args.force,
                )
            print(json.dumps(report, ensure_ascii=False, default=str, indent=2))
            return 0 if report["status"] == "completed" else 2
        if args.command == "snapshot":
            if args.file:
                file_path = Path(args.file)
                if file_path.stat().st_size > args.max_bytes:
                    raise ValueError("Snapshot file exceeds size limit")
                content = file_path.read_bytes()
                source = {"kind": "file", "name": file_path.name}
            else:
                with PortalHTTP(
                    interval=args.interval,
                    retries=args.retries,
                    timeout=args.timeout,
                    max_bytes=args.max_bytes,
                ) as http:
                    descriptor = discover_snapshot_download(http)
                    content = http.get(descriptor["url"], kind="snapshot_csv").content
                source = {"kind": "official", **descriptor}
            client, mongo_store = _mongo()
            with client:
                report = SnapshotPipeline(SnapshotStore(mongo_store.db)).run(content, source=source)
            print(json.dumps(report, ensure_ascii=False, default=str, indent=2))
            return 0 if report["status"] == "completed" else 2
        with PortalHTTP(
            service_key=os.environ.get("ODP_SERVICE_KEY"),
            interval=args.interval,
            retries=args.retries,
            timeout=args.timeout,
        ) as http:
            source = CatalogSource(http, mode=args.source)
            details = DetailCollector(http, max_member_pages=args.max_member_pages)
            if args.command == "preview":
                return preview(source, details, args)
            client, store = _mongo()
            with client:
                report = Pipeline(source, store, details).run(
                    types=args.types,
                    page_size=args.page_size,
                    resume=args.resume,
                    max_pages=args.max_pages,
                    max_details=args.max_details,
                )
            print(json.dumps(report, ensure_ascii=False, default=str, indent=2))
            return 0 if report["status"] == "completed" else 2
    except (ValueError, FetchError, RuntimeError) as error:
        operation = {"parse": "Parsing", "snapshot": "Snapshot"}.get(args.command, "Collection")
        print(f"{operation} failed: {error}", file=sys.stderr)
        return 1
    except PyMongoError:
        print(
            "MongoDB operation failed; verify connectivity, credentials, and the run checkpoint.",
            file=sys.stderr,
        )
        return 1
    except OSError:
        print("Cannot read or write the requested output file.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Resume using the run ID in the log.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
