#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlparse

BEFORE_UPGRADE_COUNTS = {
    "aips": 3,
    "aipfiles": 6,
    "transfers": 0,
    "transferfiles": 0,
}
TRACK_TOTAL_HITS_CAP_AIPFILES = 554244


class FixtureHandler(BaseHTTPRequestHandler):
    server: FixtureServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_HEAD(self) -> None:
        route = self.route()
        index = route.index
        if route.kind == "es8" and index in BEFORE_UPGRADE_COUNTS:
            if self.has_marker("missing-index") and index == "aips":
                self.send_empty(HTTPStatus.NOT_FOUND)
                return
            self.send_empty(HTTPStatus.OK)
            return
        self.send_empty(HTTPStatus.NOT_FOUND)

    def do_GET(self) -> None:
        route = self.route()

        if route.path in {"", "/"}:
            if route.kind in {"es6", "es6-temp"}:
                version = (
                    "8.15.0" if self.has_marker("before-upgrade-not-es6") else "6.8.23"
                )
                self.send_json({"version": {"number": version}})
                return
            if route.kind == "es8":
                self.send_json({"version": {"number": "8.15.0"}})
                return
            self.send_json({"ok": True})
            return

        if route.path == "/GPG-KEY-archivematica":
            self.send_text(
                "-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
                "Version: Molecule fixture\n\n"
                "phase-coverage-archivematica-key\n"
                "-----END PGP PUBLIC KEY BLOCK-----\n"
            )
            return

        if route.path.startswith("/_cluster/health"):
            self.send_json({"status": "yellow", "timed_out": False})
            return

        if route.path == "/_snapshot/_all":
            self.send_json({"repo": {}} if self.has_marker("snapshot-repos") else {})
            return

        if route.path.startswith("/_tasks/"):
            self.handle_task_poll(route.path)
            return

        if route.path.endswith("/_count") and route.index in BEFORE_UPGRADE_COUNTS:
            if self.has_marker("missing-transfer-indices") and route.index in {
                "transfers",
                "transferfiles",
            }:
                self.send_empty(HTTPStatus.NOT_FOUND)
                return
            self.send_json({"count": self.index_count(route.kind, route.index)})
            return

        if route.path == "/api/processing-configuration/":
            payload: dict[str, Any] = {"processing_configurations": ["default"]}
            if self.has_marker("bad-dashboard-api"):
                payload = {"processing_configurations": []}
            self.send_json(payload)
            return

        if route.path == "/api/v2/pipeline/":
            total_count = 0 if self.has_marker("bad-storage-api") else 1
            self.send_json({"meta": {"total_count": total_count}})
            return

        if route.path == "/api/v2/file/":
            query = parse_qs(route.query)
            status = query.get("status", [""])[0]
            total = {"UPLOADED": 2, "DEL_REQ": 1}.get(status, 3)
            self.send_json({"meta": {"total_count": total}})
            return

        if route.path == "/api/search":
            self.send_json(
                {
                    "aaData": [],
                    "iTotalDisplayRecords": 3,
                    "iTotalRecords": 3,
                }
            )
            return

        self.send_empty(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        route = self.route()
        if route.path.endswith("/_search") and route.index in BEFORE_UPGRADE_COUNTS:
            payload = self.request_json()
            count = self.index_count(route.kind, route.index)
            hit_total = {"relation": "eq", "value": count}
            if self.should_cap_search_total(route, payload, count):
                hit_total = {"relation": "gte", "value": 10000}
            self.send_json(
                {
                    "aggregations": {"total": {"value": 0.0}},
                    "hits": {"total": hit_total},
                }
            )
            return
        if route.path == "/_reindex":
            self.handle_reindex_submit()
            return
        if route.path in {"/_refresh", "/_flush"}:
            if self.has_marker("after-upgrade-counts-match-before-upgrade"):
                self.write_json(
                    "after-upgrade-counts.json",
                    self.before_upgrade_counts(),
                )
            self.send_json({"ok": True})
            return
        self.send_empty(HTTPStatus.NOT_FOUND)

    def handle_reindex_submit(self) -> None:
        body_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(body_length).decode("utf-8")
        payload = json.loads(body or "{}")
        index = str(payload.get("source", {}).get("index", "aips"))

        if self.has_marker("submit-missing-task"):
            self.send_json({})
            return

        task_id = f"fixture:{index}"
        task_ids = self.read_json("reindex-task-ids.json", {})
        task_ids[index] = task_id
        self.write_json("reindex-task-ids.json", task_ids)

        after_upgrade_counts = self.read_json("after-upgrade-counts.json", {})
        after_upgrade_counts[index] = (
            self.before_upgrade_count(index) if index in BEFORE_UPGRADE_COUNTS else 0
        )
        self.write_json("after-upgrade-counts.json", after_upgrade_counts)

        self.send_json({"task": task_id})

    def handle_task_poll(self, path: str) -> None:
        if self.has_marker("obsolete-task"):
            self.send_empty(HTTPStatus.NOT_FOUND)
            return
        if self.has_marker("task-no-response"):
            self.send_json({"completed": True})
            return
        if self.has_marker("task-error"):
            self.send_json(
                {
                    "completed": True,
                    "error": {
                        "type": "illegal_argument_exception",
                        "reason": "fixture remote reindex task error",
                        "caused_by": {
                            "type": "content_too_long_exception",
                            "reason": "fixture response exceeded the remote reindex buffer",
                        },
                    },
                }
            )
            return

        response: dict[str, Any] = {"failures": [], "timed_out": False}
        if self.has_marker("reindex-failure"):
            response["failures"] = [{"reason": "fixture failure"}]
        if self.has_marker("reindex-timeout"):
            response["timed_out"] = True
        self.send_json({"completed": True, "response": response})

    def index_count(self, kind: str, index: str) -> int:
        if kind in {"es6", "es6-temp"}:
            return self.before_upgrade_count(index)

        after_upgrade_counts = self.read_json("after-upgrade-counts.json", {})
        if self.has_marker("after-upgrade-counts-match-before-upgrade"):
            return int(after_upgrade_counts.get(index, 0))
        if self.has_marker("after-upgrade-nonempty"):
            return 1 if index == "aips" else 0
        if self.has_marker("after-upgrade-mismatch"):
            count = int(after_upgrade_counts.get(index, 0))
            return count + (1 if count > 0 and index == "aips" else 0)

        return int(after_upgrade_counts.get(index, 0))

    def before_upgrade_counts(self) -> dict[str, int]:
        return {
            index: self.before_upgrade_count(index) for index in BEFORE_UPGRADE_COUNTS
        }

    def before_upgrade_count(self, index: str) -> int:
        if self.has_marker("es8-search-total-cap") and index == "aipfiles":
            return TRACK_TOTAL_HITS_CAP_AIPFILES
        return BEFORE_UPGRADE_COUNTS[index]

    def should_cap_search_total(
        self,
        route: FixtureRoute,
        payload: dict[str, Any],
        count: int,
    ) -> bool:
        return (
            self.has_marker("es8-search-total-cap")
            and route.kind == "es8"
            and route.index == "aipfiles"
            and count > 10000
            and payload.get("track_total_hits") is not True
        )

    def request_json(self) -> dict[str, Any]:
        body_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(body_length).decode("utf-8")
        payload = json.loads(body or "{}")
        if isinstance(payload, dict):
            return payload
        return {}

    def route(self) -> FixtureRoute:
        parsed = urlparse(self.path)
        path = parsed.path
        kind = "app"

        if self.server.server_port == 9200:
            kind = "es6"
        elif self.server.server_port == 9500:
            kind = "es6-temp"
        elif path == "/es6" or path.startswith("/es6/"):
            kind = "es6"
            path = path[4:] or "/"
        elif path == "/es8" or path.startswith("/es8/"):
            kind = "es8"
            path = path[4:] or "/"

        parts = [part for part in path.split("/") if part]
        index = parts[0] if parts else ""
        return FixtureRoute(kind=kind, path=path, query=parsed.query, index=index)

    def has_marker(self, marker: str) -> bool:
        return (self.server.fixture_root / marker).exists()

    def read_json(self, name: str, default: dict[str, Any]) -> dict[str, Any]:
        path = self.server.fixture_root / name
        if not path.exists():
            return default
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
        return default

    def write_json(self, name: str, value: dict[str, Any]) -> None:
        path = self.server.fixture_root / name
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    def send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, payload: str) -> None:
        body = payload.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()


class FixtureRoute:
    def __init__(self, kind: str, path: str, query: str, index: str) -> None:
        self.kind = kind
        self.path = path
        self.query = query
        self.index = index


class FixtureServer(ThreadingHTTPServer):
    fixture_root: Path


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: phase_fixture_http.py PORT FIXTURE_ROOT [LABEL]", file=sys.stderr)
        return 2

    port = int(sys.argv[1])
    fixture_root = Path(sys.argv[2])
    fixture_root.mkdir(parents=True, exist_ok=True)

    server = FixtureServer(("127.0.0.1", port), FixtureHandler)
    server.fixture_root = fixture_root
    os.chdir(fixture_root)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
