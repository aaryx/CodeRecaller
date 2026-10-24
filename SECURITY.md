# Security policy

Report vulnerabilities through the hosting repository's private vulnerability
reporting channel when enabled. Otherwise contact a listed maintainer privately;
do not publish source code, secrets, private learning snapshots or exploit details
in an ordinary issue. This repository does not invent a contact address or promise
a response SLA. Supported fixes target the current 0.2 series.

## Defaults and boundaries

* No telemetry, server, background job, hosted state or implicit AI requests.
* `.coderecall/` is private and ignored by Git; exported data and backups remain
  sensitive local files. Backups are not encrypted. Use disk encryption/OS ACLs.
* Source code, public approach/complexity, README and basic metadata are public
  if you push them. Never put private notes or secrets in public fields.
* Git credentials are handled by Git/`gh`; no token is retrieved or persisted by
  CodeRecall. Ensure their OS credential manager is configured securely.
* Generated paths reject traversal, reserved names, alternate data streams,
  symlinks and junctions. Import reads bounded source/metadata as data, never
  executes setup scripts, shells or dependency installers.
* Backups use exact allowlisted entries and bounded decompression; restore reads
  data in memory and never calls archive extraction. Current state is preserved.
* Git operations use argument arrays, owned-path staging, dirty/conflict checks,
  fast-forward-only synchronization and an outgoing-history secret heuristic.
* Git remote URLs disallow `ext::` and unsupported URL schemes. Git hooks,
  credential helpers, SSH configuration, editors and installed plugins are trusted
  local executable configuration. Do not point CodeRecall at a hostile Git repo.
* Source execution is disabled by default. The optional Linux Docker runner has
  no host mounts/network and uses an unprivileged user, read-only root and resource
  limits. It never executes source in the host Python process. Containers share
  the host kernel; this is not a VM-grade security guarantee.
* The optional OpenAI adapter and AI plugins require configuration and per-request disclosure consent.
  Model output is text, validated for type/size, never interpreted as actions.

## Explicit network operations

`add --fetch` (public LeetCode HTTPS endpoint); `sync`/`git push` (configured Git
remote); `github connect|disconnect|status` (`gh`); consented AI requests (configured
provider). Installation/development tools contact package repositories. Ordinary
capture, import, recall, stats, search, doctor, export and backup stay offline.

## Limitations

JSON snapshot and source size limits are deliberate. Secret scanning is heuristic
and can have false positives/negatives. Atomic rename durability depends on the
filesystem. Windows private directory ACLs inherit from the parent. Same-user
malicious processes and compromised installed executables are outside the threat
model. No independent security audit or sandbox security certification is claimed.
