from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import cast

import yaml

VALID_STATUSES = {"ok", "changed", "skipped", "failed/rescued"}


class LineLoader(yaml.SafeLoader):
    pass


def construct_mapping(
    loader: LineLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[str, Any]:
    mapping = cast(
        "dict[str, Any]",
        yaml.SafeLoader.construct_mapping(loader, node, deep=deep),
    )
    mapping["__line__"] = node.start_mark.line + 1
    return mapping


LineLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_mapping,
)


@dataclass(frozen=True)
class ExpectedTask:
    path: str
    line: int
    name: str


@dataclass(frozen=True)
class CoverageEvent:
    path: str
    line: int | None
    name: str
    status: str


@dataclass(frozen=True)
class RequiredStatus:
    path: str
    name: str
    status: str


@dataclass(frozen=True)
class CoverageConfig:
    scopes: list[str]
    required_statuses: list[RequiredStatus]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--coverage-file", action="append", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--scope", action="append", default=[])
    parser.add_argument("--require-status", action="append", default=[])
    return parser.parse_args()


def load_coverage_config(config_file: Path) -> CoverageConfig:
    raw_config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    if not isinstance(raw_config, dict):
        raise ValueError(f"{config_file} must contain a YAML mapping")

    return CoverageConfig(
        scopes=string_list(raw_config.get("scopes", []), config_file, "scopes"),
        required_statuses=required_statuses_from_config(
            raw_config.get("required_events", []),
            config_file,
        ),
    )


def string_list(value: Any, config_file: Path, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{config_file} field {field_name!r} must be a list")

    strings: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str):
            raise ValueError(
                f"{config_file} field {field_name!r} item {index} must be a string"
            )
        strings.append(item)
    return strings


def required_statuses_from_config(
    value: Any,
    config_file: Path,
) -> list[RequiredStatus]:
    if not isinstance(value, list):
        raise ValueError(f"{config_file} field 'required_events' must be a list")

    required_statuses: list[RequiredStatus] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                f"{config_file} field 'required_events' item {index} must be a mapping"
            )

        path = item.get("path")
        name = item.get("name")
        status = item.get("status")
        if not isinstance(path, str):
            raise ValueError(
                f"{config_file} field 'required_events' item {index} "
                "must define a string path"
            )
        if not isinstance(name, str):
            raise ValueError(
                f"{config_file} field 'required_events' item {index} "
                "must define a string name"
            )
        if status not in VALID_STATUSES:
            raise ValueError(
                f"{config_file} field 'required_events' item {index} "
                f"has invalid status {status!r}"
            )

        required_statuses.append(RequiredStatus(path, name, status))
    return required_statuses


def unique_ordered(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_items: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        unique_items.append(item)
    return unique_items


def expand_scope(project_root: Path, scope: str) -> list[Path]:
    scope_path = project_root / scope
    if scope_path.is_dir():
        return sorted(scope_path.glob("*.yml"))
    if scope_path.is_file():
        return [scope_path]
    raise ValueError(f"Coverage scope does not exist: {scope}")


def load_expected_tasks(project_root: Path, scopes: list[str]) -> list[ExpectedTask]:
    expected_tasks: list[ExpectedTask] = []
    for scope in scopes:
        for task_file in expand_scope(project_root, scope):
            relative_path = task_file.relative_to(project_root).as_posix()
            expected_tasks.extend(parse_task_file(task_file, relative_path))
    return expected_tasks


def parse_task_file(task_file: Path, relative_path: str) -> list[ExpectedTask]:
    documents = yaml.load_all(task_file.read_text(encoding="utf-8"), Loader=LineLoader)
    expected_tasks: list[ExpectedTask] = []
    for document in documents:
        expected_tasks.extend(iter_named_tasks(document, relative_path))
    return expected_tasks


def iter_named_tasks(document: Any, relative_path: str) -> list[ExpectedTask]:
    expected_tasks: list[ExpectedTask] = []
    if not isinstance(document, list):
        return expected_tasks

    for item in document:
        if not isinstance(item, dict):
            continue

        name = item.get("name")
        line = item.get("__line__")
        is_block_container = any(
            nested_section in item for nested_section in ("block", "rescue", "always")
        )
        if isinstance(name, str) and isinstance(line, int) and not is_block_container:
            expected_tasks.append(ExpectedTask(relative_path, line, name))

        for nested_section in ("block", "rescue", "always"):
            nested_tasks = item.get(nested_section)
            expected_tasks.extend(iter_named_tasks(nested_tasks, relative_path))

    return expected_tasks


def load_coverage_events(coverage_file: Path) -> list[CoverageEvent]:
    events: list[CoverageEvent] = []
    with coverage_file.open(encoding="utf-8") as coverage_stream:
        for line_number, line in enumerate(coverage_stream, start=1):
            if not line.strip():
                continue
            raw_event = json.loads(line)
            event = coverage_event(raw_event, coverage_file, line_number)
            events.append(event)
    return events


def coverage_event(
    raw_event: dict[str, Any],
    coverage_file: Path,
    line_number: int,
) -> CoverageEvent:
    path = raw_event.get("path")
    name = raw_event.get("name")
    status = raw_event.get("status")
    line = raw_event.get("line")

    if not isinstance(path, str):
        raise ValueError(f"{coverage_file}:{line_number} has no string path")
    if not isinstance(name, str):
        raise ValueError(f"{coverage_file}:{line_number} has no string name")
    if status not in VALID_STATUSES:
        raise ValueError(f"{coverage_file}:{line_number} has invalid status {status!r}")
    if line is not None and not isinstance(line, int):
        raise ValueError(
            f"{coverage_file}:{line_number} has invalid task line {line!r}"
        )

    return CoverageEvent(path, line, name, status)


def covered_tasks(
    expected_tasks: list[ExpectedTask],
    events: list[CoverageEvent],
) -> set[ExpectedTask]:
    events_by_position: dict[tuple[str, int], list[CoverageEvent]] = defaultdict(list)
    events_by_name: dict[tuple[str, str], list[CoverageEvent]] = defaultdict(list)

    for event in events:
        if event.line is not None:
            events_by_position[(event.path, event.line)].append(event)
        events_by_name[(event.path, event.name)].append(event)

    covered: set[ExpectedTask] = set()
    for task in expected_tasks:
        if events_by_position.get((task.path, task.line)):
            covered.add(task)
            continue
        if events_by_name.get((task.path, task.name)):
            covered.add(task)

    return covered


def events_for_expected_tasks(
    expected_tasks: list[ExpectedTask],
    events: list[CoverageEvent],
) -> dict[ExpectedTask, list[CoverageEvent]]:
    events_by_position: dict[tuple[str, int], list[CoverageEvent]] = defaultdict(list)
    events_by_name: dict[tuple[str, str], list[CoverageEvent]] = defaultdict(list)

    for event in events:
        if event.line is not None:
            events_by_position[(event.path, event.line)].append(event)
        events_by_name[(event.path, event.name)].append(event)

    task_events: dict[ExpectedTask, list[CoverageEvent]] = {}
    for task in expected_tasks:
        matched_events = events_by_position.get((task.path, task.line), [])
        if not matched_events:
            matched_events = events_by_name.get((task.path, task.name), [])
        task_events[task] = matched_events

    return task_events


def real_skipped_tasks(
    task_events: dict[ExpectedTask, list[CoverageEvent]],
) -> list[ExpectedTask]:
    return sorted(
        [
            task
            for task, matched_events in task_events.items()
            if matched_events
            and {event.status for event in matched_events} == {"skipped"}
        ],
        key=lambda task: (task.path, task.line),
    )


def task_status_counts(
    task_events: dict[ExpectedTask, list[CoverageEvent]],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for matched_events in task_events.values():
        statuses = {event.status for event in matched_events}
        if "failed/rescued" in statuses:
            counts["failed/rescued"] += 1
        elif "changed" in statuses:
            counts["changed"] += 1
        elif "ok" in statuses:
            counts["ok"] += 1
        elif statuses == {"skipped"}:
            counts["skipped"] += 1
    return dict(sorted(counts.items()))


def missing_required_statuses(
    required_statuses: list[RequiredStatus],
    events: list[CoverageEvent],
) -> list[RequiredStatus]:
    missing: list[RequiredStatus] = []
    for requirement in required_statuses:
        matched = any(
            event.path == requirement.path
            and event.name == requirement.name
            and event.status == requirement.status
            for event in events
        )
        if not matched:
            missing.append(requirement)
    return missing


def parse_required_status(requirement: str) -> RequiredStatus:
    parts = requirement.split("::", 2)
    if len(parts) != 3:
        raise ValueError(
            "Required status values must use PATH::TASK NAME::STATUS format: "
            f"{requirement}"
        )
    path, name, status = parts
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid required coverage status {status!r}")
    return RequiredStatus(path, name, status)


def format_required_status(requirement: RequiredStatus) -> str:
    return f"{requirement.path}::{requirement.name}::{requirement.status}"


def report_failures(
    missing_tasks: list[ExpectedTask],
    skipped_tasks: list[ExpectedTask],
    missing_statuses: list[RequiredStatus],
) -> None:
    if missing_tasks:
        print("Missing task coverage:", file=sys.stderr)
        for task in missing_tasks:
            print(f"- {task.path}:{task.line} {task.name}", file=sys.stderr)

    if skipped_tasks:
        print("Only-skipped task coverage:", file=sys.stderr)
        for task in skipped_tasks:
            print(f"- {task.path}:{task.line} {task.name}", file=sys.stderr)

    if missing_statuses:
        print("Missing required task status coverage:", file=sys.stderr)
        for requirement in missing_statuses:
            print(f"- {format_required_status(requirement)}", file=sys.stderr)


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    coverage_files = [coverage_file.resolve() for coverage_file in args.coverage_file]
    coverage_config = (
        load_coverage_config(args.config.resolve())
        if args.config is not None
        else CoverageConfig(scopes=[], required_statuses=[])
    )
    scopes = unique_ordered([*coverage_config.scopes, *args.scope])
    required_statuses = [
        *coverage_config.required_statuses,
        *[parse_required_status(requirement) for requirement in args.require_status],
    ]

    if not scopes:
        print(
            "At least one coverage scope is required via --scope or --config",
            file=sys.stderr,
        )
        return 2

    for coverage_file in coverage_files:
        if not coverage_file.exists():
            print(f"Coverage file does not exist: {coverage_file}", file=sys.stderr)
            return 1

    expected_tasks = load_expected_tasks(project_root, scopes)
    events = [
        event
        for coverage_file in coverage_files
        for event in load_coverage_events(coverage_file)
    ]
    task_events = events_for_expected_tasks(expected_tasks, events)
    reached_tasks = covered_tasks(expected_tasks, events)
    missing_tasks = sorted(
        set(expected_tasks) - reached_tasks,
        key=lambda task: (task.path, task.line),
    )
    skipped_tasks = real_skipped_tasks(task_events)
    missing_statuses = missing_required_statuses(required_statuses, events)

    summary = {
        "covered_task_count": len(reached_tasks),
        "coverage_files": [
            coverage_file.as_posix() for coverage_file in coverage_files
        ],
        "coverage_event_count": len(events),
        "expected_task_count": len(expected_tasks),
        "real_skipped_task_count": len(skipped_tasks),
        "real_skipped_tasks": [
            f"{task.path}:{task.line} {task.name}" for task in skipped_tasks
        ],
        "required_status_count": len(required_statuses),
        "scopes": scopes,
        "task_status_counts": task_status_counts(task_events),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    if missing_tasks or skipped_tasks or missing_statuses:
        report_failures(missing_tasks, skipped_tasks, missing_statuses)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
