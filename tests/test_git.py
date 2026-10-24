from pathlib import Path

import pytest

from coderecall.domain.errors import GitError, SyncConflictError, ValidationError
from coderecall.integrations.git import LocalGitProvider


def initialize_git(root: Path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "CodeRecall Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "CodeRecall Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
    git = LocalGitProvider(root)
    git.command("init", "-b", "main")
    # Per-command config supplies a synthetic author without touching developer Git configuration.
    git.command(
        "-c",
        "user.name=CodeRecall Test",
        "-c",
        "user.email=test@example.invalid",
        "config",
        "--local",
        "core.autocrlf",
        "false",
    )
    return git


def commit_test(git, message="test fixture"):
    git.command("add", "--all")
    git.command(
        "-c",
        "user.name=CodeRecall Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        message,
    )


def test_owned_commit_refuses_unrelated_staged(project, capture, monkeypatch):
    git = initialize_git(project.root, monkeypatch)
    p, _ = project.catalog.add(capture)
    unrelated = project.root / "unrelated.txt"
    unrelated.write_text("user work", encoding="utf-8")
    git.command("add", "--", "unrelated.txt")
    with pytest.raises(GitError, match="Unrelated staged"):
        project.commit("solve: Two Sum")
    assert "unrelated.txt" in git.command("diff", "--cached", "--name-only")
    assert (project.root / p.solutions[0].path).exists()


def test_sync_states_preserve_dirty_diverged_and_remote_ahead(tmp_path, monkeypatch):
    root = tmp_path / "local"
    root.mkdir()
    git = initialize_git(root, monkeypatch)
    (root / "a.txt").write_text("initial", encoding="utf-8")
    commit_test(git)
    remote = tmp_path / "remote.git"
    git.command("init", "--bare", str(remote))
    git.command("remote", "add", "origin", str(remote))
    git.command("push", "-u", "origin", "main")
    assert git.plan().state == "CLEAN"
    (root / "a.txt").write_text("local", encoding="utf-8")
    with pytest.raises(SyncConflictError):
        git.plan()
    commit_test(git, "local change")
    assert git.plan().state == "LOCAL_AHEAD"
    git.push()
    other = tmp_path / "other"
    git.command("clone", "--branch", "main", str(remote), str(other))
    peer = LocalGitProvider(other)
    (other / "remote.txt").write_text("remote", encoding="utf-8")
    commit_test(peer, "remote change")
    peer.command("push")
    assert git.plan(fetch=True).state == "REMOTE_AHEAD"
    git.execute_plan(git.plan())
    assert (root / "remote.txt").read_text() == "remote"
    (root / "local.txt").write_text("new local", encoding="utf-8")
    commit_test(git)
    (other / "another.txt").write_text("new remote", encoding="utf-8")
    commit_test(peer)
    peer.command("push")
    plan = git.plan(fetch=True)
    assert plan.state == "DIVERGED"
    before = git.command("rev-parse", "HEAD")
    with pytest.raises(SyncConflictError):
        git.execute_plan(plan)
    assert git.command("rev-parse", "HEAD") == before


def test_secrets_in_intermediate_commits_block_push(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    git = initialize_git(root, monkeypatch)
    (root / "a.txt").write_text("safe", encoding="utf-8")
    commit_test(git)
    remote = tmp_path / "remote.git"
    git.command("init", "--bare", str(remote))
    git.command("remote", "add", "origin", str(remote))
    git.command("push", "-u", "origin", "main")
    (root / "secret.txt").write_text("-----BEGIN PRIVATE KEY-----", encoding="utf-8")
    commit_test(git)
    (root / "secret.txt").unlink()
    commit_test(git)
    with pytest.raises(ValidationError, match="Likely secret"):
        git.push()


def test_no_remote_and_unsafe_transport(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    git = initialize_git(root, monkeypatch)
    (root / "a.txt").write_text("hello", encoding="utf-8")
    commit_test(git)
    with pytest.raises(GitError):
        git.plan()


def test_remote_private_state_blocks_fast_forward(tmp_path, monkeypatch):
    root = tmp_path / "local"
    root.mkdir()
    git = initialize_git(root, monkeypatch)
    (root / "a.txt").write_text("safe", encoding="utf-8")
    commit_test(git)
    remote = tmp_path / "remote.git"
    git.command("init", "--bare", str(remote))
    git.command("remote", "add", "origin", str(remote))
    git.command("push", "-u", "origin", "main")
    other = tmp_path / "other"
    git.command("clone", "--branch", "main", str(remote), str(other))
    (other / ".coderecall").mkdir()
    (other / ".coderecall/state.json").write_text("hostile overwrite", encoding="utf-8")
    peer = LocalGitProvider(other)
    commit_test(peer)
    peer.command("push")
    plan = git.plan(fetch=True)
    with pytest.raises(SyncConflictError, match="private"):
        git.execute_plan(plan)
    assert not (root / ".coderecall").exists()


def test_owned_modified_deleted_and_retry(project, capture, monkeypatch):
    initialize_git(project.root, monkeypatch)
    p, _ = project.catalog.add(capture)
    first = project.commit("solve: initial")
    assert len(first) == 40
    assert project.commit("solve: retry").startswith("No owned")
    source = project.root / p.solutions[0].path
    source.write_text("def solve():\n    return 99\n", encoding="utf-8")
    second = project.commit("solve: improved")
    assert second != first
    assert project.store.read().problems[p.id].solutions[0].git_ref == second
    source.unlink()
    assert len(project.commit("solve: remove source")) == 40
    assert "unrelated" not in project.git.command("ls-files")


def test_sync_imports_remote_metadata_in_one_workflow(project, capture, tmp_path, monkeypatch):
    initialize_git(project.root, monkeypatch)
    project.catalog.add(capture)
    project.commit("solve: initial")
    remote = tmp_path / "remote.git"
    project.git.command("init", "--bare", str(remote))
    project.git.command("remote", "add", "origin", str(remote))
    project.git.command("push", "-u", "origin", "main")
    other = tmp_path / "peer"
    project.git.command("clone", "--branch", "main", str(remote), str(other))
    folder = other / "python/0015-three-sum"
    folder.mkdir(parents=True)
    (folder / "solution.py").write_text("print('three sum')", encoding="utf-8")
    import json

    (folder / "metadata.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "title": "Three Sum",
                "platform": "leetcode",
                "external_id": "15",
                "slug": "three-sum",
            }
        ),
        encoding="utf-8",
    )
    peer = LocalGitProvider(other)
    commit_test(peer)
    peer.command("push")
    plan = project.git.plan(fetch=True)
    result = project.sync(fetch=False, execute=True, approved=plan, import_solutions=True)
    assert result["import"]["added"] == 1
    assert len(project.store.read().problems) == 2


def test_approved_plan_rejects_changed_refs_even_same_counts(tmp_path, monkeypatch):
    from dataclasses import replace

    root = tmp_path / "repo"
    root.mkdir()
    git = initialize_git(root, monkeypatch)
    (root / "a.txt").write_text("safe", encoding="utf-8")
    commit_test(git)
    remote = tmp_path / "remote.git"
    git.command("init", "--bare", str(remote))
    git.command("remote", "add", "origin", str(remote))
    git.command("push", "-u", "origin", "main")
    plan = git.plan()
    with pytest.raises(SyncConflictError, match="changed since preview"):
        git.execute_plan(replace(plan, local_ref="0" * 40))
