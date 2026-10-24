# Validation — 0.2.0

Local environment: Windows, Python 3.14.3, Git 2.53.0.windows.3.

## Verified locally

* **97 passed, 2 skipped** in 69.05 seconds in the expanded suite.
  A subsequently added end-to-end recall-capture/terminal-output regression also
  passed with all five CLI tests; the current suite contains 100 tests.
* Ruff lint and strict mypy passed (37 production modules).
* Wheel and source distribution built as 0.2.0.
* Fresh wheel installation completed init/capture/saved-code recall/stats/backup/
  restore/export through `python -m coderecall`.
* Real local Git remotes exercised push, fast-forward, divergence, approved-ref
  changes, private-state blocking, outgoing secret scanning and integrated import.
* Fault injection exercised interrupted journal writes and user edits during
  recovery. Import revalidates preview fingerprints and uses bounded batches.
* OpenAI transport tests check endpoint, disclosure separation, response validation,
  authentication errors, rate limits, bounded retry and redacted failures.
* Docker adapter tests check restrictions, unavailable engine, timeout, memory-limit,
  script results and cleanup. These are adapter tests, not live isolation evidence.

## Explicit verification limits

* The local account cannot create symlinks, so that test skips. CI runs on POSIX too.
* Docker CLI 29.8.0 is installed, but its Linux engine socket is unavailable. Live
  container isolation is not locally verified. An opt-in real-container test and
  dedicated Ubuntu CI job are included; hosted jobs have not run in this workspace.
* Windows Application Control blocked the fresh environment's generated launcher
  with error 4551 in the 0.2.0 clean-install run. Module invocation passed. The
  validator reports this distinction and never changes or bypasses OS policy.
* No real OpenAI credential/request, GitHub login or live LeetCode request was used
  for this validation. No external publication or independent security audit is claimed.
* Two upstream Typer/Click deprecation warnings remain; Click is constrained below 9.

## Representative history benchmark

Command: `python scripts/benchmark_state.py --history 3 --sizes 1000 10000`.
Each problem includes an actual source file, a solution record, three reviews and
three activity records. One local run produced:

| Problems | Reviews | Snapshot bytes | Initial write* | Read | Search | Stats |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 3,000 | 3,206,309 | 0.9858 s | 0.5720 s | 0.5634 s | 0.6047 s |
| 10,000 | 30,000 | 32,141,309 | 12.0143 s | 5.7337 s | 5.1566 s | 6.8903 s |

*Initial write includes creation of all synthetic source files and snapshot
validation. This was one sample while other validation commands were running,
not an isolated throughput benchmark. Read/search/stats validate state and source
paths. The snapshot design is practical at ordinary practice-library sizes but
large histories have visible latency. No subsecond large-history claim is made.

The state cap is 64 MiB; journal transactions also have a 64 MiB cap, including
base64-encoded next state and pending file content. Consequently a very large
snapshot may hit the journal limit before the snapshot limit. Operations fail
before modifying public files when preparation exceeds that limit. A future
sharded-file/index design should be based on these measurements and preserve
the same recovery guarantees; no database was introduced.

## Reproduce

```console
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m build
python scripts/validate_install.py
python scripts/benchmark_state.py --history 3 --sizes 1000 10000
```

For live sandbox tests, start a supported local Linux engine, explicitly install
the trusted `python:3.12-alpine` image, and set `CODERECALL_TEST_DOCKER=1` before
running `tests/test_optional_adapters.py`. The application never pulls the image.
