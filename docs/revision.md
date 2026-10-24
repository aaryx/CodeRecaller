# Revision engine and metrics

All dates are aware UTC timestamps. There is no background scheduler. Each CLI
invocation uses an injectable clock and compares next_review with now. Due means
timestamp <= now; overdue means a due date before today's UTC date. Archived and
suspended problems are excluded. Review records preserve the original due
timestamp, actual completion, elapsed seconds and overdue duration.

First capture schedules one day later. For a review:

* Failure, confidence 1, or hint level >=4: one day.
* Other non-independent success: previous interval clamped to 1–3 days.
* Independent success (success, zero hints, confidence >=3): multiply previous
  interval by `1.6 + confidence * 0.15`; subtract 0.3 for multiple attempts and
  0.2 for elapsed time over one hour. Round and clamp to 2–365 days.
* Five consecutive independent successes and interval >=30 days labels the
  problem MASTERED. This is a transparent product label, not scientific proof.

States are NEW, LEARNING, REVIEW, SUSPENDED, MASTERED. DUE/OVERDUE are derived,
not stale stored flags. Overdue time is recorded but does not earn extra interval
credit. The strategy is deterministic and SM2-inspired, not an implementation
of SM2 or FSRS. Confidence is self-reported.

Hints 1–4 use user-supplied progressive hints when present; otherwise they offer
generic recall prompts, clearly labeled as such. Level 5 reads the old solution
only after explicit reveal. Interview disables both hints and reveal. Diffing is
allowed after submission and does not establish correctness.

## Statistics

Recall rate = successful completed reviews / all completed reviews. Failure rate
is its complement. No reviews means null/unmeasured, not 0% or 100%. Topic metrics
aggregate actual reviews on non-archived problems. Recommendations select topics
with recall below 70% or overdue work, then order by failures and overdue count;
the reason is printed. No AI score is involved. Mistakes aggregate by category.

Streaks count configured genuine activity kinds, one day per UTC date. The current
streak may end today or yesterday. CLI reads and Git commits do not count. A note
on an idle study session must accompany at least 60 seconds to qualify. Input
times of zero represent unmeasured/unspecified time and are excluded from time
averages. Counts of measured durations and assessment sources are included.

Weekly summaries filter solves/reviews to the last seven days; distributions,
topic context, overdue work and streak retain the full catalog/history context.
