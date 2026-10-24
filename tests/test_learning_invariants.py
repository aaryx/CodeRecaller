from datetime import UTC, datetime, timedelta

from coderecall.domain.analytics import (
    difficulty_distribution,
    forgetting_curve,
    goal_progress,
    learning_velocity,
    statistics,
    time_of_day_analysis,
    weakness_detection,
)
from coderecall.domain.clock import instant
from coderecall.domain.models import (
    Activity,
    Goal,
    Mistake,
    Problem,
    Review,
    Schedule,
    Solution,
    State,
)
from coderecall.revision.scheduler import FSRSScheduler, SimpleIntervalScheduler


def make_problem(
    pid: str = "p1", title: str = "Two Sum", topics: list[str] | None = None
) -> Problem:
    return Problem(
        id=pid,
        platform="leetcode",
        external_id="1",
        slug="two-sum",
        title=title,
        url="https://leetcode.com/problems/two-sum/",
        difficulty="easy",
        topics=topics or ["array", "hash-table"],
        patterns=["hash-map"],
        tags=["blind75"],
        created_at="2026-01-01T12:00:00+00:00",
        solutions=[
            Solution(
                id="s1",
                language="python",
                path=f"python/{pid}/solution.py",
                approach="hash map",
                time_complexity="O(n)",
                space_complexity="O(n)",
                created_at="2026-01-01T12:00:00+00:00",
                modified_at="2026-01-01T12:00:00+00:00",
                digest="abc",
            )
        ],
    )


# ---------------------------------------------------------------------------
# FSRS Scheduler Invariants & Correctness
# ---------------------------------------------------------------------------


def test_fsrs_initial_review_ratings():
    scheduler = FSRSScheduler(desired_retention=0.9)
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    init_sched = Schedule(problem_id="p1", next_review=now.isoformat())

    # Rating 1: Again (failed review)
    rev_fail = Review("r1", "p1", now.isoformat(), now.isoformat(), 0, False, 120, 1, 0, 1)
    sched_fail = scheduler.schedule(init_sched, rev_fail, now)
    assert sched_fail.interval_days == 1
    assert sched_fail.state == "LEARNING"
    assert sched_fail.reps == 1
    assert sched_fail.lapses == 1

    # Rating 4: Easy (high confidence, zero hints, success)
    rev_easy = Review("r2", "p1", now.isoformat(), now.isoformat(), 0, True, 60, 1, 0, 5)
    sched_easy = scheduler.schedule(init_sched, rev_easy, now)
    assert sched_easy.interval_days >= 3
    assert sched_easy.reps == 1
    assert sched_easy.lapses == 0
    assert sched_easy.stability > sched_fail.stability


def test_fsrs_consecutive_success_expands_intervals_monotonically():
    scheduler = FSRSScheduler()
    clock = datetime(2026, 1, 1, 12, tzinfo=UTC)
    sched = Schedule(problem_id="p1", next_review=clock.isoformat())

    intervals = []
    stabilities = []

    for i in range(6):
        review = Review(f"r_{i}", "p1", clock.isoformat(), sched.next_review, 0, True, 90, 1, 0, 4)
        sched = scheduler.schedule(sched, review, clock)
        intervals.append(sched.interval_days)
        stabilities.append(sched.stability)
        # Advance time to next review
        clock = instant(sched.next_review)

    # Intervals and stabilities must be strictly increasing on repeated easy/good passes
    for i in range(len(intervals) - 1):
        assert intervals[i + 1] >= intervals[i]
        assert stabilities[i + 1] > stabilities[i]

    # After 5+ successes and interval >= 30, state should be MASTERED
    assert sched.state == "MASTERED"


def test_fsrs_lapse_resets_interval_and_increases_lapses():
    scheduler = FSRSScheduler()
    clock = datetime(2026, 1, 1, 12, tzinfo=UTC)
    sched = Schedule(problem_id="p1", next_review=clock.isoformat())

    # Build up 3 successful reviews
    for i in range(3):
        review = Review(f"r_{i}", "p1", clock.isoformat(), sched.next_review, 0, True, 60, 1, 0, 4)
        sched = scheduler.schedule(sched, review, clock)
        clock = instant(sched.next_review)

    assert sched.interval_days > 1
    prior_stability = sched.stability

    # Submit a failed recall (forgot)
    rev_fail = Review("r_fail", "p1", clock.isoformat(), sched.next_review, 0, False, 180, 2, 3, 1)
    sched_after_fail = scheduler.schedule(sched, rev_fail, clock)

    assert sched_after_fail.interval_days == 1
    assert sched_after_fail.state == "LEARNING"
    assert sched_after_fail.lapses == 1
    assert sched_after_fail.reps == 4
    # Stability after lapse must drop compared to prior stability
    assert sched_after_fail.stability < prior_stability


def test_fsrs_handles_naive_datetime_and_backward_clock_safely():
    scheduler = FSRSScheduler()
    # Naive datetime (without tzinfo)
    naive_now = datetime(2026, 1, 1, 12)
    sched = Schedule(
        problem_id="p1",
        next_review="2026-01-05T12:00:00+00:00",
        last_review="2026-01-01T12:00:00+00:00",
    )
    review = Review(
        "r1", "p1", "2026-01-01T12:00:00+00:00", sched.next_review, 0, True, 60, 1, 0, 3
    )

    # Should not raise TypeError: can't subtract offset-naive and offset-aware datetimes
    updated = scheduler.schedule(sched, review, naive_now)
    assert 1 <= updated.interval_days <= 365


def test_simple_scheduler_handles_naive_datetime():
    scheduler = SimpleIntervalScheduler()
    naive_now = datetime(2026, 1, 1, 12)
    sched = Schedule(problem_id="p1", next_review="2026-01-01T12:00:00+00:00")
    review = Review(
        "r1", "p1", "2026-01-01T12:00:00+00:00", sched.next_review, 0, True, 60, 1, 0, 4
    )

    updated = scheduler.schedule(sched, review, naive_now)
    assert updated.interval_days >= 1


# ---------------------------------------------------------------------------
# Analytics Engine: Forgetting Curves, Weaknesses & Distributions
# ---------------------------------------------------------------------------


def test_forgetting_curve_points():
    state = State()
    p = make_problem("p1")
    state.problems["p1"] = p
    state.schedules["p1"] = Schedule(
        problem_id="p1", next_review="2026-01-05T12:00:00+00:00", stability=5.0
    )
    state.reviews.append(
        Review(
            "r1",
            "p1",
            "2026-01-01T12:00:00+00:00",
            "2026-01-01T12:00:00+00:00",
            0,
            True,
            60,
            1,
            0,
            4,
        )
    )

    curve = forgetting_curve(state, "p1")
    assert len(curve) > 10
    # Day 0 retention must be 100%
    assert curve[0]["days_since_review"] == 0
    assert curve[0]["estimated_retention"] == 100.0

    # Retention must decrease over time
    estimations = [pt["estimated_retention"] for pt in curve if "estimated_retention" in pt]
    for i in range(len(estimations) - 1):
        assert estimations[i] >= estimations[i + 1]

    # Nonexistent problem returns empty list
    assert forgetting_curve(state, "nonexistent") == []


def test_difficulty_distribution_analysis():
    state = State()
    p1 = make_problem("p1")
    p2 = make_problem("p2")
    p3 = make_problem("p3")
    state.problems.update({"p1": p1, "p2": p2, "p3": p3})

    state.schedules["p1"] = Schedule("p1", "2026-01-05T00:00:00+00:00", difficulty=2.5)  # easy
    state.schedules["p2"] = Schedule("p2", "2026-01-05T00:00:00+00:00", difficulty=6.0)  # hard
    state.schedules["p3"] = Schedule("p3", "2026-01-05T00:00:00+00:00", difficulty=8.5)  # very hard

    dist = difficulty_distribution(state)
    assert dist["distribution"]["easy"] == 1
    assert dist["distribution"]["moderate"] == 0
    assert dist["distribution"]["hard"] == 1
    assert dist["distribution"]["very_hard"] == 1
    assert dist["average"] is not None
    assert dist["std_dev"] is not None


def test_time_of_day_analysis():
    state = State()

    # Record reviews at hour 10 and hour 14
    state.reviews.append(
        Review(
            "r1",
            "p1",
            "2026-01-01T10:15:00+00:00",
            "2026-01-01T10:00:00+00:00",
            0,
            True,
            60,
            1,
            0,
            4,
        )
    )
    state.reviews.append(
        Review(
            "r2",
            "p1",
            "2026-01-01T10:45:00+00:00",
            "2026-01-01T10:00:00+00:00",
            0,
            True,
            45,
            1,
            0,
            5,
        )
    )
    state.reviews.append(
        Review(
            "r3",
            "p1",
            "2026-01-01T14:30:00+00:00",
            "2026-01-01T14:00:00+00:00",
            0,
            False,
            180,
            2,
            2,
            2,
        )
    )

    analysis = time_of_day_analysis(state)
    hourly = {h["hour"]: h for h in analysis["hourly_performance"]}
    assert 10 in hourly
    assert hourly[10]["reviews"] == 2
    assert hourly[10]["success_rate"] == 100.0

    assert 14 in hourly
    assert hourly[14]["reviews"] == 1
    assert hourly[14]["success_rate"] == 0.0


def test_learning_velocity_windows():
    state = State()
    now = datetime(2026, 1, 15, 12, tzinfo=UTC)

    # Activity 2 days ago (within 7, 30, 90 days)
    recent_date = (now - timedelta(days=2)).isoformat()
    state.activities.append(Activity("solution", "p1", recent_date, seconds=300))
    state.reviews.append(Review("r1", "p1", recent_date, recent_date, 0, True, 120, 1, 0, 4))

    # Activity 15 days ago (within 30 and 90 days, but NOT 7 days)
    mid_date = (now - timedelta(days=15)).isoformat()
    state.activities.append(Activity("solution", "p2", mid_date, seconds=400))
    state.reviews.append(Review("r2", "p2", mid_date, mid_date, 0, False, 180, 1, 0, 2))

    velocity = learning_velocity(state, now)
    assert velocity["last_7_days"]["reviews"] == 1
    assert velocity["last_7_days"]["solves"] == 1

    assert velocity["last_30_days"]["reviews"] == 2
    assert velocity["last_30_days"]["solves"] == 2


def test_weakness_detection_identifies_struggling_topics_and_mistakes():
    state = State()
    now = datetime(2026, 1, 10, 12, tzinfo=UTC)

    # Topic with 100% failure rate
    p_dp = make_problem("p_dp", "Coin Change", topics=["dynamic-programming"])
    state.problems["p_dp"] = p_dp
    state.schedules["p_dp"] = Schedule("p_dp", now.isoformat(), difficulty=8.0, reps=3, lapses=2)

    for i in range(3):
        state.reviews.append(
            Review(f"r_dp_{i}", "p_dp", now.isoformat(), now.isoformat(), 0, False, 200, 2, 3, 1)
        )

    # 3 recurring mistakes in 'off-by-one' category
    for _ in range(3):
        state.mistakes.append(
            Mistake(
                problem_id="p_dp",
                text="boundary error",
                category="off-by-one",
                severity="high",
                created_at=now.isoformat(),
            )
        )

    weaknesses = weakness_detection(state, now)
    types = {w["type"] for w in weaknesses}
    assert "topic" in types
    assert "mistake_pattern" in types
    assert "hard_problem" in types

    topic_w = next(w for w in weaknesses if w["type"] == "topic")
    assert topic_w["name"] == "dynamic-programming"
    assert topic_w["severity"] == "critical"

    mistake_w = next(w for w in weaknesses if w["type"] == "mistake_pattern")
    assert mistake_w["name"] == "off-by-one"


def test_goal_progress_tracking():
    state = State()
    now = datetime(2026, 1, 10, 12, tzinfo=UTC)

    # 5 reviews goal for today
    state.goals.append(
        Goal("g1", kind="daily", target_type="reviews", target_value=5, created_at=now.isoformat())
    )
    # 2 solves goal for this week
    state.goals.append(
        Goal("g2", kind="weekly", target_type="solves", target_value=2, created_at=now.isoformat())
    )

    # Complete 3 reviews today
    for i in range(3):
        state.reviews.append(
            Review(f"r_{i}", "p1", now.isoformat(), now.isoformat(), 0, True, 60, 1, 0, 4)
        )
    # Add 2 solves this week
    state.activities.append(Activity("solution", "p1", now.isoformat()))
    state.activities.append(Activity("solution", "p2", now.isoformat()))

    progress = goal_progress(state, now)
    g1_prog = next(p for p in progress if p["goal_id"] == "g1")
    assert g1_prog["current"] == 3
    assert g1_prog["progress_percent"] == 60.0
    assert g1_prog["completed"] is False

    g2_prog = next(p for p in progress if p["goal_id"] == "g2")
    assert g2_prog["current"] == 2
    assert g2_prog["progress_percent"] == 100.0
    assert g2_prog["completed"] is True


def test_statistics_comprehensive_breakdown():
    state = State()
    now = datetime(2026, 1, 10, 12, tzinfo=UTC)

    p1 = make_problem("p1")
    state.problems["p1"] = p1
    state.schedules["p1"] = Schedule("p1", (now - timedelta(days=2)).isoformat())

    state.activities.append(Activity("solution", "p1", now.isoformat(), seconds=180, attempts=1))
    state.reviews.append(Review("r1", "p1", now.isoformat(), now.isoformat(), 0, True, 90, 1, 0, 5))

    stats = statistics(state, now)
    assert stats["problems_solved"] == 1
    assert stats["reviews_completed"] == 1
    assert stats["recall_percent"] == 100.0
    assert stats["overdue"] == 1
    assert stats["average_solve_seconds"] == 180.0
    assert stats["average_review_seconds"] == 90.0
    assert "python" in stats["languages"]


def test_check_achievements_unlocking_and_deduplication():
    from coderecall.domain.analytics import check_achievements

    state = State()
    now = datetime(2026, 1, 10, 12, tzinfo=UTC)

    # First solve activity in 120s (< 300s)
    p = make_problem("p1")
    state.problems["p1"] = p
    state.activities.append(Activity("solution", "p1", now.isoformat(), seconds=120))

    unlocked = check_achievements(state, now)
    unlocked_ids = {a.id for a in unlocked}
    assert "first_solve" in unlocked_ids
    assert "speed_demon" in unlocked_ids

    # Add the unlocked achievements to state
    state.achievements.extend(unlocked)

    # Running check_achievements again must NOT return duplicates
    new_unlocked = check_achievements(state, now)
    assert len(new_unlocked) == 0
