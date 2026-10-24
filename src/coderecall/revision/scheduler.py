"""FSRS-inspired scheduler with transparent, deterministic intervals.

Implements a simplified Free Spaced Repetition Scheduler (FSRS v4) algorithm
that tracks difficulty, stability, and retrievability per card. Falls back
gracefully: the simple interval scheduler remains available as a named option.
"""

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from coderecall.domain.clock import instant
from coderecall.domain.models import Review, Schedule
from coderecall.domain.validation import performance


class RevisionScheduler(Protocol):
    def schedule(self, previous: Schedule, review: Review, now: datetime) -> Schedule: ...


class SimpleIntervalScheduler:
    """Original SM2-inspired scheduler preserved for backward compatibility."""

    def schedule(self, previous: Schedule, review: Review, now: datetime) -> Schedule:
        performance(review.seconds, review.attempts, review.hints, review.confidence)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        independent = review.success and review.hints == 0 and review.confidence >= 3
        successes = previous.successes + 1 if independent else 0
        if not review.success or review.hints >= 4 or review.confidence == 1:
            interval = 1
        elif not independent:
            interval = max(1, min(3, previous.interval_days))
        else:
            factor = 1.6 + review.confidence * 0.15
            if review.attempts > 1:
                factor -= 0.3
            if review.seconds > 3600:
                factor -= 0.2
            interval = min(365, max(2, round(previous.interval_days * factor)))
        state = (
            "MASTERED"
            if successes >= 5 and interval >= 30
            else "REVIEW"
            if independent
            else "LEARNING"
        )
        return replace(
            previous,
            next_review=(now + timedelta(days=interval)).isoformat(),
            interval_days=interval,
            last_review=now.isoformat(),
            state=state,
            successes=successes,
            confidence=review.confidence,
        )


# FSRS v4 default parameters (w0–w18)
FSRS_PARAMS: list[float] = [
    0.4072,  # w0 — initial stability for "again"
    1.1829,  # w1 — initial stability for "hard"
    3.1262,  # w2 — initial stability for "good"
    15.4722,  # w3 — initial stability for "easy"
    7.2102,  # w4 — difficulty mean reversion
    0.5316,  # w5 — difficulty initial
    1.0651,  # w6 — difficulty weight
    0.0046,  # w7 — stability on fail penalty
    1.5418,  # w8 — stability increase factor
    0.1594,  # w9 — stability decrease factor
    1.0100,  # w10 — stability retrievability bonus
    1.9279,  # w11 — stability difficulty penalty
    0.1100,  # w12 — stability fail factor
    0.2900,  # w13 — stability hard factor
    2.2273,  # w14 — stability good factor
    0.2553,  # w15 — stability easy factor
    0.6817,  # w16 — stability mean reversion strength
    2.0855,  # w17 — stability mean reversion target
    0.5100,  # w18 — stability penalty for short intervals
]

# Desired retention probability
DESIRED_RETENTION: float = 0.9
DECAY: float = -0.5
FACTOR: float = 19 / 81  # (0.9^(1/DECAY) - 1)


def _fsrs_retrievability(stability: float, elapsed_days: float) -> float:
    """Calculate the probability of recall given stability and elapsed time."""
    if stability <= 0:
        return 0.0
    return float((1.0 + FACTOR * elapsed_days / stability) ** DECAY)


def _fsrs_initial_stability(rating: int) -> float:
    """Initial stability depends on the first review rating (1-4)."""
    idx = max(0, min(3, rating - 1))
    return max(0.1, FSRS_PARAMS[idx])


def _fsrs_initial_difficulty(rating: int) -> float:
    """Initial difficulty based on the first review rating."""
    return min(10.0, max(1.0, FSRS_PARAMS[4] - math.exp(FSRS_PARAMS[5] * (rating - 1)) + 1.0))


def _fsrs_next_difficulty(d: float, rating: int) -> float:
    """Update difficulty with mean reversion toward w5."""
    w6 = FSRS_PARAMS[6]
    w7 = FSRS_PARAMS[7]
    d_prime = d - w6 * (rating - 3)
    # Mean reversion
    d_next = w7 * _fsrs_initial_difficulty(4) + (1 - w7) * d_prime
    return min(10.0, max(1.0, d_next))


def _fsrs_next_stability(s: float, d: float, r: float, rating: int, reps: int) -> float:
    """Calculate new stability after a review."""
    if reps == 0:
        return _fsrs_initial_stability(rating)

    if rating == 1:  # Again (lapse)
        w8 = FSRS_PARAMS[8]
        w9 = FSRS_PARAMS[9]
        w10 = FSRS_PARAMS[10]
        w11 = FSRS_PARAMS[11]
        s_new = w11 * (d ** (-w8)) * ((s + 1.0) ** w9 - 1.0) * math.exp(w10 * (1.0 - r))
        return float(max(0.1, min(s, s_new)))
    else:
        # Success path — rating 2 (hard), 3 (good), 4 (easy)
        w12 = FSRS_PARAMS[12]
        w13 = FSRS_PARAMS[13]
        w14 = FSRS_PARAMS[14]
        w15 = FSRS_PARAMS[15]
        w16 = FSRS_PARAMS[16]

        hard_penalty = w15 if rating == 2 else 1.0
        easy_bonus = w16 if rating == 4 else 1.0

        s_new = s * (
            1.0
            + math.exp(w12)
            * (11.0 - d)
            * s ** (-w13)
            * (math.exp(w14 * (1.0 - r)) - 1.0)
            * hard_penalty
            * easy_bonus
        )
        return float(max(s + 0.1, s_new))


def _fsrs_interval(stability: float, desired_retention: float = DESIRED_RETENTION) -> int:
    """Calculate the optimal interval in days for the desired retention."""
    if stability <= 0:
        return 1
    interval = (stability / FACTOR) * (desired_retention ** (1.0 / DECAY) - 1.0)
    return int(min(365, max(1, round(interval))))


def _confidence_to_rating(confidence: int, success: bool, hints: int) -> int:
    """Map self-reported confidence/success/hints to an FSRS rating (1-4).

    1 = Again (forgot), 2 = Hard, 3 = Good, 4 = Easy
    """
    if not success:
        return 1  # Again
    if hints >= 3 or confidence <= 2:
        return 2  # Hard
    if confidence >= 4 and hints == 0:
        return 4  # Easy
    return 3  # Good


class FSRSScheduler:
    """Free Spaced Repetition Scheduler (FSRS v4-inspired).

    Tracks per-card difficulty, stability, and retrievability.
    Provides theoretically optimal intervals for a target retention rate.
    """

    def __init__(self, desired_retention: float = DESIRED_RETENTION):
        self.desired_retention = min(0.99, max(0.70, desired_retention))

    def schedule(self, previous: Schedule, review: Review, now: datetime) -> Schedule:
        performance(review.seconds, review.attempts, review.hints, review.confidence)

        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        rating = _confidence_to_rating(review.confidence, review.success, review.hints)
        prev_due = instant(previous.next_review) if previous.next_review else now
        elapsed_days = (
            max(0.0, (now - prev_due).total_seconds() / 86400.0) if previous.last_review else 0.0
        )

        # Calculate current retrievability
        if previous.reps > 0 and previous.stability > 0:
            r = _fsrs_retrievability(previous.stability, elapsed_days + previous.interval_days)
        else:
            r = 0.0

        # Update difficulty
        if previous.reps == 0:
            difficulty = _fsrs_initial_difficulty(rating)
        else:
            difficulty = _fsrs_next_difficulty(previous.difficulty, rating)

        # Update stability
        stability = _fsrs_next_stability(previous.stability, difficulty, r, rating, previous.reps)

        # Update lapses/reps
        reps = previous.reps + 1
        lapses = previous.lapses + (1 if rating == 1 else 0)

        # Calculate next interval
        interval = _fsrs_interval(stability, self.desired_retention)

        # Determine state
        successes = previous.successes + 1 if rating >= 3 else 0
        if rating == 1:
            state = "LEARNING"
            interval = 1
        elif successes >= 5 and interval >= 30:
            state = "MASTERED"
        elif rating >= 3:
            state = "REVIEW"
        else:
            state = "LEARNING"

        return replace(
            previous,
            next_review=(now + timedelta(days=interval)).isoformat(),
            interval_days=interval,
            last_review=now.isoformat(),
            state=state,
            successes=successes,
            confidence=review.confidence,
            difficulty=round(difficulty, 4),
            stability=round(stability, 4),
            reps=reps,
            lapses=lapses,
        )
