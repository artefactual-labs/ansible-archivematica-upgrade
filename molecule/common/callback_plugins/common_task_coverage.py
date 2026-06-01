from __future__ import annotations

import json
import os
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol

import yaml

DOCUMENTATION = r"""
---
name: common_task_coverage
type: aggregate
short_description: Record role task coverage for the common Molecule scenario.
description:
  - Writes JSONL task execution events for selected role task files.
options: {}
"""


class CoverageDisplay(Protocol):
    def warning(self, msg: str) -> None: ...


if TYPE_CHECKING:

    class CallbackBase:
        _display: CoverageDisplay

else:
    from ansible.plugins.callback import CallbackBase


class CoverageHost(Protocol):
    def get_name(self) -> str: ...


class CoverageTask(Protocol):
    _uuid: str

    def get_name(self) -> str: ...

    def get_path(self) -> str: ...


class CoverageResult(Protocol):
    _host: CoverageHost
    _task: CoverageTask | None

    def is_changed(self) -> bool: ...


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "aggregate"
    CALLBACK_NAME = "common_task_coverage"
    CALLBACK_NEEDS_ENABLED = True
    _display: CoverageDisplay

    def __init__(self) -> None:
        super().__init__()
        self.project_root = self._project_root()
        self.coverage_file = self._coverage_file()
        self.coverage_paths = self._coverage_paths()

    def v2_runner_on_ok(self, result: CoverageResult) -> None:
        status = "changed" if result.is_changed() else "ok"
        self._record_result(result, status)

    def v2_runner_item_on_ok(self, result: CoverageResult) -> None:
        status = "changed" if result.is_changed() else "ok"
        self._record_result(result, status)

    def v2_runner_on_skipped(self, result: CoverageResult) -> None:
        self._record_result(result, "skipped")

    def v2_runner_item_on_skipped(self, result: CoverageResult) -> None:
        self._record_result(result, "skipped")

    def v2_runner_on_failed(
        self,
        result: CoverageResult,
        ignore_errors: bool = False,
    ) -> None:
        self._record_result(result, "failed/rescued")

    def v2_runner_item_on_failed(self, result: CoverageResult) -> None:
        self._record_result(result, "failed/rescued")

    def _project_root(self) -> Path:
        configured_root = os.environ.get("ARCHIVEMATICA_UPGRADE_TASK_COVERAGE_ROOT")
        if configured_root:
            return Path(configured_root).expanduser().resolve()
        return Path(__file__).resolve().parents[3]

    def _coverage_file(self) -> Path:
        configured_file = os.environ.get("ARCHIVEMATICA_UPGRADE_TASK_COVERAGE_FILE")
        if configured_file:
            return Path(configured_file).expanduser().resolve()
        return self.project_root / ".ansible/molecule/common-task-coverage.jsonl"

    def _coverage_paths(self) -> tuple[str, ...]:
        configured_paths = os.environ.get(
            "ARCHIVEMATICA_UPGRADE_TASK_COVERAGE_PATHS",
        )
        if configured_paths:
            return self._split_coverage_paths(configured_paths)

        config_paths = self._coverage_paths_from_config()
        if config_paths:
            return config_paths

        return ("tasks/common",)

    def _split_coverage_paths(self, paths: str) -> tuple[str, ...]:
        return tuple(
            path.strip().strip("/") for path in paths.split(os.pathsep) if path.strip()
        )

    def _coverage_paths_from_config(self) -> tuple[str, ...]:
        coverage_config = self._coverage_config_file()
        if not coverage_config.exists():
            return ()

        raw_config = yaml.safe_load(coverage_config.read_text(encoding="utf-8"))
        if not isinstance(raw_config, dict):
            self._display.warning(
                f"Unable to read task coverage paths from {coverage_config}: "
                "configuration is not a mapping"
            )
            return ()

        raw_paths = raw_config.get("record_paths", [])
        if not isinstance(raw_paths, list):
            self._display.warning(
                f"Unable to read task coverage paths from {coverage_config}: "
                "record_paths is not a list"
            )
            return ()

        coverage_paths: list[str] = []
        for raw_path in raw_paths:
            if not isinstance(raw_path, str):
                self._display.warning(
                    f"Unable to read task coverage paths from {coverage_config}: "
                    "record_paths contains a non-string item"
                )
                return ()
            coverage_paths.append(raw_path.strip().strip("/"))
        return tuple(path for path in coverage_paths if path)

    def _coverage_config_file(self) -> Path:
        configured_file = os.environ.get("ARCHIVEMATICA_UPGRADE_TASK_COVERAGE_CONFIG")
        if configured_file:
            config_path = Path(configured_file).expanduser()
            if not config_path.is_absolute():
                config_path = self.project_root / config_path
            return config_path.resolve()
        return self.project_root / "molecule/common/coverage.yml"

    def _record_result(self, result: CoverageResult, status: str) -> None:
        task = result._task
        if task is None:
            return

        task_path = self._task_path(task)
        if task_path is None:
            return

        relative_path, line = task_path
        if not self._is_covered_path(relative_path):
            return

        event = {
            "host": result._host.get_name(),
            "line": line,
            "name": self._task_name(task),
            "path": relative_path,
            "status": status,
            "timestamp": datetime.now(UTC).isoformat(),
            "uuid": task._uuid,
        }
        self._write_event(event)

    def _task_path(self, task: CoverageTask) -> tuple[str, int | None] | None:
        raw_path = task.get_path()
        if not raw_path:
            return None

        path_text, line = self._split_path(raw_path)
        try:
            relative_path = Path(path_text).resolve().relative_to(self.project_root)
        except ValueError:
            return None

        return relative_path.as_posix(), line

    def _split_path(self, raw_path: str) -> tuple[str, int | None]:
        path_text, separator, line_text = raw_path.rpartition(":")
        if separator and line_text.isdigit():
            return path_text, int(line_text)
        return raw_path, None

    def _task_name(self, task: CoverageTask) -> str:
        return task.get_name().strip().rsplit(" : ", 1)[-1]

    def _is_covered_path(self, relative_path: str) -> bool:
        for coverage_path in self.coverage_paths:
            if relative_path == coverage_path:
                return True
            if relative_path.startswith(f"{coverage_path}/"):
                return True
        return False

    def _write_event(self, event: dict[str, Any]) -> None:
        try:
            self.coverage_file.parent.mkdir(parents=True, exist_ok=True)
            with self.coverage_file.open("a", encoding="utf-8") as coverage_stream:
                coverage_stream.write(json.dumps(event, sort_keys=True) + "\n")
        except OSError as exc:
            self._display.warning(f"Unable to write common task coverage: {exc}")
