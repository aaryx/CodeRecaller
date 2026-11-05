# Changelog

All notable changes to CodeRecaller will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-10-25

### Added
- **FSRS v4 Scheduler**: Implemented the modern Free Spaced Repetition Scheduler alongside classic interval scheduling, targeting customizable retention rates (default 90%).
- **Terminal Encoding Resilience**: Auto-detecting output engine supporting modern UTF-8 terminals with Rich panels and emojis, with automatic ASCII fallback (`+---+`, ASCII bars) on legacy Windows `CP1252` consoles.
- **RFC 8259 ASCII Fallback**: CLI JSON output automatically catches `UnicodeEncodeError` on non-UTF-8 terminals and emits valid ASCII JSON with standard `\uXXXX` escaping.
- **Commit-Time Secret Scanner**: Outgoing Git commits are inspected for inadvertently staged AWS tokens, GitHub credentials, OpenAI API keys, Slack tokens, Stripe keys, and private SSH/RSA keys.
- **Multi-Format Export Engine**: Export learning history, review metrics, and topic retention to self-contained interactive HTML, full-fidelity JSON, CSV, and Markdown.
- **Comprehensive Diagnostic Engine (`doctor`)**: Inspects 15 distinct health checks offline, validating Python version, Git/Docker availability, schema integrity, write permissions, and pending transactions.
- **Multi-Platform CI Matrix**: Automated GitHub Actions matrix testing across Python 3.11, 3.12, 3.13 on Ubuntu, macOS, and Windows runners, including live container sandbox isolation verification.
- **Automated Release Gate & Verification**: Added unified pre-release gate (`scripts/release_gate.py`) and clean-environment wheel installation verifier (`scripts/validate_install.py`).
- **Developer Onboarding & Trial Protocols**: Added 10-15 minute developer trial scenario (`docs/product/developer-trial-guide.md`) and reproducible 3-persona validation (`scripts/verify_personas.py`).

### Changed
- **Zero-Dependency OS File Locking**: Replaced external locking dependencies with native OS advisory locking (`msvcrt` on Windows and `fcntl` on POSIX systems).
- **Two-Phase Transaction Journaling**: Multi-file state operations write write-ahead journals (`transaction.json`) with cryptographic SHA-256 digests and deterministic roll-forward recovery.
- **Strict Architecture Boundaries**: Clean layered separation between `domain` (zero dependencies), `storage` (atomic snapshot store and journals), `execution` (Docker sandbox protocol), `integrations` (Git and process runners), `application` (facade and use cases), and `cli` (Typer and Rich commands).
- **ASCII CLI String Normalization**: Normalized CLI help docstrings, prompts, and UI status strings to standard 7-bit ASCII hyphens (`-`), preventing `charmap` codec crashes on Windows OEM CP437 consoles and font glyph corruption.
- **Search Index Enrichment**: Added progressive problem hints (`problem.hints`) to the full-text search index haystack.

### Fixed
- **Docker Runner Input Validation**: Early boundary validation rejects script files containing embedded null bytes (`\x00`) and safely wraps OS file inspection errors in `ValidationError`.
- **Windows File System Safety**: Normalized path separators across all operations, strictly rejecting Windows drive letters (`C:`), UNC network paths, alternate data streams (`:`), and DOS reserved device names (`CON`, `PRN`, `AUX`, `NUL`).
- **Scale Benchmarks**: Storage engine validated up to 10,000 problem snapshots (8.8 MB state) with sub-second latencies across all read, write, search, and analytics operations.

### Security
- **Hardened Docker Isolation**: Ephemeral execution container with read-only root (`--read-only`), dropped Linux capabilities (`--cap-drop ALL`), `no-new-privileges:true`, non-root execution (`65534:65534`), process limits (`pids-limit 32`), 128 MiB RAM ceiling, and strict network isolation (`--network none`).
- **Strict Backup Allowlist**: Zip archive restoration strictly limits payloads to `state.json`, `config.toml`, and `manifest.json`. Symlinks, directory traversal, hidden files, and unexpected entries are rejected.
- **Dev Dependency Pinning (CVE-2026-114613)**: Constrained `msgpack>=1.2.4` in `[project.optional-dependencies].dev` to eliminate memory leak advisory in dev security tooling (`pip-audit`) while maintaining zero runtime dependencies on `msgpack`.
- **Private Vulnerability Reporting**: Configured GitHub Security Advisories as the primary private disclosure intake channel without dead external links.

---

## [0.2.0] - 2026-10-08

### Added
- Metadata enrichment preserving problem identity, schedules, and user-edited documentation.
- Durable generated-file and state transactions with validated roll-forward recovery.
- Bounded fingerprinted solution imports; changed-since-preview files are safely rejected.
- Saved-code requirement for passing reviews, explicit verbal self-assessment, and submitted attempt snapshots.
- Sync approval bound to Git commit references; optional integrated catalog import.
- Readable terminal summaries and guided capture; JSON output remains machine-readable.
- Optional OpenAI adapter and restricted Linux Docker Python-script runner.
- Cached schema reflection, linear topic aggregation, and unmeasured-time handling.
- Expanded regression and security tests with optional live sandbox CI job.

---

## [0.1.0] - 2026-09-28

### Added
- Local JSON/TOML state, schema validation, OS locks, atomic snapshots, and backups.
- Solution capture, metadata and README generation, multi-approach storage, and import.
- Private recall sessions, deterministic scheduling, hint levels, mistake tracking, and analytics.
- Owned-file Git commits, explicit safe sync, and GitHub CLI authentication bridge.
- JSON/CSV/Markdown export, recovery, doctor diagnostic command, and project configuration.
- Optional installed scheduler/AI plugin contracts (AI disabled by default).
- Source execution explicitly unavailable without configured sandbox runner.
