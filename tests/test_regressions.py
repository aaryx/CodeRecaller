import json
from dataclasses import replace
from datetime import timedelta

import pytest

from coderecall.domain.errors import StateCorruptionError, ValidationError
from coderecall.storage.codec import decode_state
from coderecall.storage.config import Config


def test_capture_retry_after_state_write_failure(project, capture, monkeypatch):
    from coderecall.storage import journal

    save = journal.atomic_write

    def fail(path, data):
        if path.name == "state.json":
            raise PermissionError("injected snapshot failure")
        save(path, data)

    monkeypatch.setattr(journal, "atomic_write", fail)
    with pytest.raises(PermissionError):
        project.catalog.add(capture)
    monkeypatch.setattr(journal, "atomic_write", save)
    problem, created = project.catalog.add(capture)
    assert not created and len(problem.solutions) == 1
    assert len(list(project.root.glob("python/**/solution.py"))) == 1


def test_incomplete_snapshot_is_not_silently_reset():
    with pytest.raises(StateCorruptionError):
        decode_state(b'{"schema_version":1}')


def test_case_insensitive_private_layout(project, capture):
    Config.set(project.root, "repository.layout", ".CODERECALL/{solution_id}")
    project.catalog.config = Config(project.root)
    with pytest.raises(ValidationError):
        project.catalog.add(capture)


def test_hint_levels_and_reveal_recorded(project, capture):
    p, _ = project.catalog.add(capture)
    project.add_hint(p.id, 1, "Think about complements")
    attempt = project.recall.start(p.id)
    rid = attempt["recall_id"]
    assert project.recall.hint(rid)["hint"] == "Think about complements"
    assert project.recall.hint(rid)["level"] == 2
    assert project.recall.hint(rid, True)["hint"] == capture.code
    result = project.recall.submit(rid, True, 5, verbal=True, approach="explained hash map")
    assert result["review"]["hints"] == 5
    assert result["schedule"]["interval_days"] == 1


def test_daily_strategy_tracks_real_solution_activity(project, capture, clock):
    Config.set(project.root, "git.strategy", "daily")
    project.config = Config(project.root)
    assert not project.daily_commit_due()
    project.catalog.add(capture)
    assert project.daily_commit_due()
    clock.value += timedelta(days=1)
    assert not project.daily_commit_due()


def test_archive_history_preserved_and_resume(project, capture):
    p, _ = project.catalog.add(capture)
    project.catalog.archive(p.id, True)
    assert project.list_problems() == []
    assert project.list_problems(archived=True)[0].id == p.id
    with pytest.raises(ValidationError):
        project.recall.start(p.id)
    project.catalog.archive(p.id, False)
    assert project.list_problems()[0].id == p.id


def test_csv_formula_injection_escape(project, capture):
    project.catalog.add(replace(capture, metadata=replace(capture.metadata, title="=IMPORTDATA()")))
    assert "'=IMPORTDATA()" in project.export("csv")


def test_unknown_fields_rejected(project):
    data = json.loads(project.store.path("state.json").read_bytes())
    data["token"] = "must-not-be-stored"  # noqa: S105 -- synthetic forbidden schema field
    with pytest.raises(StateCorruptionError):
        decode_state(json.dumps(data).encode())
