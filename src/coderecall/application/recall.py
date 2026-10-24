import difflib
import json
from dataclasses import asdict
from datetime import timedelta
from uuid import uuid4

from coderecall.application.catalog import identify
from coderecall.domain.analytics import due
from coderecall.domain.clock import Clock, instant
from coderecall.domain.errors import ValidationError
from coderecall.domain.models import Activity, Mistake, Recall, Review, Schedule, Session, State
from coderecall.domain.validation import LANGUAGES, performance
from coderecall.revision.scheduler import RevisionScheduler
from coderecall.storage.local import LocalStore
from coderecall.storage.paths import create_or_match, safe_path


class RecallService:
    def __init__(self, store: LocalStore, clock: Clock, scheduler: RevisionScheduler):
        self.store, self.clock, self.scheduler = store, clock, scheduler

    def start(self, query: str = "", mode: str = "recall", minutes: int = 30) -> dict[str, object]:
        if mode not in {"recall", "interview", "solve"} or not 1 <= minutes <= 240:
            raise ValidationError("Invalid recall mode/time limit")
        with self.store.transaction() as state:
            queue = due(state, self.clock.now())
            if not query and not queue:
                raise ValidationError("No reviews due. Choose a problem ID to practice early")
            problem = identify(state, query) if query else queue[0]
            if problem.archived or state.schedules[problem.id].state == "SUSPENDED":
                raise ValidationError("Restore/resume the problem before practicing")
            current = next(
                (
                    r
                    for r in state.recalls.values()
                    if r.problem_id == problem.id and not r.completed
                ),
                None,
            )
            if current is not None and current.mode != mode:
                raise ValidationError(
                    f"An active {current.mode} attempt already exists; finish or cancel it before starting {mode}"
                )
            if current is None:
                rid = "r_" + uuid4().hex
                language = problem.solutions[-1].language if problem.solutions else "python"
                workspace = f".coderecall/workspaces/{rid}/{LANGUAGES[language][1]}"
                create_or_match(safe_path(self.store.root, workspace), b"")
                if problem.solutions:
                    baseline = problem.solutions[-1]
                    source = safe_path(self.store.root, baseline.path)
                    if source.stat().st_size > 2 * 1024 * 1024:
                        raise ValidationError("Previous solution exceeds recall size limit")
                    snapshot = {
                        "source": source.read_text(encoding="utf-8"),
                        "approach": baseline.approach,
                        "complexity": baseline.time_complexity,
                        "solution_id": baseline.id,
                    }
                    create_or_match(
                        safe_path(self.store.root, f".coderecall/workspaces/{rid}/baseline.json"),
                        json.dumps(snapshot, ensure_ascii=False).encode(),
                    )
                current = Recall(
                    rid, problem.id, self.clock.now().isoformat(), workspace, mode, minutes=minutes
                )
                state.recalls[rid] = current
            elif current.paused_at:
                current.paused_seconds += max(
                    0, int((self.clock.now() - instant(current.paused_at)).total_seconds())
                )
                current.paused_at = ""
            return {
                "recall_id": current.id,
                "problem_id": problem.id,
                "title": problem.title,
                "difficulty": problem.difficulty,
                "topics": problem.topics,
                "url": problem.url,
                "last_review": state.schedules[problem.id].last_review or None,
                "workspace": current.workspace,
                "mode": current.mode,
                "minutes": current.minutes,
                "elapsed_seconds": self.elapsed(current),
                "instruction": "Solve from memory. Previous solution is hidden.",
            }

    def active(self, state: State, rid: str) -> Recall:
        recall = state.recalls.get(rid)
        if recall is None or recall.completed:
            raise ValidationError("No active recall with that ID")
        return recall

    def cancel(self, rid: str) -> str:
        with self.store.transaction() as state:
            recall = self.active(state, rid)
            recall.completed = True
            state.activities.append(
                Activity(
                    "recall_cancel", recall.problem_id, self.clock.now().isoformat(), detail=rid
                )
            )
        return "Cancelled; workspace preserved and no review/streak awarded"

    def attempt_code(self, recall: Recall) -> str:
        path = safe_path(self.store.root, recall.workspace)
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValidationError("Attempt workspace must be a regular file at most 2 MiB")
        return path.read_text(encoding="utf-8")

    def baseline(self, state: State, recall: Recall) -> dict[str, str]:
        path = safe_path(self.store.root, f".coderecall/workspaces/{recall.id}/baseline.json")
        if path.exists():
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValidationError("Recall baseline exceeds size limit")
            try:
                data = json.loads(path.read_bytes())
                if (
                    not isinstance(data, dict)
                    or set(data) != {"source", "approach", "complexity", "solution_id"}
                    or not all(isinstance(v, str) for v in data.values())
                ):
                    raise ValueError
                return data
            except (ValueError, UnicodeError) as exc:
                raise ValidationError("Invalid private recall baseline") from exc
        # Compatibility for attempts created before baseline snapshots were introduced.
        problem = state.problems[recall.problem_id]
        if not problem.solutions:
            raise ValidationError("No previous solution exists")
        solution = problem.solutions[-1]
        return {
            "source": safe_path(self.store.root, solution.path).read_text(encoding="utf-8"),
            "approach": solution.approach,
            "complexity": solution.time_complexity,
            "solution_id": solution.id,
        }

    def elapsed(self, recall: Recall) -> int:
        end = instant(recall.paused_at) if recall.paused_at else self.clock.now()
        return max(
            0, int((end - instant(recall.started_at)).total_seconds()) - recall.paused_seconds
        )

    def pause(self, rid: str, resume: bool = False) -> str:
        with self.store.transaction() as state:
            recall = self.active(state, rid)
            if resume and recall.paused_at:
                recall.paused_seconds += max(
                    0, int((self.clock.now() - instant(recall.paused_at)).total_seconds())
                )
                recall.paused_at = ""
            elif not resume and not recall.paused_at:
                recall.paused_at = self.clock.now().isoformat()
            return "resumed" if resume else "paused"

    def hint(self, rid: str, reveal: bool = False) -> dict[str, object]:
        with self.store.transaction() as state:
            recall = self.active(state, rid)
            if recall.mode == "interview":
                raise ValidationError("Hints and reveal are disabled in interview mode")
            problem = state.problems[recall.problem_id]
            level = 5 if reveal else min(5, recall.hints + 1)
            if level == 5:
                if not problem.solutions:
                    raise ValidationError("No previous solution exists")
                text = self.baseline(state, recall)["source"]
            elif len(problem.hints) >= level:
                text = problem.hints[level - 1]
            else:
                text = [
                    "What constraints and edge cases matter?",
                    "Which invariant would make progress safe?",
                    "Can you describe the algorithm before coding?",
                    "Write pseudocode and trace a small example.",
                ][level - 1]
            recall.hints = max(recall.hints, level)
            return {
                "level": level,
                "hint": text,
                "source": "previous solution"
                if level == 5
                else "user hint"
                if len(problem.hints) >= level
                else "generic recall prompt",
            }

    def submit(
        self,
        rid: str,
        success: bool,
        confidence: int,
        attempts: int = 1,
        seconds: int | None = None,
        note: str = "",
        mistake: str = "",
        approach: str = "",
        complexity: str = "",
        verbal: bool = False,
    ) -> dict[str, object]:
        with self.store.transaction() as state:
            existing = next((r for r in state.reviews if r.id == rid), None)
            if existing:
                return {
                    "review": asdict(existing),
                    "schedule": asdict(state.schedules[existing.problem_id]),
                    "already_recorded": True,
                }
            recall = self.active(state, rid)
            code = self.attempt_code(recall)
            if success and not code.strip() and not verbal:
                raise ValidationError(
                    "A passing review requires a saved attempt. Write the workspace first, or use --verbal for explicit explanation-only self-assessment"
                )
            if verbal and not approach.strip():
                raise ValidationError("Explanation-only assessment requires --approach")
            if recall.mode == "interview" and (not approach.strip() or not complexity.strip()):
                raise ValidationError(
                    "Interview submission requires approach and complexity explanations"
                )
            elapsed = self.elapsed(recall) if seconds is None else seconds
            performance(elapsed, attempts, recall.hints, confidence)
            previous = state.schedules[recall.problem_id]
            if state.problems[recall.problem_id].archived or previous.state == "SUSPENDED":
                raise ValidationError("Problem is archived/suspended; resume it before submission")
            now = self.clock.now()
            review = Review(
                rid,
                recall.problem_id,
                now.isoformat(),
                previous.next_review,
                max(0, int((now - instant(previous.next_review)).total_seconds())),
                success,
                elapsed,
                attempts,
                recall.hints,
                confidence,
                note,
                approach,
                complexity,
                "self-reported-verbal"
                if verbal
                else "self-reported-code"
                if code.strip()
                else "self-reported-failure",
            )
            submission = safe_path(self.store.root, f".coderecall/workspaces/{rid}/submitted.txt")
            create_or_match(submission, code.encode())
            state.schedules[recall.problem_id] = self.scheduler.schedule(previous, review, now)
            state.reviews.append(review)
            recall.completed = True
            state.activities.append(
                Activity("review", recall.problem_id, now.isoformat(), elapsed, attempts)
            )
            if mistake:
                state.mistakes.append(
                    Mistake(recall.problem_id, mistake, "uncategorized", "medium", now.isoformat())
                )
            return {
                "review": asdict(review),
                "schedule": asdict(state.schedules[recall.problem_id]),
                "already_recorded": False,
                "attempt_has_code": bool(code.strip()),
            }

    def compare(self, rid: str) -> dict[str, object]:
        state = self.store.read()
        recall = state.recalls.get(rid)
        if not recall:
            raise ValidationError("Recall not found")
        if not recall.completed:
            raise ValidationError("Submit before comparing (or explicitly reveal in recall mode)")
        problem = state.problems[recall.problem_id]
        if not problem.solutions:
            raise ValidationError("No previous solution")
        baseline = self.baseline(state, recall)
        old = baseline["source"]
        submitted = safe_path(self.store.root, f".coderecall/workspaces/{rid}/submitted.txt")
        new = (
            submitted.read_text(encoding="utf-8")
            if submitted.exists()
            else self.attempt_code(recall)
        )
        review = next(r for r in state.reviews if r.id == rid)
        return {
            "diff": "".join(
                difflib.unified_diff(
                    old.splitlines(True), new.splitlines(True), "previous", "attempt"
                )
            ),
            "previous_approach": baseline["approach"],
            "current_approach": review.approach,
            "previous_complexity": baseline["complexity"],
            "current_complexity": review.complexity,
            "correctness": "Textual differences do not establish correctness",
        }

    def schedule_action(self, query: str, action: str, days: int = 1) -> Schedule:
        if not 1 <= days <= 365:
            raise ValidationError("Days must be 1–365")
        with self.store.transaction() as state:
            problem = identify(state, query)
            schedule = state.schedules[problem.id]
            if action == "suspend":
                schedule.state = "SUSPENDED"
            elif action == "resume":
                schedule.state = "REVIEW" if schedule.last_review else "NEW"
            elif action in {"skip", "reschedule"}:
                schedule.next_review = (self.clock.now() + timedelta(days=days)).isoformat()
            elif action == "reset":
                schedule = Schedule(problem.id, (self.clock.now() + timedelta(days=1)).isoformat())
                state.schedules[problem.id] = schedule
            else:
                raise ValidationError("Use skip, suspend, resume, reschedule or reset")
            state.activities.append(
                Activity(
                    "schedule",
                    problem.id,
                    self.clock.now().isoformat(),
                    detail=f"{action}: {days} days",
                )
            )
            return schedule

    def session(self, action: str, note: str = "") -> dict[str, object]:
        with self.store.transaction() as state:
            active = next((s for s in state.sessions.values() if not s.ended_at), None)
            if action == "start":
                if active is None:
                    active = Session("session_" + uuid4().hex, self.clock.now().isoformat())
                    state.sessions[active.id] = active
            elif action == "stop":
                if active is None:
                    raise ValidationError("No active study session")
                active.ended_at = self.clock.now().isoformat()
                active.note = note
                relevant = [
                    a
                    for a in state.activities
                    if a.kind in {"solution", "review"}
                    and instant(a.at) >= instant(active.started_at)
                ]
                seconds = max(
                    0, int((self.clock.now() - instant(active.started_at)).total_seconds())
                )
                if relevant or (note.strip() and seconds >= 60):
                    state.activities.append(
                        Activity("study", "", active.ended_at, seconds, detail=note)
                    )
            elif action != "status":
                raise ValidationError("Session action must be start, stop or status")
            if active is None:
                return {"active": False}
            end = instant(active.ended_at) if active.ended_at else self.clock.now()
            activities = [
                a
                for a in state.activities
                if instant(active.started_at) <= instant(a.at) <= end
                and a.kind in {"solution", "review"}
            ]
            reviews = [
                r
                for r in state.reviews
                if instant(active.started_at) <= instant(r.reviewed_at) <= end
            ]
            return {
                **asdict(active),
                "duration_seconds": max(0, int((end - instant(active.started_at)).total_seconds())),
                "new_solutions": sum(a.kind == "solution" for a in activities),
                "revisions": len(reviews),
                "problems_attempted": len({a.problem_id for a in activities}),
                "successes": sum(r.success for r in reviews),
                "failures": sum(not r.success for r in reviews),
            }
