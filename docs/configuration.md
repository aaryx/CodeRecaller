# Configuration

Precedence: command-specific CLI flags > `CODERECALL_SECTION_KEY` environment
variables > `.coderecall/config.toml` > user config > defaults. User configuration
lives at `$XDG_CONFIG_HOME/coderecall/config.toml`, or
`~/.config/coderecall/config.toml` (including Windows). `$VISUAL`, then `$EDITOR`,
are editor fallbacks. Boolean values are `true`/`false`.

```toml
[repository]
layout = "{language}/{external_id}-{slug}/{solution_id}"
editor = "code --wait"

[git]
auto_commit = true
auto_push = false
strategy = "every-solution"
scan_secrets = true

[revision]
enabled = true
scheduler = "simple"
daily_new = 2

[streak]
activities = "solution,review,study"

[execution]
enabled = false
image = "python:3.12-alpine"
timeout = 5

[ai]
enabled = false
plugin = ""
model = "gpt-4.1-mini"
```

Layout supports language, external_id (zero-padded when numeric), slug,
solution_id, platform. Include solution_id to retain alternative approaches.
Different existing files are never overwritten. Git ignores private state,
while generated solution metadata is the selected non-sensitive versioned subset.

`every-solution` captures commit immediately; `manual` only explicit commits;
`daily` batches through `session stop` at most once per UTC day. In
`solution-and-review`, capture behaves like every-solution; `recall capture ID --yes`
promotes the submitted attempt and commits genuine code changes. Review metrics
remain private. No private study activity produces fake commits.

`revision.enabled=false` suspends new schedules. Existing schedules require
explicit `schedule suspend`; changing defaults never silently rewrites history.

Execution settings configure the optional Linux Docker runner; the daemon and
trusted Python image must already exist. AI loads either the bundled `openai`
adapter or a named installed plugin only on an explicitly consented request.
See [optional adapters](optional.md). Streak kinds are restricted to genuine
solution/review/study activity; Git commits cannot be configured to count.

Unknown keys are rejected. Do not put passwords, tokens or API keys in any project
file. Git credentials belong to Git's credential manager; GitHub authentication
is delegated to `gh`. Choose secure OS credential storage when configuring it.
