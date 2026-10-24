# Git and GitHub

CodeRecall uses the installed Git executable with argument arrays, never shell
interpolation. It preserves working changes and does not reset, clean, stash,
force push, rewrite timestamps or create empty commits.

Capture saves locally first. Commit stages only owned solution/README/metadata
files, plus `.gitignore` only when it is exactly the generated single-rule file.
Unrelated staged files stop the commit. Existing modified ignore rules remain
your responsibility to commit. An initial `git config user.name` / `user.email`
may be necessary; CodeRecall never changes your identity or configuration.

Set up an upstream using ordinary Git:

```console
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git
git push -u origin main
coderecall --dry-run sync
coderecall sync
```

GitHub hosting is optional. `coderecall github connect` delegates to `gh auth
login --web`; disconnect logs out of the shared GitHub CLI identity. `gh` owns
credential storage; verify its OS-keyring configuration. CodeRecall neither
retrieves nor stores access tokens. `github status` explicitly invokes the
authentication check; `doctor` stays offline and does not probe credentials.

Sync states: CLEAN, LOCAL_AHEAD, REMOTE_AHEAD, DIVERGED, CONFLICT. Saved application
status also includes UNKNOWN, PUSH_PENDING and ERROR. A dirty tree stops sync.
Fetch updates remote refs before the plan. Only fast-forward merges are automatic.
Divergence/conflict requires manual Git reconciliation. Remote private state or
symlinks block automatic fast-forward. Re-run after resolving the cause.

`sync --import-solutions --yes` also imports public metadata after synchronization.
Alternatively `coderecall import . --dry-run` previews adoption separately. Existing
reviews/schedules are retained. Confirmation is bound to exact local/upstream refs,
not only ahead/behind counts. Push failure preserves successful local work.

Secret scanning checks all blobs of outgoing commits, including secrets removed
in a later commit. It blocks private keys and common credential patterns and
oversized blobs it cannot scan. It is a heuristic, not a guarantee. Explicit
`git.scan_secrets=false` disables it; only do that after independent review.
Git hooks and configured credential/SSH tools are trusted local Git configuration,
not a sandbox. Never commit in an untrusted repository without inspecting Git config.
