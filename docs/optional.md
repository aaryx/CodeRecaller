# Optional execution and AI

Both integrations are disabled by default. They never initialize during ordinary
local capture, recall, search or analytics.

## Docker Python runner

Install/start a local Linux Docker engine and explicitly obtain a trusted Python
image yourself. CodeRecall uses `--pull never` and never downloads images.

```console
coderecall config set execution.enabled true
coderecall config set execution.image python:3.12-alpine
coderecall run solution_with_assertions.py --yes
```

The runner checks Linux/seccomp/resource-limit support, uses the inspected image
ID, copies only the selected script into an unstarted container, then runs Python
with isolated mode. It has no host mounts, network, extra capabilities or root
user; root filesystem is read-only, temporary space is bounded, memory is 128 MiB,
swap is disabled, CPU is 0.5, processes are limited to 32, and wall time defaults
to five seconds (configurable 1–60). Logs are discarded to prevent output floods.
Cleanup removes only the uniquely named CodeRecall-owned container.

PASS means the script exited zero, not that the coding problem is generally
correct. Include your own explicit sample/custom assertions in the script. FAIL
means Python exited 1 (assertion or exception); other exit codes are RUNTIME_ERROR.
TIMEOUT, MEMORY_LIMIT, SANDBOX_ERROR and UNAVAILABLE are distinguished. Results
do not silently convert self-reported reviews to verified correctness.

Containers share the host kernel and are not a VM-grade security guarantee. Use a
trusted patched local engine/image, especially for adversarial code. The adapter
does not start Docker, change host policies, or fall back to host execution.

## OpenAI

```console
coderecall config set ai.plugin openai
coderecall config set ai.model gpt-4.1-mini
coderecall config set ai.enabled true
coderecall ai explain --file solution.py --consent
```

Supply `OPENAI_API_KEY` only in the process environment (or inject it from your OS
credential manager). Do not put it in project TOML, source or CLI arguments.
Every source disclosure requires `--consent`. The endpoint is fixed to OpenAI's
HTTPS Chat Completions endpoint, redirects are disabled, `store=false` is set and
output is bounded. Provider data-retention/billing rules still apply.

Instructions and source are separate messages. Responses cannot dispatch tools,
modify files or perform Git actions. Tool requests and incomplete output are
rejected. Authentication and rate-limit errors stop immediately; server retries
are bounded to three calls with backoff. Ambiguous POST timeouts are not retried
to avoid duplicate billing. Errors never include credential-bearing response bodies.

Trusted explicitly installed AI plugins remain supported through the same
interface. Their internal credential/network behavior must be reviewed separately.
