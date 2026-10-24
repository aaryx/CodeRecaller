# Contributing

Python 3.11+ is supported. From a checkout:

```console
python -m venv .venv
```

Activate `.venv` using your shell, or invoke `.venv/Scripts/python` on Windows
and `.venv/bin/python` elsewhere.

```console
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m build
```

Tests use temporary projects/remotes; never run acceptance flows against personal
solutions. Network adapters use controlled failure tests. A skipped Windows
symlink test requires Developer Mode/elevated symlink permission; CI Linux/macOS
exercise POSIX behavior. No GitHub credentials are needed for the test suite.

Read [architecture.md](architecture.md). Put scheduling rules in `revision`,
business orchestration in `application`, pure rules/records in `domain`, I/O in
`storage`/`integrations`, and presentation in `cli`. Keep dependencies directional.
New state fields require schema/migration design and recovery tests, not silent
defaults for incomplete documents. Run journal fault-injection tests whenever
changing generated-file or snapshot persistence. New network activity must be explicit and
documented. Do not add unsafe execution, fake Git activity or cloud dependencies.

Submit focused PRs with user-visible behavior, test commands/results and migration
notes. Discuss new runtime dependencies and schema changes first. Follow the
code of conduct. The MIT license applies to contributions.
