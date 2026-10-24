"""Serializable domain records. All timestamps are timezone-aware ISO 8601."""

from dataclasses import dataclass, field


@dataclass
class Solution:
    id: str
    language: str
    path: str
    approach: str
    time_complexity: str
    space_complexity: str
    created_at: str
    modified_at: str
    digest: str
    labels: list[str] = field(default_factory=list)
    git_ref: str = ""


@dataclass
class Problem:
    id: str
    platform: str
    external_id: str
    slug: str
    title: str
    url: str
    difficulty: str
    topics: list[str]
    patterns: list[str]
    tags: list[str]
    created_at: str
    solved_at: str = ""
    archived: bool = False
    notes: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    solutions: list[Solution] = field(default_factory=list)


@dataclass
class Schedule:
    problem_id: str
    next_review: str
    interval_days: int = 1
    state: str = "NEW"
    last_review: str = ""
    successes: int = 0
    confidence: int = 0
    # FSRS parameters
    difficulty: float = 5.0
    stability: float = 1.0
    reps: int = 0
    lapses: int = 0


@dataclass
class Review:
    id: str
    problem_id: str
    reviewed_at: str
    original_due: str
    overdue_seconds: int
    success: bool
    seconds: int
    attempts: int
    hints: int
    confidence: int
    note: str = ""
    approach: str = ""
    complexity: str = ""
    assessment: str = "self-reported"
    rating: int = 0


@dataclass
class Mistake:
    problem_id: str
    text: str
    category: str
    severity: str
    created_at: str


@dataclass
class Activity:
    kind: str
    problem_id: str
    at: str
    seconds: int = 0
    attempts: int = 1
    detail: str = ""


@dataclass
class Session:
    id: str
    started_at: str
    ended_at: str = ""
    note: str = ""


@dataclass
class Recall:
    id: str
    problem_id: str
    started_at: str
    workspace: str
    mode: str = "recall"
    hints: int = 0
    paused_at: str = ""
    paused_seconds: int = 0
    completed: bool = False
    minutes: int = 30


@dataclass
class Goal:
    id: str
    kind: str  # "daily", "weekly", "monthly"
    target_type: str  # "reviews", "solves", "minutes", "streak"
    target_value: int
    created_at: str
    active: bool = True


@dataclass
class Achievement:
    id: str
    name: str
    description: str
    unlocked_at: str
    category: str = "milestone"


@dataclass
class State:
    schema_version: int = 1
    problems: dict[str, Problem] = field(default_factory=dict)
    schedules: dict[str, Schedule] = field(default_factory=dict)
    reviews: list[Review] = field(default_factory=list)
    mistakes: list[Mistake] = field(default_factory=list)
    activities: list[Activity] = field(default_factory=list)
    sessions: dict[str, Session] = field(default_factory=dict)
    recalls: dict[str, Recall] = field(default_factory=dict)
    sync_status: str = "UNKNOWN"
    goals: list[Goal] = field(default_factory=list)
    achievements: list[Achievement] = field(default_factory=list)
