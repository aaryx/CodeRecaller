# CodeRecall architecture

CodeRecall is a local, synchronous Python CLI. No database, service, daemon,
telemetry, or account is required. GitHub, metadata fetching, AI and execution
are explicit opt-ins.

## Boundaries

`cli` handles arguments, prompts and presentation. `application` coordinates
use cases. `domain` contains typed records, validation, analytics and an injected
clock. `revision` owns deterministic scheduling. `storage` implements local
transactions and backups. `integrations` owns Git, GitHub, metadata, AI, editor
and runner adapters. Domain code does not import CLI or infrastructure code.

## State and ownership

* Public: solution code, README, minimal metadata under a configurable layout.
* Private: `.coderecall/config.toml`, `manifest.json`, `state.json`, `backups/`,
  and active recall workspaces. The entire directory is ignored by Git.
* Package: scheduling algorithms and use cases, never a user's schedule.
* Git: authoritative source history. Remote hosting is optional.

One schema-versioned `state.json` holds problems, solutions, schedules, reviews,
mistakes, study sessions and activity. This deliberately replaces six independent
JSON documents: a single atomic replacement commits a logically consistent
snapshot. Reads and writes take an OS advisory lock. Windows and POSIX locks
release automatically on process exit; a persistent lock file is not a stale
lock. JSON is strictly validated, including references and paths, before use.
Writes use a same-directory temporary file, flush, fsync and atomic replacement.
The prior snapshot is retained as `state.previous.json`. Migrations are explicit
and backed up. Unsupported future versions fail closed.

The initial implementation uses O(n) snapshot reads/searches and O(n) writes.
This is a conscious ceiling, not an invented scalability claim. Measure before
introducing shards or an optional local index. There is no embedded database.

## Transactions and failure recovery

Capture validates inputs, takes the project lock and stages compare-and-replace
images. A durable `transaction.json` journal contains validated resulting state
and generated-file writes before public files change. Recovery checks all paths
against recorded before/after hashes, completes matching writes and atomically
publishes state. Conflicting user edits stop recovery without discarding either
the edited file or journal. Metadata enrichment retains stable IDs and paths and
only replaces documentation that still matches its previous generated content.
Git runs after local persistence. A failed
commit/push never rolls back learning state. Explicit sync stores PUSH_PENDING.
No automatic clean, reset, force push, stash or non-fast-forward merge is performed.

Backups are bounded ZIP archives of validated private state/config/manifest;
they are not code backups. Restore validates every entry without extracting,
creates a recovery backup, then atomically replaces the learning snapshot.
Configuration is never silently restored over current configuration.

## Git and trust

All Git subprocesses pass argument arrays through one adapter. Commit previews
only changed owned paths and refuses unrelated staged changes. Hooks are normal
Git behavior and are not disabled. Import never invokes Git hooks or executes
repository files. Fetch is explicit; sync plans use ahead/behind counts and
fast-forward only. Dirty working trees and divergence stop synchronization.
Secret scanning covers outgoing commit blobs, including intermediate commits.
The scanner is heuristic, not a guarantee. GitHub authentication delegates to
the installed `gh` CLI and its credential store; CodeRecall stores no tokens.

Generated paths must be relative, remain under the resolved project root, avoid
reserved/control components, and contain no symlink ancestors. Imported files
and archives are data. Archive paths, entry types and uncompressed sizes are
validated before reads. Terminal control sequences from data are escaped.

## Recall

Clock is injectable. The scheduler is deterministic and replaceable through a
Protocol. Due/overdue are derived at invocation. Review history retains the
original due date and actual review time. Recall starts a blank private workspace
and privately snapshots its comparison baseline without displaying the old source.
Only explicit hint/reveal/compare displays it. Submitted code is preserved
separately so later edits cannot rewrite the comparison. Paused time is excluded.
Passing code reviews require saved code; explanation-only reviews require explicit
verbal assessment. All reviews remain labeled self-assessed. Sandbox script results
are separate and do not establish general problem correctness.

## Optional extensions

Trusted, explicitly installed Python entry points can implement provider,
scheduler, AI, template, exporter and runner protocols. Loading an extension is
code execution and requires explicit configuration. AI cannot call tools or
mutate files. External source disclosure needs explicit consent on each request.
The optional Linux Docker runner uses pre-existing images, no host mounts/network,
an unprivileged user and resource limits. OpenAI uses a fixed HTTPS endpoint,
environment credentials and per-request consent. Both remain disabled by default.
See `docs/optional.md` for exact capability checks and security limitations.
