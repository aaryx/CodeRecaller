# Security Policy & Architecture

## 1. Supported Versions

Security updates and bug fixes target the current release series:

| Version | Supported | Status |
| :--- | :--- | :--- |
| `0.3.x` | :white_check_mark: | Current active release line |
| `< 0.3.0` | :x: | End of life |

---

## 2. Reporting a Vulnerability

Please report suspected security vulnerabilities privately rather than opening public GitHub issues:
- Use the **Private Vulnerability Reporting** feature on GitHub: [Report a vulnerability](https://github.com/aaryx/CodeRecaller/security/advisories/new).
- Provide detailed reproduction steps, proof of concept, and an assessment of the impact.
- Maintain confidentiality until a patched release is published.

---

## 3. Threat Model & Security Boundaries

CodeRecaller is engineered with a **local-first, privacy-by-default** model. The boundaries below define what the application protects and where responsibilities lie:

### 3.1 Local-First Privacy & Storage Isolation
- **Zero Telemetry / Zero Background Daemons**: CodeRecaller contains no tracking, telemetry, or silent background processes. All capture, recall, statistics, search, and export operations execute strictly offline.
- **Private Learning State**: The `.coderecall/` directory contains private spaced repetition histories, notes, and schedules. It is automatically added to `.gitignore` during `coderecall init` before any learning data is stored.
- **Export & Backup Confidentiality**: Backups (`.coderecall/backups/`) and exports are stored unencrypted on the local filesystem. Users should rely on OS full-disk encryption (BitLocker, FileVault, LUKS) and user directory ACLs to protect local storage at rest.

### 3.2 Storage Durability & Archive Safety
- **Atomic Operations**: State snapshots (`state.json`) and configuration (`config.toml`) use atomic replacement (`.cr-*` temporary files with `fsync` and atomic rename), preventing torn writes during sudden power losses.
- **Two-Phase Transaction Journaling**: Multi-file mutations use a recoverable journal (`transaction.json`) with before/after cryptographic SHA-256 digests. Pending transactions are rolled forward deterministically upon startup.
- **Strict Backup Allowlisting**: Backups use zip archives with an exact 3-file allowlist (`state.json`, `config.toml`, `manifest.json`). Archives containing directories, symlinks, extra entries, path traversals (`../`), or encrypted payloads are rejected.
- **Safe Restoration**: CodeRecaller restores backups entirely in-memory and validates problem solution paths before committing. A pre-restore safety copy is created to guarantee recovery if a restore is interrupted.

### 3.3 Git Synchronization & Credential Protection
- **No Embedded Credentials**: Remote URLs containing inline credentials (e.g. `https://token@github.com/...`) are rejected. Users must rely on Git credential helpers or SSH keys.
- **Error Redaction**: Subprocess Git errors suppress stdout/stderr in error messages and logs to prevent credential leakage.
- **Fast-Forward Only**: Remote synchronization uses `--ff-only` merges. Destructive operations (`git reset --hard`, `git clean`) are never performed automatically.
- **Outgoing Secret Scanner**: Pre-push scanning audits outgoing commits for AWS access keys, GitHub tokens, Slack tokens, Stripe keys, OpenAI/Anthropic credentials, and private keys. Commits containing detected tokens or private `.coderecall` paths are blocked.

### 3.4 Docker Sandbox Isolation Boundary
- **Personal Local Practice**: The optional Docker runner (`coderecall run <file>`) executes user code under strict container controls:
  - Non-root execution (`--user 65534:65534`).
  - Read-only root filesystem (`--read-only`).
  - Strict network isolation (`--network none`).
  - Dropped Linux capabilities (`--cap-drop ALL`) and `no-new-privileges:true`.
  - Resource limits: 128 MiB RAM, 0.5 CPU cores, 32 process PIDs, 16 MiB `noexec` `/tmp`.
  - Inline Python execution (`python -I -B -c`) with max 64 KiB script bound.
  - Zero host mounts (`-v`/`--mount` strictly prohibited).
  - Stdout/stderr discarded via `--log-driver none`.
- **Multi-Tenant SaaS Boundary**: Containers share the host Linux kernel. CodeRecaller's sandbox is intended for individual developer safety; it is **NOT** a multi-tenant untrusted evaluation service. Hypervisor-based microVMs are required for multi-tenant SaaS environments.

### 3.5 AI Confidentiality & Explicit Consent
- **Opt-In Only**: AI integrations (`ai.enabled`) are disabled by default.
- **Consent Gate**: Every source code disclosure requires explicit user consent (`--consent`).
- **Zero API Key Persistence**: API keys must be provided via process environment variables (`OPENAI_API_KEY`) and are never written to project TOML files or state files.
- **Model Output Sandboxing**: AI responses are treated strictly as text data and are never evaluated as executable code or commands.

### 3.6 Cross-Platform Path Traversal Protections
- **Path Sanitization**: All file paths are validated against `..`, leading slashes, Windows drive letters (`C:`), UNC paths (`\\server\share`), and alternate data streams (`:`).
- **Windows Device Names**: Reserved DOS/Windows device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`) are rejected.
- **Symlink & Junction Rejection**: Symlinks and Windows NTFS directory junctions are strictly prohibited in project paths and archives.

---

## 4. Out of Scope

The following threat scenarios are outside CodeRecaller's security model:
1. **Compromised Host Environment**: Malware, keyloggers, or malicious processes running under the same OS user account.
2. **Host Kernel Exploits**: Kernel zero-day vulnerabilities enabling container escape from a hardened Linux Docker container.
3. **Hardware / Filesystem Corruption**: Physical storage failure without filesystem integrity guarantees.
4. **Malicious Git Remotes**: User-configured Git remotes pointing to untrusted malicious repositories with crafted git hooks or executable helpers.
