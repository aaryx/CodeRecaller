# CLI reference

Global flags precede the command: `--json`, `--quiet`, `--verbose`, `--no-color`,
`--non-interactive`, `--dry-run`, `--version`, `--help`. Each command also has
`--help`. JSON mode never prompts and emits JSON only on stdout, including errors
and help. Explicit confirmations use `--yes`. Debug diagnostics go to stderr.

## Catalog

* `init [--git-init]`: initialize at the Git root; Git is optional.
* `add [--title TEXT] [--url URL] --file PATH`: capture local code. `--stdin`
  reads code from stdin and requires `--language`. `--fetch` explicitly requests
  public LeetCode metadata; failure falls back to supplied/URL-derived fields.
  `--platform`, `--external-id`, `--difficulty`, `--topics`, `--patterns`,
  `--tags`, `--labels`, `--approach`, `--time-complexity`, `--space-complexity`,
  `--note`, `--seconds`, `--attempts`, `--no-commit` are supported. Comma-separated
  fields are lists. Approach/complexity are public; notes are private.
* `problems`: filter `--difficulty`, `--topic`, `--pattern`, `--language`, `--due`,
  `--failed` (latest review failed), `--unreviewed`, `--overdue`, `--archived`.
* `problem ID`: metadata, schedule and private notes, not source contents.
* `search QUERY`: local substring search, including notes.
* `edit ID`: open the latest stored solution using the configured editor.
* `import DIRECTORY [--dry-run] [--yes]`: preview then copy recognized solutions
  into the configured layout. Unrecognized/invalid files are reported. Files
  are never executed. Without metadata, numbered filenames are **custom**
  problems rather than assumed LeetCode identities.
* `note ID --text TEXT [--hint-level 1..4]`: local note or progressive hint.
* `mistake ID TEXT [--category edge-case] [--severity medium]`: private mistake.
* `archive ID [--undo]`: exclude/include a problem without deleting history.
* `random [--seed N] [--weak] [--unsolved]` plus difficulty/topic/pattern/language.
  Unsolved selects catalog entries without solutions; capture/import normally
  creates solved entries, so this filter may legitimately be empty.
* `analyze FILE [--time-complexity O(n)] [--space-complexity O(n)]`: report
  user-supplied complexity, never guess or execute.

## Learning

* `today`: due queue, weak topics, suggested new work and estimate basis.
* `revise [ID]`: start/resume active recall (earliest due when ID omitted).
* `solve ID`: a blank timed attempt on a catalog problem.
* `interview [ID] [--minutes 30] [--seed N]`: interview with hints disabled.
  The budget is guidance; elapsed time is measured, not a hard process deadline.
* `recall submit RECALL_ID --result pass|fail --confidence 1..5`: record a
  self-assessment; optional `--attempts`, `--seconds`, `--note`, `--mistake`,
  `--approach`, `--complexity`. Interview requires the last two. Repeated
  submission of a recorded ID returns the original review.
  A pass requires code saved in the workspace. Explicit `--verbal --approach TEXT`
  records explanation-only self-assessment without code and labels it accordingly.
* `recall hint RECALL_ID [--reveal]`: progressive hints; reveal counts as level 5.
* `recall pause RECALL_ID`, `recall resume RECALL_ID`: exclude paused time.
* `recall compare RECALL_ID`: unified diff after submission, plus user explanations.
* `recall cancel RECALL_ID`: abandon without awarding a review; preserve workspace.
* `recall capture RECALL_ID --yes`: promote a successful submitted attempt to public
  solution code, with optional configured review commit. Notes/metrics stay private.
* `schedule skip|suspend|resume|reschedule|reset ID [--days N]`: explicit,
  recorded changes; reset preserves review history.
* `session start|stop|status [--note TEXT]`: study session. Stop records genuine
  work; idle sessions count only with a meaningful note and at least 60 seconds.
* `stats`, `topics`, `streak`, `summary --week`: measured local analytics.

## Project and integrations

* `status`, `doctor [--migrate --yes]`, `version`.
* `config show|get|set [KEY] [VALUE]`.
* `git status`, `git diff`, `git commit [--message TEXT] [--yes]`, `git push --yes`.
* `sync [--yes] [--no-fetch]`: explicit fetch, plan, confirm, fast-forward/push.
  Global `--dry-run` does not fetch and reflects cached tracking refs.
  `--import-solutions` also imports catalog metadata after Git synchronization.
  The exact previewed commit refs are rechecked before applying the plan.
* `github connect|disconnect|status`: `gh` required, explicit network activity.
* `backup`: content-addressed, idempotent private backup under `.coderecall/backups`.
* `restore ARCHIVE --yes`: validated learning snapshot restore, recovery copy first.
  Configuration is preserved. Use `archive --undo` to restore an archived problem.
* `export [--format json|csv|markdown] [--output PATH]`: no overwrite of different
  existing content. JSON includes full history; CSV/Markdown summarize catalog.
* `ai status` or `ai explain|hint|complexity|alternative|readme|interview|quality
  --file PATH --consent`: configured trusted plugin only, generated text only.
* `run FILE --yes`: optional restricted Linux Docker execution of an explicit
  Python script. Disabled/unavailable sandbox returns exit 8. No host fallback.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | General/filesystem error |
| 2 | Invalid command/argument usage |
| 3 | Configuration or uninitialized project |
| 4 | Authentication |
| 5 | Sync conflict/divergence/dirty tree |
| 6 | Provider/executable unavailable or timeout |
| 7 | Input validation/unsafe operation |
| 8 | Sandbox unavailable/failure |
| 9 | Corrupt/incompatible state or failed doctor |
| 10 | Concurrent state lock |
| 11 | Git operation failure |
| 130 | User cancellation |

A saved capture with failed post-save Git automation exits 0 and includes
`git_warning` and `local_saved: true`. Explicit Git commands return failure codes.
