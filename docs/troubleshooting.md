# Troubleshooting

* **No project:** run `coderecall init` at your Git repository root. Multiple
  independent repositories each have their own `.coderecall` directory.
* **Already initialized:** no overwrite occurs. Run `doctor` and inspect files.
* **Git missing:** local capture/review still works. Install Git for version control.
* **Unknown author:** configure your Git identity, then `coderecall git commit`.
* **Unrelated staged changes:** commit or unstage those using Git yourself.
* **Dirty sync:** preserve and commit your work first; CodeRecall never stashes it.
* **No upstream:** configure the remote/tracking branch with Git before sync.
* **Divergence/conflict:** resolve using Git, inspect the result, then retry sync.
* **Push failed:** successful local capture/commits remain valid. Check connectivity,
  credentials and upstream permissions. Retry `sync`.
* **LeetCode denied/rate-limited:** omit `--fetch` and enter metadata manually.
  CodeRecall never bypasses login, CAPTCHA or rate restrictions.
* **No reviews due:** use `revise ID` to practice early or `today` for suggestions.
* **Locked:** another process is updating state. Wait or stop that process safely.
  OS locks release on exit; deleting the persistent lock file is unnecessary and
  unsafe while another process is active.
* **Corrupt state:** copy `.coderecall` before investigation. `doctor` detects
  malformed/incompatible snapshots. `restore PATH --yes` validates a backup and
  retains a recovery copy. `state.previous.json` is the preceding snapshot. Do not
  replace files while a process holds the state lock. Future schema versions
  require an appropriate package version; never forcibly downgrade the number.
* **Missing code:** state backups do not contain source/workspaces. Restore source
  through Git. `doctor` reports missing owned files.
* **Editor:** set `EDITOR` or `repository.editor`, for example `code --wait`.
  On PowerShell: `$env:EDITOR = 'code --wait'`. Paths with spaces should be quoted
  within the editor setting. The editor is invoked without a shell.
* **Sandbox unavailable:** enable execution explicitly, start your local Linux
  Docker engine and install a trusted Python image. The engine must support seccomp
  and resource limits. No host execution fallback exists.
* **AI disabled:** core operation does not require it. Only explicitly installed
  and consented provider plugins are loaded.

## Recovery boundaries

Atomic replacement protects snapshots; a durable transaction journal coordinates
generated files with state. The next state read rolls a pending transaction forward
only when all destinations match their recorded before/after hashes. If recovery
reports an edited destination, preserve that file and the journal; restore the
expected before/after content only after inspecting both. Never delete the journal
to suppress a conflict. Restore blocks while a transaction is pending.

Backups cannot reconstruct workspace source or changes that were never saved.
A hostile local process with the same filesystem privileges is outside the threat
model; use OS permissions and trusted repositories.
