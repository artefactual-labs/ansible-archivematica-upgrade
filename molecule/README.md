# Molecule test infrastructure

The role uses Molecule for task-level regression coverage. The default
development target is Ubuntu 24.04 using a pinned
`geerlingguy/docker-ubuntu2404-ansible` image digest. The lower-level platform
targets can still run a scenario on Ubuntu 22.04 or Rocky Linux 9 when that
coverage is needed.

The scenarios are hermetic. They create temporary Archivematica files,
service units, package metadata, database state, API responses, APT key data,
and Elasticsearch runtime data inside the container. They do not require a
live Archivematica installation, MySQL server, Elasticsearch service, Storage
Service API, Dashboard API, or access to `packages.archivematica.org`.

## Requirements

Run the commands from the repository root with Docker available to the current
user. The Makefile invokes `uv` with the required dependency groups, so the
test commands do not require a manually managed virtual environment.

Molecule runtime files, downloaded collections, and coverage JSONL files are
written under `.ansible/`.

## Platform images

The Makefile pins Molecule platform images by immutable manifest-list digest
instead of mutable `latest` tags. Direct Molecule runs also use the pinned
Ubuntu 24.04 image as their fallback when `MOLECULE_IMAGE` is unset.

| Variable | Image |
| --- | --- |
| `MOLECULE_UBUNTU_2404_IMAGE` | `geerlingguy/docker-ubuntu2404-ansible@sha256:68af87df907605679a3fd572d0eb8b13330b160a3aa89fe9d89e31a4d8ef6ca0` |
| `MOLECULE_UBUNTU_2204_IMAGE` | `geerlingguy/docker-ubuntu2204-ansible@sha256:12e0dce9f846b01ac40dc27a3fbab027644e08c5f252ef664677ba962051328f` |
| `MOLECULE_ROCKYLINUX_9_IMAGE` | `geerlingguy/docker-rockylinux9-ansible@sha256:967060db9f42dc650fddc74ea175f7aec0b0c852884645a10c95ddaea517eb10` |

To refresh a pinned image, inspect the upstream tag and update both the
Makefile default and any direct Molecule fallback that uses that image:

```sh
docker buildx imagetools inspect geerlingguy/docker-ubuntu2404-ansible:latest
```

## Main commands

Run the common task scenario on the default Ubuntu 24.04 platform:

```sh
make molecule-test
```

Show coverage from the latest common scenario run:

```sh
make molecule-coverage
```

Run all phase and migration scenarios on Ubuntu 24.04 and enforce aggregate
coverage:

```sh
make molecule-test-phases
```

Show aggregate coverage from the latest phase and migration scenario runs
without rerunning containers:

```sh
make molecule-phase-coverage
```

Run the full local validation set before submitting a change:

```sh
make molecule-test
make molecule-coverage
make molecule-test-phases
pre-commit run --all-files
git diff --check
```

For documentation-only changes, `pre-commit run --all-files` and
`git diff --check` are usually enough.

## Running one scenario

The common scenario is the default `MOLECULE_SCENARIO`:

```sh
make molecule-test
```

To run one phase or migration scenario, keep using the aggregate phase target
and override `MOLECULE_PHASE_SCENARIOS`. Set
`MOLECULE_PHASE_ENFORCE_COVERAGE=false` for subset runs because the aggregate
coverage contract expects the full scenario set. The target still provides the
shared phase coverage configuration and the per-scenario coverage output path.

```sh
make molecule-test-phases \
  MOLECULE_PHASE_SCENARIOS="phase-lifecycle-mysql" \
  MOLECULE_PHASE_ENFORCE_COVERAGE=false
```

The available phase and migration scenarios are:

| Scenario | Coverage purpose |
| --- | --- |
| `phase-lifecycle-mysql` | Main phase lifecycle with MySQL-backed Storage Service state. |
| `phase-lifecycle-sqlite` | Main phase lifecycle with SQLite-backed Storage Service state. |
| `phase-resume-checkpoints` | Checkpoint and resumability branches across public phases. |
| `phase-restore-success` | Successful rollback validation and restore behavior. |
| `phase-guardrails-negative` | Public phase guardrail failures and required confirmations. |
| `elasticsearch-readiness-cutover-negative` | Elasticsearch readiness and cutover failure branches. |
| `elasticsearch-runtime-negative` | Temporary Elasticsearch 6 runtime failure branches. |
| `elasticsearch-reindex-negative` | Remote reindex submission and polling failure branches. |
| `elasticsearch-restore-validate-cleanup-negative` | Elasticsearch restore, validate, and cleanup failure branches. |
| `elasticsearch-search-total-cap` | Regression coverage for Elasticsearch 8 capped `_search` hit totals. |

## Optional platforms

Ubuntu 24.04 is the default and is what the aggregate phase target uses. To run
a single scenario on another supported image, use the lower-level platform
target.

Common scenario examples:

```sh
make molecule-test-ubuntu2204
make molecule-test-rockylinux9
```

Phase scenario example:

```sh
make molecule-test-ubuntu2204 \
  MOLECULE_SCENARIO=phase-lifecycle-mysql \
  MOLECULE_COVERAGE_CONFIG=molecule/phase-coverage.yml \
  MOLECULE_COVERAGE_FILE=.ansible/molecule/phase-lifecycle-mysql-task-coverage.jsonl
```

The phase aggregate coverage report can consume the JSONL file produced by
that run. Use this only when the selected scenarios cover the configured
aggregate contract:

```sh
make molecule-phase-coverage \
  MOLECULE_PHASE_SCENARIOS="phase-lifecycle-mysql"
```

## Coverage model

The Molecule provisioner enables the `common_task_coverage` callback plugin
from `molecule/common/callback_plugins`. The callback records one JSONL event
for every reached task under the configured role task paths. Each event records
the task path, task line, task name, host, UUID, timestamp, and one of these
statuses:

- `ok`
- `changed`
- `skipped`
- `failed/rescued`

The verifier script at `molecule/common/scripts/verify_task_coverage.py`
parses the recorded JSONL files and the scoped task files. It fails when a
named task in scope was not reached, when a task was only skipped, or when a
required status event is missing.

Coverage contracts live with the scenarios:

- `molecule/common/coverage.yml` records and verifies `tasks/common` plus the
  migration context snippets that are exercised by common hook dispatch tests.
- `molecule/phase-coverage.yml` records and verifies `tasks/phases` plus
  `tasks/migrations/elasticsearch-6-to-8` across the aggregate phase and
  migration scenarios.

`required_events` entries in those files document intentional negative paths.
They are used when a test deliberately runs a task inside `block`/`rescue` and
the callback should prove that the failure branch was exercised.

## Fixture design

The common scenario in `molecule/common` tests shared snippets directly with
`include_role` and `tasks_from`. It uses deterministic local fixtures for
database query output, Storage Service and Dashboard API responses, filesystem
state, APT sources, and GPG key refresh behavior.

The phase and migration scenarios share the harness under
`molecule/shared/phase_coverage`. The shared `prepare.yml` builds the fixture
host, starts local HTTP fixtures, installs command fixtures ahead of the normal
`PATH`, creates service units, seeds package metadata, and builds temporary
Elasticsearch data. Each scenario imports the shared playbooks and selects one
case task file with `phase_coverage_case`.

The shared phase fixture root is `/tmp/archivematica-upgrade-phase` inside the
container. Scenario cleanup stops fixture HTTP processes and removes that
directory.

## Adding coverage

For a new common task branch:

1. Add the fixture state to `molecule/common/prepare.yml` or
   `molecule/common/vars.yml`.
2. Exercise the snippet from `molecule/common/converge.yml` with
   `include_role` and `tasks_from`.
3. Assert the result in `molecule/common/verify.yml`.
4. Update `molecule/common/coverage.yml` only when the coverage scope or an
   intentional `failed/rescued` requirement changes.

For a new phase or migration branch:

1. Add or extend a case file under `molecule/shared/phase_coverage/tasks`.
2. Add a scenario directory under `molecule/<scenario>` by copying an existing
   phase scenario wrapper.
3. Set `phase_coverage_case` in the scenario `converge.yml`.
4. Add the scenario name to `MOLECULE_PHASE_SCENARIOS` in the Makefile.
5. Update `molecule/phase-coverage.yml` only when the coverage scope or an
   intentional `failed/rescued` requirement changes.

Prefer Ansible `assert` tasks in the scenario verifier or case files. Use
`block`/`rescue` for expected failures so negative behavior is explicit and
coverage records the failure as `failed/rescued`.
