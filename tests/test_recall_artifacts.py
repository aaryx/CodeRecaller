from dataclasses import replace

import pytest

from coderecall.domain.errors import ValidationError


def test_comparison_uses_original_baseline_and_submitted_code(project, capture):
    problem, _ = project.catalog.add(capture)
    attempt = project.recall.start(problem.id)
    workspace = project.root / attempt["workspace"]
    workspace.write_text("print('submitted attempt')\n", encoding="utf-8")
    project.recall.submit(attempt["recall_id"], True, 5)
    project.catalog.add(replace(capture, code="print('new unrelated version')\n", approach="later"))
    workspace.write_text("print('edited after submission')", encoding="utf-8")
    compared = project.recall.compare(attempt["recall_id"])
    assert "submitted attempt" in compared["diff"]
    assert "new unrelated version" not in compared["diff"]
    assert "edited after submission" not in compared["diff"]
    assert "return [0, 1]" in compared["diff"]
    project.capture_review(attempt["recall_id"])
    captured = project.store.read().problems[problem.id].solutions[-1]
    assert "submitted attempt" in (project.root / captured.path).read_text()


def test_duplicate_capture_detects_external_source_change(project, capture):
    problem, _ = project.catalog.add(capture)
    source = project.root / problem.solutions[0].path
    source.write_text("local edits", encoding="utf-8")
    with pytest.raises(ValidationError, match="Stored solution changed"):
        project.catalog.add(capture)
    assert source.read_text() == "local edits"
