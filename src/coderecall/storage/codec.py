"""Strict schema decoding without a runtime validation dependency."""

import dataclasses
import json
from functools import lru_cache
from typing import TypeVar, cast, get_args, get_origin, get_type_hints

from coderecall.domain.clock import instant
from coderecall.domain.errors import StateCorruptionError, ValidationError
from coderecall.domain.models import State
from coderecall.domain.validation import LANGUAGES, relative_path

T = TypeVar("T")
MAX_STATE_BYTES = 64 * 1024 * 1024


@lru_cache(maxsize=32)
def record_hints(kind: type) -> dict[str, object]:
    return get_type_hints(kind)


def _decode(kind: object, value: object) -> object:
    origin = get_origin(kind)
    args = get_args(kind)
    if origin is list:
        if not isinstance(value, list):
            raise ValueError("Expected list")
        return [_decode(args[0], item) for item in value]
    if origin is dict:
        if not isinstance(value, dict):
            raise ValueError("Expected mapping")
        return {_decode(args[0], k): _decode(args[1], v) for k, v in value.items()}
    if isinstance(kind, type) and dataclasses.is_dataclass(kind):
        if not isinstance(value, dict):
            raise ValueError("Expected record")
        hints = record_hints(kind)
        if set(value) != set(hints):
            raise ValueError("Missing or unknown record fields")
        return kind(**{k: _decode(hints[k], v) for k, v in value.items()})
    if kind is float and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if type(value) is not kind:
        raise ValueError("Unexpected field type")
    return value


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def json_object(raw: bytes) -> dict[str, object]:
    if len(raw) > MAX_STATE_BYTES:
        raise StateCorruptionError("State exceeds the 64 MiB snapshot limit")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
        if not isinstance(value, dict):
            raise ValueError("Expected JSON object")
        return cast(dict[str, object], value)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise StateCorruptionError(
            "Malformed JSON; use doctor or restore a validated backup"
        ) from exc


def decode_record(kind: type[T], value: object) -> T:
    try:
        return cast(T, _decode(kind, value))
    except (TypeError, ValueError, KeyError, RecursionError) as exc:
        raise StateCorruptionError(f"Invalid {kind.__name__} schema: {exc}") from exc


def decode_state(raw: bytes) -> State:
    data = json_object(raw)
    if type(data.get("schema_version")) is not int or data.get("schema_version") != 1:
        raise StateCorruptionError(
            "Unsupported state schema; run doctor (never downgrade newer state)"
        )
    # Migrate: add new fields with defaults if they are missing from older state files
    _migrate_state_fields(data)

    if set(data) != {f.name for f in dataclasses.fields(State)}:
        raise StateCorruptionError("State snapshot has missing or unknown top-level fields")
    state = decode_record(State, data)
    try:
        paths: set[str] = set()
        identities: set[tuple[str, str]] = set()
        for key, problem in state.problems.items():
            if key != problem.id or not key.startswith("cr_"):
                raise ValueError("Invalid problem identity")
            identity = (problem.platform, problem.external_id or problem.slug)
            if identity in identities:
                raise ValueError("Duplicate problem identity")
            identities.add(identity)
            if problem.difficulty not in {"unknown", "easy", "medium", "hard"}:
                raise ValueError("Invalid difficulty")
            instant(problem.created_at)
            if problem.solved_at:
                instant(problem.solved_at)
            for solution in problem.solutions:
                if solution.language not in LANGUAGES:
                    raise ValueError("Invalid solution language")
                relative_path(solution.path)
                if (
                    solution.path.casefold().startswith(".coderecall/")
                    or solution.path.casefold() in paths
                ):
                    raise ValueError("Invalid/duplicate public solution path")
                paths.add(solution.path.casefold())
                instant(solution.created_at)
                instant(solution.modified_at)
        if set(state.schedules) != set(state.problems):
            raise ValueError("Each problem must have exactly one schedule")
        for key, schedule in state.schedules.items():
            if schedule.problem_id != key or not 1 <= schedule.interval_days <= 365:
                raise ValueError("Invalid schedule reference/interval")
            if schedule.state not in {"NEW", "LEARNING", "REVIEW", "SUSPENDED", "MASTERED"}:
                raise ValueError("Invalid schedule state")
            if not 0 <= schedule.confidence <= 5 or schedule.successes < 0:
                raise ValueError("Invalid schedule performance")
            # Validate FSRS fields
            if not 0.0 <= schedule.difficulty <= 10.0:
                raise ValueError("Invalid FSRS difficulty")
            if schedule.stability < 0.0:
                raise ValueError("Invalid FSRS stability")
            if schedule.reps < 0 or schedule.lapses < 0:
                raise ValueError("Invalid FSRS reps/lapses")
            instant(schedule.next_review)
            if schedule.last_review:
                instant(schedule.last_review)
        for review in state.reviews:
            if review.problem_id not in state.problems:
                raise ValueError("Dangling review reference")
            from coderecall.domain.validation import performance

            performance(review.seconds, review.attempts, review.hints, review.confidence)
            instant(review.reviewed_at)
            instant(review.original_due)
            if review.overdue_seconds < 0:
                raise ValueError("Invalid overdue duration")
            if not 0 <= review.rating <= 4:
                raise ValueError("Invalid review rating")
        if len({r.id for r in state.reviews}) != len(state.reviews):
            raise ValueError("Duplicate review identities")
        for mistake in state.mistakes:
            if mistake.problem_id not in state.problems:
                raise ValueError("Dangling mistake reference")
            instant(mistake.created_at)
            if mistake.severity not in {"low", "medium", "high"}:
                raise ValueError("Invalid mistake severity")
        for activity in state.activities:
            instant(activity.at)
            if activity.seconds < 0 or activity.attempts < 1:
                raise ValueError("Invalid activity performance")
            if activity.problem_id and activity.problem_id not in state.problems:
                raise ValueError("Dangling activity reference")
        for key, recall in state.recalls.items():
            if key != recall.id or recall.problem_id not in state.problems:
                raise ValueError("Invalid recall reference")
            relative_path(recall.workspace)
            if not recall.workspace.startswith(".coderecall/workspaces/"):
                raise ValueError("Invalid recall workspace")
            instant(recall.started_at)
            if recall.paused_at:
                instant(recall.paused_at)
            if (
                recall.mode not in {"recall", "interview", "solve"}
                or not 0 <= recall.hints <= 5
                or recall.paused_seconds < 0
                or not 1 <= recall.minutes <= 240
            ):
                raise ValueError("Invalid recall performance")
        active = [r.problem_id for r in state.recalls.values() if not r.completed]
        if len(active) != len(set(active)):
            raise ValueError("Multiple active recalls for one problem")
        for key, session in state.sessions.items():
            if key != session.id:
                raise ValueError("Invalid session identity")
            instant(session.started_at)
            if session.ended_at:
                instant(session.ended_at)
                if instant(session.ended_at) < instant(session.started_at):
                    raise ValueError("Session ends before it starts")
        # Validate goals
        for goal in state.goals:
            if goal.kind not in {"daily", "weekly", "monthly"}:
                raise ValueError("Invalid goal kind")
            if goal.target_type not in {"reviews", "solves", "minutes", "streak"}:
                raise ValueError("Invalid goal target type")
            if goal.target_value < 1:
                raise ValueError("Goal target must be positive")
            instant(goal.created_at)
        # Validate achievements
        for achievement in state.achievements:
            instant(achievement.unlocked_at)
    except (ValueError, ValidationError) as exc:
        raise StateCorruptionError(f"Invalid state: {exc}") from exc
    return state


def _migrate_state_fields(data: dict[str, object]) -> None:
    """Add default values for fields introduced in newer versions.

    This enables reading older state files without requiring an explicit migration step.
    """
    data.setdefault("goals", [])
    data.setdefault("achievements", [])

    # Migrate schedule entries to include FSRS fields
    schedules = data.get("schedules")
    if isinstance(schedules, dict):
        for schedule in schedules.values():
            if isinstance(schedule, dict):
                schedule.setdefault("difficulty", 5.0)
                schedule.setdefault("stability", 1.0)
                schedule.setdefault("reps", 0)
                schedule.setdefault("lapses", 0)

    # Migrate review entries to include rating
    reviews = data.get("reviews")
    if isinstance(reviews, list):
        for review in reviews:
            if isinstance(review, dict):
                review.setdefault("rating", 0)


def encode_state(state: State) -> bytes:
    raw = (json.dumps(dataclasses.asdict(state), ensure_ascii=False, indent=2) + "\n").encode()
    decode_state(raw)
    return raw
