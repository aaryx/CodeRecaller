import json
from dataclasses import replace

import pytest

from coderecall.application.importer import apply_import, scan
from coderecall.domain.errors import ValidationError
from coderecall.integrations.problems import ProblemMetadata
from coderecall.storage.config import Config


def test_capture_idempotency_versions_privacy(project, capture):
    p, created = project.catalog.add(capture)
    assert created
    same, created = project.catalog.add(capture)
    assert same.id == p.id and not created
    alternative = replace(capture, code="print('alternate')\n", approach="brute force")
    updated, created = project.catalog.add(alternative)
    assert created and len(updated.solutions) == 2
    for solution in updated.solutions:
        directory = (project.root / solution.path).parent
        assert (directory / "README.md").is_file()
        metadata = (directory / "metadata.json").read_text()
        assert "private-memory" not in metadata
        assert "confidence" not in metadata
    assert len(project.store.read().schedules) == 1
    assert project.stats()["solutions_added"] == 2


def test_conflict_preserves_existing_files(project, capture):
    Config.set(project.root, "repository.layout", "python/fixed")
    project.catalog.config = Config(project.root)
    p, _ = project.catalog.add(capture)
    source = project.root / p.solutions[0].path
    original = source.read_bytes()
    with pytest.raises(ValidationError):
        project.catalog.add(replace(capture, code="print('different')"))
    assert source.read_bytes() == original
    assert len(project.store.read().problems[p.id].solutions) == 1


@pytest.mark.parametrize("count", [10, 100, 1000])
def test_import_scale_preview_and_idempotency(project, tmp_path, count):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    for i in range(count):
        (incoming / f"{i + 1:04}-problem-{i}.py").write_text(
            f"def solve():\n    return {i}\n", encoding="utf-8"
        )
    (incoming / "setup.py").write_text("raise RuntimeError('must never execute')", encoding="utf-8")
    before = project.store.path("state.json").read_bytes()
    plan = scan(incoming)
    assert len(plan.captures) == count
    assert plan.needs_review == ["setup.py"]
    assert project.store.path("state.json").read_bytes() == before
    result = apply_import(project.catalog, plan)
    assert result["added"] == count
    assert apply_import(project.catalog, plan)["duplicates"] == count


def test_import_batch_keeps_one_identity_for_repeated_external_id(project, tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    for name, code in [
        ("1-first.py", "print('first')\n"),
        ("1-second.py", "print('second')\n"),
        ("1-third.py", "print('third')\n"),
    ]:
        (incoming / name).write_text(code, encoding="utf-8")

    result = apply_import(project.catalog, scan(incoming))

    assert result["added"] == 3
    stored = project.store.read().problems
    assert len(stored) == 1
    assert len(next(iter(stored.values())).solutions) == 3


def test_malicious_metadata_and_unicode(project, tmp_path):
    incoming = tmp_path / "import"
    incoming.mkdir()
    (incoming / "0001-三数之和.py").write_text("x = 1", encoding="utf-8")
    assert len(scan(incoming).captures) == 1
    (incoming / "metadata.json").write_text(
        json.dumps({"title": "Hello", "topics": "not a list"}), encoding="utf-8"
    )
    assert len(scan(incoming).needs_review) == 1


def test_random_seed_and_search(project, capture):
    project.catalog.add(capture)
    project.catalog.add(replace(capture, metadata=ProblemMetadata("Three Sum", "leetcode", "15")))
    assert project.random_problem(42).id == project.random_problem(42).id
    assert len(project.list_problems(query="private-memory")) == 2
    assert len(project.list_problems(topic="array")) == 1
