# Archivematica upgrade role

## Experimental status

This role is experimental. Test it carefully against representative
non-production environments and verified rollback procedures before using it
for a production upgrade.

This role contains reusable, resumable workflows for Archivematica application
upgrades. The initial workflow supports an Archivematica 1.17 to 1.18 upgrade
while preserving the existing Elasticsearch 6 indices through a temporary
Elasticsearch 6 node and Elasticsearch remote reindexing.

The workflow follows the
[Archivematica 1.18 Elasticsearch upgrade documentation](https://www.archivematica.org/en/docs/archivematica-1.18/admin-manual/installation-setup/upgrading/upgrading/#upgrade-elasticsearch).

## Workflow design

The role runs one explicit phase at a time. A stable
`archivematica_upgrade_id` identifies the upgrade run and stores persistent
state under `/var/lib/archivematica-upgrades/<archivematica_upgrade_id>`.
Re-running a completed phase is safe. Cleanup is separate and requires an
explicit confirmation variable.

For a clean migration, run the phases and the normal Archivematica installation
automation in this order:

1. Run `check-readiness`.
2. Run `prepare`.
3. Run `cutover-before-install`.
4. Run the normal Archivematica installation automation to install
   Archivematica 1.18, Storage Service 0.24, and Elasticsearch 8.
5. Run `cutover-after-install`.
6. Run `migrate`.
7. Run `validate`.
8. Complete operator validation, then run `cleanup`.

The installer invocation remains outside this role because a role cannot import
and bracket an external playbook.

## Prerequisites

This workflow currently supports a single-host installation managed with
`ansible-archivematica-src`. One or more local MCP client instances are
supported. Before running `check-readiness`, configure the target host with the
Archivematica 1.18 installer variables described below.
Run every role phase with `become: true`. The workflow manages system services,
writes to protected directories, and starts the temporary Elasticsearch 6
process as a non-root local account.
The installer configuration must select Archivematica `v1.18.x` or
`stable/1.18.x`, Storage Service `v0.24.x` or `stable/0.24.x`, Elasticsearch
`8.x`, and full search indexing. The installed Elasticsearch service must still
be the Archivematica 1.17 Elasticsearch 6 instance until `prepare` completes.
The readiness check also fails when Elasticsearch snapshot repositories remain
configured so operators can review and remove them before package removal.
The first `prepare` invocation repeats the readiness checks immediately before
stopping services and creating backups so changed conditions cannot be hidden
behind an older checkpoint.

The role consumes the existing `archivematica_src_*` installer variables for
database names, Storage Service database mode, service configuration, and
version checks. It supports Ubuntu, Rocky Linux, and Red Hat hosts. The
`validate` phase also uses the configured Dashboard and Storage Service API
credentials to verify application API responses after the upgrade.
Automated phase and migration coverage runs on Ubuntu 24.04 and Rocky Linux 9;
Rocky Linux 9 is used as the automated Red Hat-family compatibility target.
Review `archivematica_upgrade_application_services` for each deployment.
Operators must include every local unit that can submit work, expose the app,
or depend on Elasticsearch during cutover. Installed common local units such as
`gearman-job-server` and `nginx` are added to the managed service list
automatically unless they are listed in
`archivematica_upgrade_ignored_common_local_services`.

By default, MySQL commands use the executing root account's standard client
configuration, such as `/root/.my.cnf`. Set
`archivematica_upgrade_mysql_defaults_extra_file` when the upgrade requires a
different protected MySQL defaults file. For restricted-network hosts, set an
internal `archivematica_upgrade_es6_archive_url` and matching
`archivematica_upgrade_es6_checksum`; otherwise `migrate` downloads the
temporary Elasticsearch archive and checksum from `artifacts.elastic.co`.

For QA validation against moving branches, override the accepted target
patterns explicitly:

```yaml
archivematica_upgrade_am_version_pattern: '^qa/1\.x$'
archivematica_upgrade_ss_version_pattern: '^qa/0\.x$'
```

The moving QA branches are intentionally not accepted by the production
defaults.

## Variables

Required operator inputs:

| Variable | Description |
| --- | --- |
| `archivematica_upgrade_id` | Stable identifier for the upgrade run, using letters, numbers, dots, underscores, or dashes. |
| `archivematica_upgrade_snapshot_confirmed` | Set to `true` only after an external recovery snapshot or backup is confirmed. |

Common optional variables:

| Variable | Default | Description |
| --- | --- | --- |
| `archivematica_upgrade_path` | `1.17-to-1.18` | Upgrade workflow implemented by this role. |
| `archivematica_upgrade_phase` | `check-readiness` | Phase to execute when invoking the role directly. |
| `archivematica_upgrade_root` | `/var/lib/archivematica-upgrades` | Persistent state and backup root. |
| `archivematica_upgrade_es6_port` | `9500` | Port for the temporary Elasticsearch 6 node used by the `elasticsearch-6-to-8` migration. |
| `archivematica_upgrade_es8_url` | `http://127.0.0.1:9200` | Compatibility endpoint used as the default for source and destination Elasticsearch URLs. |
| `archivematica_upgrade_source_es_url` | `archivematica_upgrade_es8_url` | Source Elasticsearch endpoint used before the installer handoff. |
| `archivematica_upgrade_destination_es_url` | `archivematica_upgrade_es8_url` | Destination Elasticsearch endpoint installed by the normal Archivematica installation automation. |
| `archivematica_upgrade_es_data_dir` | `elasticsearch_data_dir` or `/var/lib/elasticsearch` | Packaged Elasticsearch data directory to measure, back up, and preserve during cutover when a migration needs that. |
| `archivematica_upgrade_es6_user` | SSH user | Non-root account used to run the temporary Elasticsearch 6 process. |
| `archivematica_upgrade_es6_archive_url` | Elastic download URL | Optional Elasticsearch 6 archive URL override. Set `archivematica_upgrade_es6_checksum` with this override. |
| `archivematica_upgrade_es6_checksum` | empty | Optional checksum override for the downloaded Elasticsearch 6 archive. When empty, the role verifies Elastic's published SHA-512 checksum URL. |
| `archivematica_upgrade_es6_java_opts` | `-Xms2g -Xmx2g` | JVM memory options for the temporary Elasticsearch 6 node. |
| `archivematica_upgrade_java_11_home` | empty | Optional Java 11 home override for the temporary Elasticsearch 6 node. When empty, the role searches under `/usr/lib/jvm`. The selected executable must report Java major version 11. |
| `archivematica_upgrade_mysqldump_timeout` | `7200` | Maximum number of seconds allowed for each MySQL database backup. |
| `archivematica_upgrade_es_data_timeout` | `7200` | Maximum number of seconds allowed for Elasticsearch filesystem archives and temporary-node copy operations. |
| `archivematica_upgrade_reindex_timeout` | `3600` | Maximum number of seconds to poll each asynchronous remote-reindex task. |
| `archivematica_upgrade_reindex_batch_size` | `1000` | Remote reindex batch size. Tune this with `archivematica_upgrade_reindex_timeout` for large installations. |
| `archivematica_upgrade_disk_multiplier` | `3` | Conservative working-storage safety multiplier applied by migrations that need extra Elasticsearch working copies. |
| `archivematica_upgrade_disk_extra_bytes` | `1073741824` | Extra free-space margin required during readiness checks for upgrade storage and migration destination filesystems. |
| `archivematica_upgrade_mysql_defaults_extra_file` | empty | Optional protected MySQL client defaults file used by readiness queries and backups. Use this for non-default hosts, sockets, or credentials. |
| `archivematica_upgrade_mysql_client_args` | `[]` | Additional non-secret MySQL client arguments used by readiness queries and backups. Keep credentials in the protected defaults file. |
| `archivematica_upgrade_archivematica_user` | `archivematica` | Local Archivematica account that owns restored Dashboard processing configuration files. |
| `archivematica_upgrade_archivematica_group` | `archivematica_upgrade_archivematica_user` | Local Archivematica group that owns restored Dashboard processing configuration files. |
| `archivematica_upgrade_processing_config_dir` | `/var/archivematica/sharedDirectory/sharedMicroServiceTasksConfigs/processingMCPConfigs` | Dashboard processing configuration directory backed up during `prepare` and restored during `restore-backup`. |
| `archivematica_upgrade_src_role_names` | Path metadata | Accepted `ansible-archivematica-src` role names during the readiness check. Override explicitly for QA branch testing. |
| `archivematica_upgrade_am_version_pattern` | Path metadata | Accepted Archivematica target version pattern. Override explicitly for QA branch testing. |
| `archivematica_upgrade_ss_version_pattern` | Path metadata | Accepted Storage Service target version pattern. Override explicitly for QA branch testing. |
| `archivematica_upgrade_application_services` | Standard Archivematica services | Local systemd services stopped during the upgrade and started during validation. Override to include additional local units. When multiple MCP clients are configured, the role replaces `archivematica-mcp-client` with the numbered units managed by `ansible-archivematica-src`. Installed common local services are added automatically unless ignored. |
| `archivematica_upgrade_common_local_services` | `gearman-job-server`, `nginx` | Common local units that are automatically managed when installed unless explicitly ignored. |
| `archivematica_upgrade_ignored_common_local_services` | `[]` | Installed common local units intentionally left outside this upgrade workflow. |
| `archivematica_upgrade_restore_confirmed` | `false` | Must be set to `true` for `restore-backup` after confirming rollback should start from the prepared backup artifacts. |
| `archivematica_upgrade_cleanup_confirmed` | `false` | Must be set to `true` for cleanup. |
| `archivematica_upgrade_remove_rollback_data_confirmed` | `false` | Set to `true` during cleanup only after the rollback retention period has ended. |
| `archivematica_upgrade_am_api_url` | Dashboard site URL | Dashboard URL used during authenticated API validation. |
| `archivematica_upgrade_am_api_user` | Dashboard configured user | Dashboard API user used during validation. |
| `archivematica_upgrade_am_api_key` | Dashboard configured API key | Dashboard API key used during validation. |
| `archivematica_upgrade_am_search_validation_url` | empty | Optional Dashboard-compatible archival-storage search URL used for a post-upgrade smoke test. The endpoint must be reachable from the upgrade host and return Dashboard search JSON. |
| `archivematica_upgrade_ss_api_url` | Storage Service configured URL | Storage Service URL used during authenticated API validation. |
| `archivematica_upgrade_ss_api_user` | Storage Service configured user | Storage Service API user used during validation. |
| `archivematica_upgrade_ss_api_key` | Storage Service configured API key | Storage Service API key used during validation. |
| `archivematica_upgrade_validate_certs` | `true` | Whether authenticated API validation verifies TLS certificates. |

## Migration safety

Every upgrade path creates required rollback artifacts for the MCP database,
Storage Service database, `/etc`, Dashboard processing configuration files, and
Elasticsearch filesystem state. The Elasticsearch artifacts are compressed
archives of `/etc/elasticsearch`, `archivematica_upgrade_es_data_dir`, and
`/var/log/elasticsearch`, stored as `elasticsearch-config-before-upgrade.tgz`,
`elasticsearch-data-before-upgrade.tgz`, and
`elasticsearch-logs-before-upgrade.tgz` under the upgrade backup directory. The
backup manifest records checksums and byte sizes for these artifacts, and
`restore-backup-check` validates them before any restore starts.

The `/etc` and Elasticsearch archives are retained as manual safety artifacts.
Generic `restore-backup` restores the application databases and Dashboard
processing configuration files. Automated Elasticsearch restore is implemented
only by migrations that need it.

For `elasticsearch-6-to-8`, before the Elasticsearch 6 package is removed, the
role also preserves the active Elasticsearch configuration, data, and log
directories with a `-before-upgrade` suffix, such as
`/var/lib/elasticsearch-before-upgrade`. These preserved directories support
rollback and provide the source data for remote reindexing. They are retained
until rollback data removal is explicitly confirmed.

The temporary Elasticsearch archive is checked against Elastic's published
SHA-512 checksum by default. After Elasticsearch 8 is installed, the role
reindexes `aips`, `aipfiles`, `transfers`, and `transferfiles`, verifies the
document counts, and restores the Elasticsearch configuration that existed
before the temporary remote-reindex setting was applied. Configuration
restoration and temporary Elasticsearch 6 shutdown also run when reindexing
fails.
Remote reindexing runs as asynchronous Elasticsearch tasks. The role stores
their IDs under
`state/migrations/elasticsearch-6-to-8/reindex-task-ids.json` before polling so
a repeated `migrate` phase resumes the submitted tasks instead of creating
duplicates. Elasticsearch 6-to-8 migration state and checkpoints live under
`state/migrations/elasticsearch-6-to-8/` and
`checkpoints/migrations/elasticsearch-6-to-8/`; the top-level `state/` and
`checkpoints/` directories are reserved for the generic upgrade lifecycle.

The readiness check always requires enough upgrade-root storage for the
Elasticsearch filesystem archives plus the configured extra margin. The
`elasticsearch-6-to-8` migration also applies a conservative working-storage
heuristic of three times the existing Elasticsearch data plus 1 GiB. This is an
operator safety margin for the temporary copies created by that workflow, not an
Archivematica upstream requirement. Review the filesystem layout before
lowering it. That migration separately requires enough free space on the
Elasticsearch data filesystem for the Elasticsearch 8 destination indices plus
the configured extra margin.

The `cleanup` phase removes temporary Elasticsearch 6 runtime files by default
and retains SQL dumps, configuration archives, Elasticsearch archives, and
preserved Elasticsearch directories for rollback. Set
`archivematica_upgrade_remove_rollback_data_confirmed=true` only when those
rollback artifacts are no longer required.

### Restore from rollback backups

If the upgrade must be rolled back before rollback data has been removed, first
run `restore-backup-check` to validate the backup manifest and backup artifact
checksums. This phase is non-destructive.

The role does not reinstall or downgrade Elasticsearch. Before running
`restore-backup`, run the external deployment automation for the 1.17
environment so Archivematica, Storage Service, and packaged Elasticsearch 6 are
installed again if `cutover-before-install` or the installer handoff has already
run. The Elasticsearch 6-to-8 restore hook verifies that the installed
`elasticsearch` package is version 6.x and fails before stopping services or
moving directories if that handoff has not happened. The package may be stopped;
the restore hook stops it again before moving Elasticsearch directories.

After packaged Elasticsearch 6 is installed, run `restore-backup` with
`archivematica_upgrade_restore_confirmed=true`. The phase validates the backup
manifest again, stops local Archivematica and Elasticsearch services, runs any
migration restore hooks, restores the Archivematica MySQL databases, and
restores Dashboard processing configuration files with Archivematica ownership.
For `elasticsearch-6-to-8`, the migration restore hook stops the temporary
Elasticsearch 6 node and moves preserved Elasticsearch directories back into
their original locations. The phase records a `restore-started` checkpoint and
leaves service startup and application validation to the operator or the normal
source-version deployment automation.

The `/etc` and Elasticsearch archives are retained as manual safety artifacts.
`restore-backup` does not automatically unpack them.

## Direct use

Install the role as `artefactual.archivematica_upgrade`, then invoke one phase:

```yaml
---
- hosts: archivematica
  become: true
  roles:
    - role: "artefactual.archivematica_upgrade"
      vars:
        archivematica_upgrade_phase: "check-readiness"
        archivematica_upgrade_id: "am-1.18-2026-06-01"
        archivematica_upgrade_snapshot_confirmed: true
```

For end-to-end orchestration, invoke the phases in the documented order and run
the normal Archivematica installation automation between the two cutover
phases.

For an operator-facing sample procedure, see
[docs/runbooks/1.17-to-1.18.md](docs/runbooks/1.17-to-1.18.md).

## Adding an upgrade path

Each supported `archivematica_upgrade_path` value is an explicit adjacent
transition in `_archivematica_upgrade_supported_paths`. For example, a future
Archivematica 1.18 to 1.19 workflow would use `1.18-to-1.19` as its path
identifier. Do not model unsupported jumps such as `1.17-to-1.19`; operators
should run each supported adjacent transition in order.

Each path entry stores generic target installer constraints and an ordered
`migrations` list. Target installer constraints are the expected
`ansible-archivematica-src` role names, Archivematica version pattern, and
Storage Service version pattern for the external installer handoff. For
`1.17-to-1.18`, the migration list contains only `elasticsearch-6-to-8`.
Future paths should register only the migrations they actually need. Migration
implementations live under `tasks/migrations/<migration>/` and expose hook
files for the phases they need, such as `migrate.yml`. Requirements that belong
to one migration, such as the Elasticsearch 6 source and Elasticsearch 8
destination version ranges, should live in that migration's hook files rather
than in path target metadata.

### Migration hooks

A migration can add tasks to any supported hook point by creating a matching
YAML file under `tasks/migrations/<migration>/`. Missing hook files are valid
no-ops, so migrations only need to implement the phases they affect. Hook files
run only when the migration name is listed in the selected path's `migrations`
list.

Supported hook files:

- `load-context.yml`
- `check-readiness.yml`
- `prepare-before-readiness.yml`
- `prepare.yml`
- `prepare-backup.yml`
- `cutover-before-install.yml`
- `cutover-after-install.yml`
- `load-state.yml`
- `migrate.yml`
- `validate-before-services.yml`
- `validate.yml`
- `restore-backup-check.yml`
- `restore-backup-before-services.yml`
- `restore-backup.yml`
- `cleanup.yml`

#### `elasticsearch-6-to-8` hooks

The `1.17-to-1.18` path enables the `elasticsearch-6-to-8` migration. It
implements these hook files:

| Hook | Purpose |
| --- | --- |
| `load-context.yml` | Sets migration-specific Elasticsearch version constraints plus state, backup, checkpoint, and artifact paths. |
| `load-state.yml` | Loads the prepared Elasticsearch source version, source index counts, Java 11 home, and temporary Elasticsearch 6 paths. |
| `prepare-before-readiness.yml` | Keeps packaged Elasticsearch 6 running before the repeated readiness checks run during `prepare`. |
| `check-readiness.yml` | Requires the installer handoff to target Elasticsearch 8, a packaged Elasticsearch 6 source, removed snapshot repositories, an unused temporary Elasticsearch 6 port, and enough working storage. |
| `prepare.yml` | Records the packaged Elasticsearch 6 version and source index counts used later for reindex validation. |
| `prepare-backup.yml` | Registers the generic Elasticsearch filesystem backup artifacts in the backup manifest. |
| `cutover-before-install.yml` | Stops packaged Elasticsearch 6, preserves its config/data/log directories, uninstalls the `elasticsearch` package, and records the removal checkpoint. |
| `cutover-after-install.yml` | Requires the Elasticsearch 6 removal checkpoint and verifies that packaged Elasticsearch 8 is installed and responding. |
| `migrate.yml` | Prepares the temporary Elasticsearch 6 runtime, reindexes into Elasticsearch 8, restores Elasticsearch 8 configuration, and stops the temporary node. |
| `validate-before-services.yml` | Requires completed reindexing and confirms the temporary Elasticsearch 6 port is stopped before services start. |
| `validate.yml` | Verifies Elasticsearch 8 destination index counts against the captured Elasticsearch 6 source counts. |
| `restore-backup-check.yml` | Requires Elasticsearch 6 metadata in the backup manifest before rollback restore proceeds. |
| `restore-backup-before-services.yml` | Requires the packaged Elasticsearch package to be installed at version 6.x before restore. |
| `restore-backup.yml` | Stops packaged and temporary Elasticsearch, removes current packaged Elasticsearch directories, and moves preserved Elasticsearch 6 directories back. |
| `cleanup.yml` | Removes the temporary Elasticsearch 6 runtime directory and downloaded archive after validation. |

Other files under `tasks/migrations/elasticsearch-6-to-8/`, such as
`ensure-es6.yml`, `prepare-es6-runtime.yml`, and `perform-reindex.yml`, are
helpers included by these hooks rather than lifecycle hook entry points.

To add an upgrade path:

1. Add the identifier to `_archivematica_upgrade_supported_paths` in
   `vars/main.yml` with generic target installer constraints and an ordered
   `migrations` list.
2. Reuse the generic public phase entry points in `tasks/phases/`. Add or
   change common phase behavior only when it applies safely to every path that
   uses that phase.
3. Add migration-specific hooks under `tasks/migrations/<migration>/` for the
   phases they affect. Missing hook files are valid no-ops. For example, a
   migration can provide `prepare.yml`, `migrate.yml`, and `cleanup.yml`
   without implementing every public phase. Keep migration-specific source or
   destination package/version constraints in those hooks.
4. Keep migration-specific state under
   `state/migrations/<migration>/` and migration-specific checkpoints under
   `checkpoints/migrations/<migration>/` so future paths do not inherit
   another path's runtime assumptions.
5. Share helpers only when their behavior and safety assumptions apply
   unchanged to every workflow that uses them.
6. Add any operator variables to `defaults/main.yml` without changing defaults
   relied on by existing upgrade paths.
7. Document the new path's prerequisites, normal installer boundary, retained
   rollback data, cleanup behavior, and any differences from earlier paths.
8. Add coverage for every phase, resumability, expected failure handling,
   cleanup, and required OS coverage when automated tests are available.

The public phases define the orchestration contract. Their implementation does
not need to copy the Elasticsearch 6 remote-reindex workflow when a later
Archivematica upgrade requires different migration steps.

## Tests

Automated checks use `uv`-managed Python tooling and Docker-backed Molecule
scenarios. Run the default Ubuntu 24.04 role checks with:

```sh
make molecule-test
make molecule-coverage
make molecule-test-phases
pre-commit run --all-files
git diff --check
```

See [molecule/README.md](molecule/README.md) for the scenario layout, coverage
contract, fixture design, and commands for running individual scenarios.
