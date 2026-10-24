# CODE RECALL

**Solve. Commit. Recall. Improve.**

A local-first CLI for your coding archive, active recall, revision schedule,
private mistakes and Git history. No server, database, account, telemetry,
Node.js or Docker is required. Python 3.11+ and Git are recommended.

## Install

This source tree builds the `coderecall` package. Until a release is published,
install from the checkout:

```console
pipx install .
```

The intended published installation is `pipx install coderecall`; this project
does not claim a PyPI release has been published.

```console
mkdir leetcode-solutions
cd leetcode-solutions
git init
coderecall init
coderecall add --file solution.py --title "Two Sum" --external-id 1 --platform leetcode --topics array,hash-table
coderecall status
coderecall today
coderecall revise 1
coderecall stats
coderecall backup
coderecall export --output learning.json
```

`add` prompts for a title and existing file when omitted. It creates solution
code, public README and metadata, then stores a private revision schedule.
If Git exists it attempts an owned-files-only commit. Configure your Git author
normally first. `--no-commit` disables this for one capture. A Git failure is
reported separately from successful local capture.

## Recall, rather than rereading

`revise` selects the earliest due problem. `revise <id>` practices early.
The previous solution stays hidden. Edit the blank private workspace, use
progressive hints if needed, then submit your **self-assessed** result. Pausing
excludes time. Interview mode disables hints and asks for approach/complexity.

For scripts (global flags precede the command):

```console
coderecall --json --non-interactive revise 1
coderecall --json recall submit r_THE_RETURNED_ID --result pass --confidence 4 --seconds 391
coderecall recall compare r_THE_RETURNED_ID
```

Passing code reviews require a nonempty saved attempt. For explanation-only
practice, use `--verbal --approach "your explanation"`; analytics labels that
assessment separately. Submission remains self-assessment, not proof of correctness.

`recall capture RECALL_ID --yes` explicitly promotes submitted code into the public
solution archive. Private notes and confidence remain private. The optional Docker
runner executes explicitly selected Python scripts/assertions with resource limits,
no network and no host mounts. OpenAI is available as an opt-in provider with
per-request consent. Both are disabled by default; see [optional adapters](docs/optional.md).

## Your data

| Public Git files | Private `.coderecall/` |
| --- | --- |
| Source, README, basic metadata, public approach | Notes, hints, review history, confidence, mistakes, workspaces, sessions, schedule |

The complete `.coderecall/` directory is ignored by default. Public metadata is
already selectively versioned with each solution; personal state is never staged
by CodeRecall. Backups contain **learning state, not source code or workspaces**.
Use Git for code backup. JSON exports are full fidelity; CSV and Markdown are
human-oriented summaries. Treat backups/exports as private.

## Useful commands

```console
coderecall import ./old-solutions --dry-run
coderecall import ./old-solutions --yes
coderecall problems --topic graphs --failed
coderecall search "binary search"
coderecall note 1 --text "Check duplicate values"
coderecall mistake 1 "Forgot duplicate handling" --category edge-case
coderecall schedule suspend 1
coderecall schedule resume 1
coderecall session start
coderecall session stop --note "Practiced graph traversal"
coderecall summary --week
coderecall --dry-run git commit
coderecall git commit --yes
coderecall sync --yes
coderecall doctor
```

Sync uses an existing Git upstream. Set it with Git; CodeRecall never creates
remote repositories, rewrites history, force pushes, stashes or resets work.
`sync` fetches and shows a plan, then fast-forwards or pushes after confirmation.
Use `sync --import-solutions --yes` to also adopt source metadata into the local
catalog, or run `import` separately. Confirmation is bound to the previewed Git refs.

## Documentation and development

* [Architecture](architecture.md)
* [CLI reference](docs/cli.md)
* [Configuration](docs/configuration.md)
* [Scheduling and metrics](docs/revision.md)
* [Git and GitHub](docs/git.md)
* [Plugins](docs/plugins.md)
* [Troubleshooting](docs/troubleshooting.md)
* [Validation and measured limits](docs/validation.md)
* [Security](SECURITY.md), [Contributing](CONTRIBUTING.md)

```console
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m mypy
python -m build
```

Snapshot storage intentionally uses linear scans. There is a 64 MiB state limit
and a 2 MiB per-source import limit. Import previews retain only paths/fingerprints,
then apply batches capped at 100 files or 8 MiB of source. Generated file updates
and state use a recoverable transaction journal. See validation notes for measurements.
