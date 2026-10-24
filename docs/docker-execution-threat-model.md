# Docker Execution Threat Model & Sandbox Security Analysis

## 1. Executive Summary

CodeRecaller provides an optional containerized runner (`coderecall run <file>`) to execute user-authored Python solutions under strict isolation boundaries. This document defines the threat model, security architecture, isolation boundaries, verified properties, and operational limitations of the Docker execution sandbox.

---

## 2. Threat Model

The sandbox is designed to execute locally submitted Python scripts while protecting the host system and user workspace against accidental damage and malicious script behavior:

| Threat Category | Potential Attack Vector | Protection Mechanism |
| :--- | :--- | :--- |
| **Filesystem Modification** | Overwriting workspace files, altering host system binaries | `--read-only` rootfs, `--tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777`, zero host mounts |
| **Filesystem Traversal / Exfiltration** | Reading host files, `.env` files, SSH keys, AWS credentials | Zero host mounts (`-v`/`--mount` strictly prohibited), non-root execution (`--user 65534:65534`) |
| **Network Access & Exfiltration** | Exfiltrating code, phone-home beacons, downloading payloads | `--network none` (loopback only, no external egress/ingress) |
| **Privilege Escalation** | SUID binaries, Linux capability abuse, kernel exploitation | `--cap-drop ALL`, `--security-opt no-new-privileges:true`, running as `nobody` (`65534:65534`) |
| **Process / Fork Bombs** | Exhausting host process table (`:(){ :\|:& };:`) | `--pids-limit 32` |
| **Memory Exhaustion** | Consuming host RAM, swap thrashing (`bytearray(10**10)`) | `--memory 128m`, `--memory-swap 128m` (zero swap) |
| **CPU Denial of Service** | Infinite computation loops (`while True: pass`) | `--cpus 0.5`, wall-clock execution timeout (default 5s, max 60s) |
| **Disk Exhaustion / Log Flooding** | Writing infinite log streams to stdout/stderr | `--log-driver none` (discard logs), `--ulimit fsize=1048576` (1 MiB max write) |
| **Binary Execution from Scratch Space** | Writing ELF binaries to `/tmp` and executing them | `noexec` mount flag on `/tmp` tmpfs |
| **Image Substitution / Tampering** | Manipulating mutable tags (e.g. `python:latest`) | Runtime resolves immutable sha256 image ID before container creation |
| **Daemon Ingestion Attacks** | Explaining host files via daemon `docker cp` | Zero `docker cp` calls; script passed inline via `python -I -B -c` |
| **Command Injection / Shell Escaping** | Injecting shell metacharacters in arguments | Explicit entrypoint `python`, no `/bin/sh` or `/bin/bash` intermediary |

---

## 3. Sandboxing Architecture

```
+-----------------------------------------------------------------------+
| HOST SYSTEM (Developer Workstation)                                   |
|                                                                       |
|  +--------------------+       Docker Engine (Linux daemon)            |
|  | CodeRecaller CLI   |                   |                           |
|  |  (Python Runtime)  |                   v                           |
|  +---------+----------+       +-----------------------------------+   |
|            |                  | ISOLATED CONTAINER                |   |
|            | docker create    |                                   |   |
|            | (immutable ID)   | User: 65534:65534 (nobody)        |   |
|            v                  | Caps: Drop ALL, No-New-Privileges |   |
|  +--------------------+       | Network: none (isolated)          |   |
|  | Inline Execution   | ----> | Rootfs: Read-Only                 |   |
|  | -I -B -c "<codebox>|       | Tmpfs: /tmp (16M, noexec, nosuid) |   |
|  +--------------------+       | Resources: 128M RAM, 0.5 CPU, 32 P|   |
|                               +-----------------------------------+   |
+-----------------------------------------------------------------------+
```

### Key Architectural Controls

1. **Inline Execution via Python `-I -B -c`**:
   - `-I` (Isolated mode): Ignores `PYTHONPATH`, `PYTHONHOME`, user site-packages, and excludes the working directory from `sys.path`.
   - `-B`: Suppresses writing `.pyc` bytecode files.
   - Script content is bound to at most 64 KiB, safely below Linux kernel `MAX_ARG_STRLEN` (128 KiB) to prevent `execve` buffer overflows.
2. **Explicit Entrypoint & Zero Shell**:
   - Entrypoint is strictly overridden to `python`. No shell wrapper (`/bin/sh -c`) is permitted.
3. **Immutable Image Identification**:
   - `docker image inspect` validates that the image is Linux, does not expose declared volumes, and extracts the immutable SHA256 image ID (`sha256:...`) to eliminate tag-shadowing risks.
4. **Guaranteed Container Lifecycle & Cleanup**:
   - Containers are named with cryptographically random UUIDs (`coderecall-<uuid4>`).
   - Timed-out containers are sent SIGKILL.
   - The container is unconditionally destroyed in `finally` via `docker rm --force <name>`.

---

## 4. Verification Evidence

### 4.1 Real Live Container Tests (Validated in CI on Ubuntu Linux)
In GitHub Actions runner environments with a live Linux Docker daemon:
- **Network Isolation**: Probed `socket.create_connection(('1.1.1.1', 443))` raises `OSError` (Network unreachable).
- **Filesystem Immutability**: Attempted `open('/escape', 'w')` raises `OSError` (Read-only file system).
- **UID / GID Boundary**: Validated `os.getuid() == 65534` (unprivileged `nobody`).
- **Zero Host Exposure**: Validated absence of `/var/run/docker.sock`, `/host`, or any workspace mounts.

### 4.2 Adversarial Test Suite (`tests/test_docker_adversarial.py`)
Tested deterministically through verified orchestration mocks:
- Malicious image name injection attempts (e.g. `--privileged`, `; rm -rf /`, `$PATH`).
- Timeout validation boundaries (1s to 60s).
- Script validation (rejection of non-existent files, symlinks, directories, non-Python files, binary files, empty files, and files > 64 KiB).
- Missing Docker daemon or unsupported capabilities (missing seccomp, missing memory/pids/cfs quotas).
- Container creation failure handling (guaranteeing no dangling cleanup attempts).
- Non-zero exit code mapping (code 1 to `FAIL`, code 2 to `RUNTIME_ERROR`).
- Wall-clock timeout enforcement (SIGKILL dispatch + cleanup).
- Memory limit enforcement (OOMKilled status detection).
- Reliable container cleanup on normal completion, execution errors, and kill errors.

---

## 5. Scope, Trust Boundaries & Operational Limits

> [!WARNING]
> **Personal Local Use vs. Multi-Tenant SaaS**:
> CodeRecaller's Docker sandbox is engineered for personal developer workstations to safely practice algorithms without risking accidental host file corruption or unconstrained background loops.
>
> It is **NOT** a multi-tenant untrusted code evaluation platform (like LeetCode or HackerRank). Docker containers share the host Linux kernel. Any kernel zero-day vulnerability (privilege escalation, container breakout, CPU microarchitectural attacks like Spectre) could theoretically allow malicious code to compromise the host. For multi-tenant hosting, hypervisor-based microVMs (e.g. Firecracker, gVisor) are required.

---

## 6. Language Support Policy

The read-only sandbox strictly supports Python (`.py`) scripts. Compiled languages (e.g. C++, Rust) or runtimes requiring writable temporary compilation artifacts and executable permissions are deliberately excluded from this runner to maintain an immutable, noexec rootfs and scratch architecture. Attempting to run non-Python files raises an explicit `ValidationError`.

