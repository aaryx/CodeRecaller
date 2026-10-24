"""Advanced analytics engine with forgetting curves, time-of-day analysis,
difficulty ratings, learning velocity, weakness detection, and achievements."""

from collections import Counter
from datetime import datetime, timedelta
from statistics import mean, median, stdev

from coderecall.domain.clock import instant
from coderecall.domain.models import Achievement, Problem, State


def due(state: State, now: datetime, overdue: bool = False) -> list[Problem]:
    return sorted(
        [
            p
            for p in state.problems.values()
            if not p.archived
            and state.schedules[p.id].state != "SUSPENDED"
            and (
                instant(state.schedules[p.id].next_review).date() < now.date()
                if overdue
                else instant(state.schedules[p.id].next_review) <= now
            )
        ],
        key=lambda p: instant(state.schedules[p.id].next_review),
    )


def streak(
    state: State, now: datetime, qualifying: str = "solution,review,study"
) -> dict[str, object]:
    kinds = set(qualifying.split(","))
    dates = sorted(
        {instant(a.at).date() for a in state.activities if a.kind in kinds and instant(a.at) <= now}
    )
    longest = run = 0
    previous = None
    for date in dates:
        run = run + 1 if previous and date == previous + timedelta(days=1) else 1
        longest = max(longest, run)
        previous = date
    current = 0
    cursor = now.date() if now.date() in dates else now.date() - timedelta(days=1)
    active = set(dates)
    while cursor in active:
        current += 1
        cursor -= timedelta(days=1)
    return {
        "current": current,
        "longest": longest,
        "calendar": [d.isoformat() for d in dates],
        "qualifying": sorted(kinds),
        "timezone": "UTC",
    }


def topic_stats(state: State) -> list[dict[str, object]]:
    solved: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    passed: Counter[str] = Counter()
    topics = {p.id: set(p.topics) for p in state.problems.values() if not p.archived}
    for pid, names in topics.items():
        for name in names:
            solved[name] += int(bool(state.problems[pid].solutions))
    for review in state.reviews:
        for name in topics.get(review.problem_id, set()):
            counts[name] += 1
            passed[name] += int(review.success)
    results: list[dict[str, object]] = []
    for topic in sorted(solved):
        results.append(
            {
                "topic": topic,
                "solved": solved[topic],
                "reviews": counts[topic],
                "failed": counts[topic] - passed[topic],
                "recall_percent": round(passed[topic] / counts[topic] * 100, 1)
                if counts[topic]
                else None,
            }
        )
    return results


def statistics(
    state: State,
    now: datetime,
    qualifying: str = "solution,review,study",
    since: datetime | None = None,
) -> dict[str, object]:
    reviews = [r for r in state.reviews if since is None or instant(r.reviewed_at) >= since]
    activities = [a for a in state.activities if since is None or instant(a.at) >= since]
    solves = [a for a in activities if a.kind == "solution"]
    passed = sum(r.success for r in reviews)
    solve_times = [a.seconds for a in solves if a.seconds > 0]
    review_times = [r.seconds for r in reviews if r.seconds > 0]
    return {
        "problems_solved": len({a.problem_id for a in solves}),
        "solutions_added": len(solves),
        "reviews_completed": len(reviews),
        "recall_percent": round(100 * passed / len(reviews), 1) if reviews else None,
        "failure_percent": round(100 * (len(reviews) - passed) / len(reviews), 1)
        if reviews
        else None,
        "average_solve_seconds": round(mean(solve_times), 1) if solve_times else None,
        "average_review_seconds": round(mean(review_times), 1) if review_times else None,
        "median_solve_seconds": round(median(solve_times), 1) if solve_times else None,
        "median_review_seconds": round(median(review_times), 1) if review_times else None,
        "measured_solve_times": len(solve_times),
        "measured_review_times": len(review_times),
        "assessment_sources": dict(Counter(r.assessment for r in reviews)),
        "hints_used": sum(r.hints for r in reviews),
        "attempts": sum(r.attempts for r in reviews) + sum(a.attempts for a in solves),
        "difficulty": dict(Counter(p.difficulty for p in state.problems.values() if p.solutions)),
        "languages": dict(
            Counter(s.language for p in state.problems.values() for s in p.solutions)
        ),
        "mistakes": dict(Counter(m.category for m in state.mistakes)),
        "streak": streak(state, now, qualifying),
        "overdue": len(due(state, now, overdue=True)),
        "topics": topic_stats(state),
        "learning_velocity": learning_velocity(state, now),
        "difficulty_distribution": difficulty_distribution(state),
        "time_analysis": time_of_day_analysis(state),
        "weakness_report": weakness_detection(state, now),
    }


def recommendations(state: State, now: datetime) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    overdue_ids = {p.id for p in due(state, now, overdue=True)}
    for row in topic_stats(state):
        topic = str(row["topic"])
        recall = row["recall_percent"]
        overdue = sum(p.id in overdue_ids for p in state.problems.values() if topic in p.topics)
        if (isinstance(recall, (int, float)) and recall < 70) or overdue:
            result.append(
                {
                    **row,
                    "overdue": overdue,
                    "reason": f"Recall {recall if recall is not None else 'not measured'}%; {row['failed']} failed reviews; {overdue} overdue problems",
                }
            )
    return sorted(
        result, key=lambda r: (-int(str(r["failed"])), -int(str(r["overdue"])), str(r["topic"]))
    )


# ─── Advanced Analytics ─────────────────────────────────────────────────


def forgetting_curve(state: State, problem_id: str) -> list[dict[str, object]]:
    """Generate forgetting curve data points for a specific problem.

    Returns estimated retention probability at various intervals based on
    the problem's review history and FSRS stability parameter.
    """
    schedule = state.schedules.get(problem_id)
    if not schedule:
        return []

    stability = schedule.stability if schedule.stability > 0 else 1.0
    decay = -0.5
    factor = 19.0 / 81.0
    points: list[dict[str, object]] = []

    for days in [0, 1, 2, 3, 5, 7, 14, 30, 60, 90, 180, 365]:
        retention = (1.0 + factor * days / stability) ** decay
        points.append(
            {
                "days_since_review": days,
                "estimated_retention": round(max(0.0, min(1.0, retention)) * 100, 1),
            }
        )

    # Add actual review data points
    reviews = [r for r in state.reviews if r.problem_id == problem_id]
    for review in reviews:
        overdue_days = review.overdue_seconds / 86400.0
        actual_interval = (
            (schedule.interval_days + overdue_days)
            if review.overdue_seconds
            else schedule.interval_days
        )
        points.append(
            {
                "days_since_review": round(actual_interval, 1),
                "actual_result": "pass" if review.success else "fail",
            }
        )

    return points


def difficulty_distribution(state: State) -> dict[str, object]:
    """Analyze FSRS difficulty ratings across all active problems."""
    difficulties: list[float] = []
    ratings: dict[str, int] = {"easy": 0, "moderate": 0, "hard": 0, "very_hard": 0}

    for pid, schedule in state.schedules.items():
        if pid in state.problems and not state.problems[pid].archived:
            d = schedule.difficulty
            difficulties.append(d)
            if d <= 3.0:
                ratings["easy"] += 1
            elif d <= 5.0:
                ratings["moderate"] += 1
            elif d <= 7.5:
                ratings["hard"] += 1
            else:
                ratings["very_hard"] += 1

    return {
        "distribution": ratings,
        "average": round(mean(difficulties), 2) if difficulties else None,
        "median": round(median(difficulties), 2) if difficulties else None,
        "std_dev": round(stdev(difficulties), 2) if len(difficulties) >= 2 else None,
    }


def time_of_day_analysis(state: State) -> dict[str, object]:
    """Analyze performance patterns by time of day."""
    hourly_reviews: dict[int, list[bool]] = {h: [] for h in range(24)}
    hourly_times: dict[int, list[int]] = {h: [] for h in range(24)}

    for review in state.reviews:
        hour = instant(review.reviewed_at).hour
        hourly_reviews[hour].append(review.success)
        if review.seconds > 0:
            hourly_times[hour].append(review.seconds)

    performance_by_hour: list[dict[str, object]] = []
    for hour in range(24):
        results = hourly_reviews[hour]
        times = hourly_times[hour]
        if results:
            performance_by_hour.append(
                {
                    "hour": hour,
                    "reviews": len(results),
                    "success_rate": round(sum(results) / len(results) * 100, 1),
                    "avg_seconds": round(mean(times), 1) if times else None,
                }
            )

    # Find peak performance hours
    best_hours = sorted(
        [h for h in performance_by_hour if h["reviews"] >= 3],  # type: ignore[operator]
        key=lambda h: (-float(h.get("success_rate", 0)), float(h.get("avg_seconds", 9999))),  # type: ignore[arg-type]
    )[:3]

    return {
        "hourly_performance": performance_by_hour,
        "peak_hours": [h["hour"] for h in best_hours],
        "recommendation": f"Your best performance is around {best_hours[0]['hour']}:00 UTC"
        if best_hours
        else "Not enough data to determine peak hours",
    }


def learning_velocity(state: State, now: datetime) -> dict[str, object]:
    """Track the rate of learning progress over time windows."""
    windows = {
        "last_7_days": now - timedelta(days=7),
        "last_30_days": now - timedelta(days=30),
        "last_90_days": now - timedelta(days=90),
    }
    velocity: dict[str, object] = {}

    for name, since in windows.items():
        reviews_in_window = [r for r in state.reviews if instant(r.reviewed_at) >= since]
        solves_in_window = [
            a for a in state.activities if a.kind == "solution" and instant(a.at) >= since
        ]
        days = max(1, (now - since).days)

        if reviews_in_window:
            passed = sum(r.success for r in reviews_in_window)
            velocity[name] = {
                "reviews": len(reviews_in_window),
                "solves": len(solves_in_window),
                "reviews_per_day": round(len(reviews_in_window) / days, 2),
                "solves_per_day": round(len(solves_in_window) / days, 2),
                "recall_rate": round(passed / len(reviews_in_window) * 100, 1),
                "total_minutes": round(sum(r.seconds for r in reviews_in_window) / 60, 1),
            }
        else:
            velocity[name] = {
                "reviews": 0,
                "solves": len(solves_in_window),
                "reviews_per_day": 0.0,
                "solves_per_day": round(len(solves_in_window) / days, 2),
                "recall_rate": None,
                "total_minutes": 0.0,
            }

    return velocity


def weakness_detection(state: State, now: datetime) -> list[dict[str, object]]:
    """Identify specific areas of weakness for targeted practice.

    Combines topic recall rates, mistake patterns, overdue problems,
    and FSRS difficulty/stability to find weak spots.
    """
    weaknesses: list[dict[str, object]] = []

    # Topic-level weaknesses
    for row in topic_stats(state):
        topic = str(row["topic"])
        recall = row["recall_percent"]
        if isinstance(recall, (int, float)) and recall < 60:
            weaknesses.append(
                {
                    "type": "topic",
                    "name": topic,
                    "severity": "critical" if recall < 40 else "warning",
                    "recall_rate": recall,
                    "reviews": row["reviews"],
                    "suggestion": f"Focus on {topic}: only {recall}% recall rate across {row['reviews']} reviews",
                }
            )

    # Mistake pattern weaknesses
    mistake_categories: Counter[str] = Counter()
    for mistake in state.mistakes:
        mistake_categories[mistake.category] += 1
    for category, count in mistake_categories.most_common(5):
        if count >= 3:
            weaknesses.append(
                {
                    "type": "mistake_pattern",
                    "name": category,
                    "severity": "warning" if count < 5 else "critical",
                    "occurrences": count,
                    "suggestion": f"Recurring '{category}' mistakes ({count} times) — review edge cases",
                }
            )

    # Problems with high FSRS difficulty
    hard_problems = sorted(
        [
            (pid, s)
            for pid, s in state.schedules.items()
            if pid in state.problems
            and not state.problems[pid].archived
            and s.difficulty >= 7.0
            and s.reps >= 2
        ],
        key=lambda x: -x[1].difficulty,
    )[:5]
    for pid, schedule in hard_problems:
        problem = state.problems[pid]
        weaknesses.append(
            {
                "type": "hard_problem",
                "name": problem.title,
                "severity": "info",
                "difficulty_score": schedule.difficulty,
                "lapses": schedule.lapses,
                "suggestion": f"'{problem.title}' has difficulty {schedule.difficulty:.1f} with {schedule.lapses} lapses",
            }
        )

    return weaknesses


def goal_progress(state: State, now: datetime) -> list[dict[str, object]]:
    """Calculate progress toward active goals."""
    results: list[dict[str, object]] = []

    for goal in state.goals:
        if not goal.active:
            continue

        if goal.kind == "daily":
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif goal.kind == "weekly":
            since = now - timedelta(days=now.weekday())
            since = since.replace(hour=0, minute=0, second=0, microsecond=0)
        elif goal.kind == "monthly":
            since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            continue

        if goal.target_type == "reviews":
            current = sum(1 for r in state.reviews if instant(r.reviewed_at) >= since)
        elif goal.target_type == "solves":
            current = sum(
                1 for a in state.activities if a.kind == "solution" and instant(a.at) >= since
            )
        elif goal.target_type == "minutes":
            current = sum(r.seconds for r in state.reviews if instant(r.reviewed_at) >= since) // 60
        elif goal.target_type == "streak":
            s = streak(state, now)
            val = s.get("current", 0)
            current = int(val) if isinstance(val, (int, float, str)) else 0
        else:
            continue

        progress = (
            min(100.0, round(current / goal.target_value * 100, 1)) if goal.target_value else 0.0
        )

        results.append(
            {
                "goal_id": goal.id,
                "kind": goal.kind,
                "target_type": goal.target_type,
                "target_value": goal.target_value,
                "current": current,
                "progress_percent": progress,
                "completed": current >= goal.target_value,
            }
        )

    return results


# ─── Achievement Definitions ────────────────────────────────────────────

ACHIEVEMENT_DEFINITIONS: list[dict[str, str | int]] = [
    {
        "id": "first_solve",
        "name": "🎯 First Blood",
        "description": "Solve your first problem",
        "threshold": 1,
        "type": "solves",
    },
    {
        "id": "solve_10",
        "name": "🔟 Getting Started",
        "description": "Solve 10 problems",
        "threshold": 10,
        "type": "solves",
    },
    {
        "id": "solve_50",
        "name": "⭐ Half Century",
        "description": "Solve 50 problems",
        "threshold": 50,
        "type": "solves",
    },
    {
        "id": "solve_100",
        "name": "💯 Centurion",
        "description": "Solve 100 problems",
        "threshold": 100,
        "type": "solves",
    },
    {
        "id": "solve_500",
        "name": "🏆 Grand Master",
        "description": "Solve 500 problems",
        "threshold": 500,
        "type": "solves",
    },
    {
        "id": "review_10",
        "name": "📝 Reviewer",
        "description": "Complete 10 reviews",
        "threshold": 10,
        "type": "reviews",
    },
    {
        "id": "review_50",
        "name": "🔄 Dedicated Reviewer",
        "description": "Complete 50 reviews",
        "threshold": 50,
        "type": "reviews",
    },
    {
        "id": "review_100",
        "name": "🧠 Memory Master",
        "description": "Complete 100 reviews",
        "threshold": 100,
        "type": "reviews",
    },
    {
        "id": "streak_7",
        "name": "🔥 Week Warrior",
        "description": "7-day streak",
        "threshold": 7,
        "type": "streak",
    },
    {
        "id": "streak_30",
        "name": "🌟 Monthly Champion",
        "description": "30-day streak",
        "threshold": 30,
        "type": "streak",
    },
    {
        "id": "streak_100",
        "name": "💎 Diamond Streak",
        "description": "100-day streak",
        "threshold": 100,
        "type": "streak",
    },
    {
        "id": "streak_365",
        "name": "👑 Year of Code",
        "description": "365-day streak",
        "threshold": 365,
        "type": "streak",
    },
    {
        "id": "master_5",
        "name": "🎓 Scholar",
        "description": "Master 5 problems",
        "threshold": 5,
        "type": "mastered",
    },
    {
        "id": "master_25",
        "name": "🏅 Expert",
        "description": "Master 25 problems",
        "threshold": 25,
        "type": "mastered",
    },
    {
        "id": "topics_5",
        "name": "📚 Well Rounded",
        "description": "Practice 5+ topics",
        "threshold": 5,
        "type": "topics",
    },
    {
        "id": "topics_10",
        "name": "🌐 Polyglot",
        "description": "Practice 10+ topics",
        "threshold": 10,
        "type": "topics",
    },
    {
        "id": "perfect_10",
        "name": "💪 Perfect Ten",
        "description": "10 consecutive successful reviews",
        "threshold": 10,
        "type": "consecutive",
    },
    {
        "id": "speed_demon",
        "name": "⚡ Speed Demon",
        "description": "Solve a problem in under 5 minutes",
        "threshold": 300,
        "type": "speed",
    },
]


def check_achievements(state: State, now: datetime) -> list[Achievement]:
    """Check and return newly unlocked achievements."""
    existing_ids = {a.id for a in state.achievements}
    newly_unlocked: list[Achievement] = []

    solve_count = len({a.problem_id for a in state.activities if a.kind == "solution"})
    review_count = len(state.reviews)
    s_val = streak(state, now).get("current", 0)
    current_streak = int(s_val) if isinstance(s_val, (int, float, str)) else 0
    mastered_count = sum(1 for s in state.schedules.values() if s.state == "MASTERED")
    topic_count = len({t for p in state.problems.values() for t in p.topics if not p.archived})
    fast_solves = any(
        a.seconds > 0 and a.seconds <= 300 for a in state.activities if a.kind == "solution"
    )

    # Check consecutive reviews
    consecutive = 0
    max_consecutive = 0
    for review in state.reviews:
        if review.success:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0

    for defn in ACHIEVEMENT_DEFINITIONS:
        aid = str(defn["id"])
        if aid in existing_ids:
            continue
        threshold = int(defn["threshold"])
        atype = str(defn["type"])

        unlocked = False
        if atype == "solves" and solve_count >= threshold:
            unlocked = True
        elif atype == "reviews" and review_count >= threshold:
            unlocked = True
        elif atype == "streak" and current_streak >= threshold:
            unlocked = True
        elif atype == "mastered" and mastered_count >= threshold:
            unlocked = True
        elif atype == "topics" and topic_count >= threshold:
            unlocked = True
        elif atype == "consecutive" and max_consecutive >= threshold:
            unlocked = True
        elif atype == "speed" and fast_solves:
            unlocked = True

        if unlocked:
            achievement = Achievement(
                id=aid,
                name=str(defn["name"]),
                description=str(defn["description"]),
                unlocked_at=now.isoformat(),
                category="milestone",
            )
            newly_unlocked.append(achievement)

    return newly_unlocked
