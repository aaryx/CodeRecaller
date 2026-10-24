from dataclasses import replace
from datetime import timedelta

import pytest

from coderecall.domain.analytics import due, recommendations, streak, topic_stats
from coderecall.domain.clock import instant
from coderecall.domain.errors import ValidationError
from coderecall.domain.models import Activity, Review, Schedule, State
from coderecall.domain.validation import slugify
from coderecall.revision.scheduler import SimpleIntervalScheduler


def test_schedule_success_failure_hints_and_bounds(clock):
    scheduler = SimpleIntervalScheduler()
    prior = Schedule("cr_a", clock.now().isoformat())
    review = Review(
        "r_a", "cr_a", clock.now().isoformat(), prior.next_review, 0, True, 300, 1, 0, 5
    )
    for _ in range(20):
        updated = scheduler.schedule(prior, review, clock.now())
        assert 1 <= updated.interval_days <= 365
        assert instant(updated.next_review) > clock.now()
        prior = updated
    assert prior.state == "MASTERED"
    failed = scheduler.schedule(prior, replace(review, success=False), clock.now())
    assert failed.interval_days == 1 and failed.successes == 0
    hinted = scheduler.schedule(prior, replace(review, hints=5), clock.now())
    assert hinted.interval_days == 1 and hinted.state == "LEARNING"
    with pytest.raises(ValidationError):
        scheduler.schedule(prior, replace(review, confidence=6), clock.now())


def test_streak_genuine_utc_days(clock):
    state = State()
    for day in [-5, -4, -3, -1, 0]:
        state.activities.append(
            Activity("solution", "", (clock.now() + timedelta(days=day)).isoformat())
        )
    state.activities.append(Activity("stats", "", (clock.now() - timedelta(days=2)).isoformat()))
    result = streak(state, clock.now())
    assert result["current"] == 2 and result["longest"] == 3
    clock.value += timedelta(days=1)
    assert streak(state, clock.now())["current"] == 2
    clock.value += timedelta(days=1)
    assert streak(state, clock.now())["current"] == 0


def test_revision_due_overdue_pause_idempotency(project, capture, clock):
    problem, _ = project.catalog.add(capture)
    assert not due(project.store.read(), clock.now())
    clock.value += timedelta(days=3)
    assert due(project.store.read(), clock.now())[0].id == problem.id
    attempt = project.recall.start()
    rid = attempt["recall_id"]
    assert "private-memory" not in str(attempt) and "return [0, 1]" not in str(attempt)
    assert (project.root / attempt["workspace"]).read_text() == ""
    clock.value += timedelta(seconds=60)
    project.recall.pause(rid)
    clock.value += timedelta(seconds=600)
    project.recall.pause(rid, resume=True)
    clock.value += timedelta(seconds=30)
    result = project.recall.submit(rid, False, 2, mistake="edge case")
    assert result["review"]["seconds"] == 90
    assert result["review"]["overdue_seconds"] >= 2 * 86400
    assert result["schedule"]["interval_days"] == 1
    assert project.recall.submit(rid, True, 5)["already_recorded"]
    assert len(project.store.read().reviews) == 1
    assert topic_stats(project.store.read())[0]["recall_percent"] == 0
    assert recommendations(project.store.read(), clock.now())


def test_hint_interview_and_schedule_controls(project, capture, clock):
    p, _ = project.catalog.add(capture)
    attempt = project.recall.start(p.id, "interview")
    with pytest.raises(ValidationError):
        project.recall.hint(attempt["recall_id"], True)
    with pytest.raises(ValidationError):
        project.recall.submit(attempt["recall_id"], True, 5)
    project.recall.submit(
        attempt["recall_id"], True, 5, approach="hash map", complexity="O(n)", verbal=True
    )
    project.recall.schedule_action(p.id, "suspend")
    clock.value += timedelta(days=30)
    assert not due(project.store.read(), clock.now())
    project.recall.schedule_action(p.id, "resume")
    assert due(project.store.read(), clock.now())
    project.recall.schedule_action(p.id, "reschedule", 7)
    assert not due(project.store.read(), clock.now())
    project.recall.schedule_action(p.id, "reset")
    assert len(project.store.read().reviews) == 1


def test_sessions_do_not_award_idle_activity(project, clock):
    project.recall.session("start")
    clock.value += timedelta(minutes=10)
    project.recall.session("stop")
    assert not project.store.read().activities
    project.recall.session("start")
    clock.value += timedelta(minutes=2)
    project.recall.session("stop", "Studied tree invariants")
    assert project.store.read().activities[0].kind == "study"


@pytest.mark.parametrize(
    "title,expected",
    [("Two Sum", "two-sum"), ("  三数之和  ", "三数之和"), ("Binary_Search", "binary_search")],
)
def test_slug(title, expected):
    assert slugify(title) == expected
