# Lightweight plugin SDK

Plugins are trusted installed Python code. CodeRecall never downloads them,
discovers remote code or loads all entry points at startup. Configuration is
explicit enablement. Review plugins like any other installed program.

## Scheduler example

Create an ordinary Python package with:

```toml
[project.entry-points."coderecall.schedulers"]
conservative = "my_scheduler:ConservativeScheduler"
```

```python
from dataclasses import replace
from datetime import datetime, timedelta
from coderecall.domain.models import Review, Schedule


class ConservativeScheduler:
    def schedule(self, previous: Schedule, review: Review, now: datetime) -> Schedule:
        days = 3 if review.success and review.hints == 0 else 1
        return replace(
            previous,
            next_review=(now + timedelta(days=days)).isoformat(),
            interval_days=days,
            last_review=now.isoformat(),
            state="REVIEW" if days == 3 else "LEARNING",
            confidence=review.confidence,
        )
```

Install deliberately, then `coderecall config set revision.scheduler conservative`.
The returned snapshot is schema-validated before persistence. Inject a fake clock
when testing your scheduler; do not read wall-clock time in the algorithm.

## AI

The bundled `openai` provider is selected with `ai.plugin=openai`; see
[optional adapters](optional.md). Other names select installed entry points.

Register `coderecall.ai` entry points implementing
`generate(instruction: str, untrusted_content: str) -> str`. Configure
`ai.plugin=NAME` and `ai.enabled=true`. Each request still needs `--consent`.
Credentials are the provider's responsibility and must use OS credential storage
or explicit environment inputs, never CodeRecall project files. Implement timeouts,
bounded retry, size limits and provider-specific disclosure policies.

The application passes source separately as untrusted content, validates the
response type/size, marks it AI-generated, and only prints text. There is no tool
dispatch or direct file/Git action from output. Prompt instructions alone are not
a security boundary; the lack of action execution is the important boundary.

## Other ports

`ProblemProvider`, `GitProvider`, `GitHostingProvider`, `CodeRunner`,
`TemplateProvider` and `Exporter` document adapter contracts. Only scheduler and
AI entry-point loading are currently wired to CLI configuration. Other adapters
are integrated in application composition through normal Python contribution,
not advertised as automatically configurable plugins. See the existing LeetCode,
Git and GitHub adapters for concrete implementations.
