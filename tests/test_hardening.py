import json
from dataclasses import replace
from datetime import timedelta

import pytest

from coderecall.application.importer import apply_import, scan
from coderecall.domain.errors import StateCorruptionError, ValidationError
from coderecall.storage import journal
from coderecall.storage.codec import decode_state
from coderecall.storage.config import Config


def test_metadata_enrichment_preserves_identity_schedule_and_paths(project, capture):
    first = replace(
        capture, metadata=replace(capture.metadata, external_id="", difficulty="unknown", topics=[])
    )
    old, _ = project.catalog.add(first)
    before = project.store.read().schedules[old.id]
    enriched, created = project.catalog.add(
        replace(capture, labels=["preferred"], patterns=["hash-map"])
    )
    assert not created and enriched.id == old.id
    assert enriched.external_id == "1" and enriched.difficulty == "easy"
    assert enriched.solutions[0].path == old.solutions[0].path
    assert enriched.solutions[0].labels == ["preferred"]
    assert project.store.read().schedules[old.id] == before
    meta = json.loads(
        (project.root / enriched.solutions[0].path).with_name("metadata.json").read_text()
    )
    assert meta["external_id"] == "1" and meta["topics"] == capture.metadata.topics
    assert project.stats()["solutions_added"] == 1


def test_enrichment_preserves_user_document_changes(project, capture):
    old, _ = project.catalog.add(capture)
    readme = (project.root / old.solutions[0].path).with_name("README.md")
    readme.write_text("My custom documentation", encoding="utf-8")
    with pytest.raises(ValidationError, match="Preserving modified"):
        project.catalog.add(replace(capture, metadata=replace(capture.metadata, difficulty="hard")))
    assert readme.read_text() == "My custom documentation"
    assert project.store.read().problems[old.id].difficulty == "easy"


@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
def test_journal_rolls_forward_every_interrupted_write(project, capture, monkeypatch, fail_at):
    original = journal.atomic_write
    calls = 0

    def fail(path, data):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise PermissionError("injected interrupted write")
        original(path, data)

    monkeypatch.setattr(journal, "atomic_write", fail)
    with pytest.raises(PermissionError):
        project.catalog.add(capture)
    monkeypatch.setattr(journal, "atomic_write", original)
    problem, _ = project.catalog.add(capture)
    state = project.store.read()
    assert len(state.problems) == len(state.schedules) == 1
    assert len(state.activities) == 1
    assert (project.root / problem.solutions[0].path).read_text() == capture.code
    assert not project.store.path("transaction.json").exists()


def test_recovery_refuses_concurrent_user_change(project, capture, monkeypatch):
    original = journal.atomic_write

    def fail(path, data):
        if path.name == "state.json":
            raise PermissionError("stop before snapshot")
        original(path, data)

    monkeypatch.setattr(journal, "atomic_write", fail)
    with pytest.raises(PermissionError):
        project.catalog.add(capture)
    monkeypatch.setattr(journal, "atomic_write", original)
    source = next(project.root.glob("python/**/solution.py"))
    source.write_text("user edits after interruption", encoding="utf-8")
    with pytest.raises(StateCorruptionError, match="changed after"):
        project.store.read()
    assert source.read_text() == "user edits after interruption"
    assert project.store.path("transaction.json").exists()


def test_import_preview_is_bounded_and_rejects_changed_source(project, tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    path = incoming / "1-two-sum.py"
    path.write_text("print('original')", encoding="utf-8")
    plan = scan(incoming)
    assert not hasattr(plan.captures[0], "code")
    path.write_text("print('changed')", encoding="utf-8")
    result = apply_import(project.catalog, plan)
    assert result["added"] == 0 and "changed after preview" in result["errors"][0]["error"]


def test_recall_requires_code_or_explicit_verbal_and_rejects_mode_switch(project, capture, clock):
    problem, _ = project.catalog.add(capture)
    started = project.recall.start(problem.id)
    rid = started["recall_id"]
    with pytest.raises(ValidationError, match="passing review"):
        project.recall.submit(rid, True, 4)
    with pytest.raises(ValidationError, match="already exists"):
        project.recall.start(problem.id, "interview")
    clock.value += timedelta(seconds=20)
    project.recall.pause(rid)
    clock.value += timedelta(seconds=300)
    resumed = project.recall.start(problem.id)
    assert resumed["elapsed_seconds"] == 20
    reviewed = project.recall.submit(
        rid, True, 4, verbal=True, approach="Explained complement lookup"
    )
    assert reviewed["review"]["assessment"] == "self-reported-verbal"


def test_review_capture_is_explicit_idempotent_and_private_notes_stay_private(project, capture):
    p, _ = project.catalog.add(capture)
    attempt = project.recall.start(p.id)
    source = project.root / attempt["workspace"]
    source.write_text("def solve():\n    return 'new approach'\n", encoding="utf-8")
    project.recall.submit(
        attempt["recall_id"], True, 5, note="private review note", approach="alternative"
    )
    assert len(project.store.read().problems[p.id].solutions) == 1
    assert project.capture_review(attempt["recall_id"])["captured"]
    assert not project.capture_review(attempt["recall_id"])["captured"]
    solutions = project.store.read().problems[p.id].solutions
    assert len(solutions) == 2
    assert (
        "private review note"
        not in (project.root / solutions[-1].path).with_name("metadata.json").read_text()
    )


def test_missing_nested_schema_fields_are_corruption(project, capture):
    project.catalog.add(capture)
    state = json.loads(project.store.path("state.json").read_bytes())
    p = next(iter(state["problems"].values()))
    del p["notes"]
    with pytest.raises(StateCorruptionError, match="Missing"):
        decode_state(json.dumps(state).encode())


def test_streak_config_cannot_count_fake_activity(project):
    from coderecall.domain.errors import ConfigurationError

    with pytest.raises(ConfigurationError):
        Config.set(project.root, "streak.activities", "git_commit")


def test_zero_times_are_unmeasured(project, capture):
    project.catalog.add(replace(capture, seconds=0))
    assert project.stats()["average_solve_seconds"] is None
    assert project.stats()["measured_solve_times"] == 0
