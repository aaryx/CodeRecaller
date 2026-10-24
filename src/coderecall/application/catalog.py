import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeAlias
from uuid import NAMESPACE_URL, uuid5

from coderecall.domain.clock import Clock
from coderecall.domain.errors import ValidationError
from coderecall.domain.models import Activity, Problem, Schedule, Solution, State
from coderecall.domain.validation import LANGUAGES, performance, slugify, validate_url
from coderecall.integrations.problems import ProblemMetadata
from coderecall.storage.config import Config
from coderecall.storage.local import LocalStore
from coderecall.storage.paths import safe_path

# Import uses this short-lived index while a transaction is open. Store IDs rather
# than Problem instances: capture_into replaces records as it enriches them, so a
# cached instance would otherwise become stale within the same batch.
IdentityIndex: TypeAlias = dict[tuple[str, str], list[str]]


def identify(state: State, query: str) -> Problem:
    if not query.strip():
        raise ValidationError("Provide a problem ID, slug or title")
    if query in state.problems:
        return state.problems[query]
    matches = [
        p
        for p in state.problems.values()
        if query in {p.id, p.external_id, p.slug} or query.casefold() == p.title.casefold()
    ]
    if len(matches) != 1:
        raise ValidationError(
            "Problem not found or ambiguous; use the full internal ID from problems"
        )
    return matches[0]


def owned_paths(state: State) -> list[str]:
    paths: set[str] = set()
    for problem in state.problems.values():
        for solution in problem.solutions:
            parent = Path(solution.path).parent.as_posix()
            paths.update([solution.path, f"{parent}/README.md", f"{parent}/metadata.json"])
    return sorted(paths)


@dataclass
class Capture:
    metadata: ProblemMetadata
    language: str
    code: str
    approach: str = ""
    time_complexity: str = "unknown"
    space_complexity: str = "unknown"
    note: str = ""
    patterns: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    seconds: int = 0
    attempts: int = 1


def validate_capture(capture: Capture) -> None:
    meta = capture.metadata
    if capture.language not in LANGUAGES:
        raise ValidationError("Unsupported language: " + ", ".join(LANGUAGES))
    if not capture.code.strip() or len(capture.code.encode()) > 2 * 1024 * 1024:
        raise ValidationError("Solution must contain code and be at most 2 MiB")
    if meta.difficulty not in {"unknown", "easy", "medium", "hard"}:
        raise ValidationError("Difficulty must be unknown, easy, medium or hard")
    if not meta.title.strip() or len(meta.title) > 300:
        raise ValidationError("Title must have 1–300 characters")
    slugify(meta.slug or meta.title)
    slugify(meta.platform)
    if meta.external_id:
        slugify(meta.external_id)
    if meta.url:
        validate_url(meta.url, leetcode=meta.platform == "leetcode")
    performance(capture.seconds, capture.attempts, 0, 3)


def documents(problem: Problem, solution: Solution) -> dict[str, bytes]:
    metadata = {
        "schema_version": 1,
        "internal_id": problem.id,
        "platform": problem.platform,
        "external_id": problem.external_id,
        "slug": problem.slug,
        "title": problem.title,
        "url": problem.url,
        "difficulty": problem.difficulty,
        "topics": problem.topics,
        "patterns": problem.patterns,
        "tags": problem.tags,
        "language": solution.language,
        "solution_id": solution.id,
        "approach": solution.approach,
        "time_complexity": solution.time_complexity,
        "space_complexity": solution.space_complexity,
    }
    readme = (
        f"# {problem.title}\n\nDifficulty: {problem.difficulty}\n\n"
        + (f"Problem: {problem.url}\n\n" if problem.url else "")
        + "## Topics\n\n"
        + ("\n".join(f"- {topic}" for topic in problem.topics) or "Not specified")
        + f"\n\n## Approach\n\n{solution.approach or 'Not documented'}\n\n"
        + f"## Complexity\n\nTime: {solution.time_complexity}\n\nSpace: {solution.space_complexity}\n"
    )
    return {
        "README.md": readme.encode(),
        "metadata.json": (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode(),
    }


class Catalog:
    def __init__(self, store: LocalStore, clock: Clock, config: Config):
        self.store, self.clock, self.config = store, clock, config

    @staticmethod
    def identity_index(state: State) -> IdentityIndex:
        index: IdentityIndex = {}
        for problem in state.problems.values():
            Catalog._index_problem(index, problem)
        return index

    @staticmethod
    def _index_problem(index: IdentityIndex, problem: Problem) -> None:
        ids = index.setdefault((problem.platform, problem.external_id or problem.slug), [])
        if problem.id not in ids:
            ids.append(problem.id)

    def capture_into(
        self, state: State, capture: Capture, index: IdentityIndex | None = None
    ) -> tuple[Problem, bool]:
        validate_capture(capture)
        meta = capture.metadata
        slug = slugify(meta.slug or meta.title)
        platform = slugify(meta.platform)
        external_id = (
            str(int(meta.external_id)) if meta.external_id.isdecimal() else meta.external_id
        )
        identity = external_id or slug
        existing = (
            [state.problems[pid] for pid in index.get((platform, identity), [])]
            if index is not None
            else [
                p
                for p in state.problems.values()
                if p.platform == platform and (p.external_id or p.slug) == identity
            ]
        )
        # A URL-only capture later enriched with an external ID must keep its identity.
        if not existing:
            existing = [
                p
                for p in state.problems.values()
                if p.platform == platform
                and p.slug == slug
                and (not p.external_id or not external_id)
            ]
        now = self.clock.now().isoformat()
        problem = (
            deepcopy(existing[0])
            if existing
            else Problem(
                "cr_" + uuid5(NAMESPACE_URL, f"coderecall:{platform}:{identity}").hex,
                platform,
                external_id,
                slug,
                meta.title.strip(),
                meta.url,
                meta.difficulty,
                meta.topics,
                capture.patterns,
                capture.tags,
                now,
                now,
            )
        )
        if len(existing) > 1:
            raise ValidationError(
                "Ambiguous problem identity; resolve duplicate catalog entries first"
            )
        previous = deepcopy(problem)
        if existing:
            problem.external_id = external_id or problem.external_id
            problem.title = meta.title.strip()
            problem.url = meta.url or problem.url
            problem.difficulty = (
                meta.difficulty if meta.difficulty != "unknown" else problem.difficulty
            )
            for name, values in [
                ("topics", meta.topics),
                ("patterns", capture.patterns),
                ("tags", capture.tags),
            ]:
                setattr(problem, name, list(dict.fromkeys([*getattr(problem, name), *values])))
        if capture.note and capture.note not in problem.notes:
            problem.notes.append(capture.note)
        digest = hashlib.sha256(capture.code.encode()).hexdigest()
        duplicate = next(
            (
                s
                for s in problem.solutions
                if s.digest == digest
                and s.language == capture.language
                and s.approach == capture.approach
            ),
            None,
        )
        if duplicate:
            actual = self.store.staged_content(duplicate.path)
            if actual is None or hashlib.sha256(actual).hexdigest() != digest:
                raise ValidationError(
                    "Stored solution changed or is missing; commit/reconcile it before recapturing this version"
                )
            duplicate.time_complexity = (
                capture.time_complexity
                if capture.time_complexity != "unknown"
                else duplicate.time_complexity
            )
            duplicate.space_complexity = (
                capture.space_complexity
                if capture.space_complexity != "unknown"
                else duplicate.space_complexity
            )
            duplicate.labels = list(dict.fromkeys([*duplicate.labels, *capture.labels]))
            self.stage_documents(previous, problem)
            state.problems[problem.id] = problem
            if index is not None:
                self._index_problem(index, problem)
            return problem, False
        sid = (
            "s_"
            + hashlib.sha256((digest + capture.language + capture.approach).encode()).hexdigest()[
                :16
            ]
        )
        external = slugify(problem.external_id).zfill(4) if problem.external_id else platform
        try:
            folder = str(self.config.get("repository.layout")).format(
                language=capture.language,
                external_id=external,
                slug=problem.slug,
                solution_id=sid,
                platform=platform,
            )
        except (KeyError, ValueError, IndexError, AttributeError) as exc:
            raise ValidationError("Invalid repository.layout; use documented placeholders") from exc
        if folder.casefold().startswith(".coderecall"):
            raise ValidationError("Public solution layout cannot use .coderecall")
        filename = LANGUAGES[capture.language][1]
        relative = f"{folder}/{filename}"
        safe_path(self.store.root, relative)
        solution = Solution(
            sid,
            capture.language,
            relative,
            capture.approach,
            capture.time_complexity,
            capture.space_complexity,
            now,
            now,
            digest,
            capture.labels,
        )
        problem.solutions.append(solution)
        writes = {
            relative: (None, capture.code.encode()),
            **self.document_changes(previous, problem),
        }
        self.store.stage_files(writes)
        problem.solved_at = now
        state.problems[problem.id] = problem
        from datetime import timedelta

        if problem.id not in state.schedules:
            schedule = Schedule(problem.id, (self.clock.now() + timedelta(days=1)).isoformat())
            if not self.config.get("revision.enabled"):
                schedule.state = "SUSPENDED"
            state.schedules[problem.id] = schedule
        state.activities.append(
            Activity("solution", problem.id, now, capture.seconds, capture.attempts)
        )
        if index is not None:
            self._index_problem(index, problem)
        return problem, True

    def document_changes(
        self, previous: Problem, problem: Problem
    ) -> dict[str, tuple[bytes | None, bytes]]:
        old = {s.id: s for s in previous.solutions}
        writes: dict[str, tuple[bytes | None, bytes]] = {}
        for solution in problem.solutions:
            before = documents(previous, old[solution.id]) if solution.id in old else {}
            parent = Path(solution.path).parent.as_posix()
            for name, data in documents(problem, solution).items():
                if before.get(name) != data:
                    writes[f"{parent}/{name}"] = (before.get(name), data)
        return writes

    def stage_documents(self, previous: Problem, problem: Problem) -> None:
        self.store.stage_files(self.document_changes(previous, problem))

    def add(self, capture: Capture) -> tuple[Problem, bool]:
        with self.store.transaction() as state:
            return self.capture_into(state, capture)

    def annotate(self, query: str, note: str) -> None:
        if not note.strip():
            raise ValidationError("Note cannot be blank")
        with self.store.transaction() as state:
            identify(state, query).notes.append(note)

    def archive(self, query: str, archived: bool) -> None:
        with self.store.transaction() as state:
            problem = identify(state, query)
            if problem.archived != archived:
                problem.archived = archived
                state.activities.append(
                    Activity(
                        "archive" if archived else "unarchive",
                        problem.id,
                        self.clock.now().isoformat(),
                    )
                )
