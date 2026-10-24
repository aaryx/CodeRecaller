import json
import os
import subprocess
import sys
import zipfile
from dataclasses import asdict
from pathlib import Path

import pytest

from coderecall.domain.errors import ConfigurationError, StateCorruptionError, ValidationError
from coderecall.domain.validation import relative_path, validate_url
from coderecall.storage.backup import backup, restore, validate_archive
from coderecall.storage.codec import decode_state, encode_state
from coderecall.storage.config import Config
from coderecall.storage.paths import atomic_write, safe_path


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/outside/x",
        "C:/x",
        "a\\b",
        "a/../b",
        "a//b",
        "a/CON.py",
        "a/x.",
        ".git/config",
        ".GIT/config",
        "a/evil\n.py",
        "a/b:stream",
    ],
)
def test_path_traversal(path, tmp_path):
    with pytest.raises(ValidationError):
        safe_path(tmp_path, path)


@pytest.mark.parametrize(
    "url",
    [
        "http://leetcode.com/problems/a",
        "https://evil.com/problems/a",
        "https://leetcode.com.evil.com/problems/a",
        "https://user:secret@leetcode.com/problems/a",
        "https://leetcode.com:444/problems/a",
        "file:///etc/passwd",
    ],
)
def test_url_security(url):
    with pytest.raises(ValidationError):
        validate_url(url, leetcode=True)


def test_symlink_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    try:
        (tmp_path / "link").symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation unavailable for this Windows account")
    with pytest.raises(ValidationError):
        safe_path(tmp_path, "link/escape.py")


def test_atomic_replace_failure_preserves_original(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    atomic_write(path, b"original")

    def fail(*args):
        raise PermissionError("injected disk error")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(PermissionError):
        atomic_write(path, b"changed")
    assert path.read_bytes() == b"original"
    assert list(tmp_path.glob(".cr-*")) == []


def test_validation_references_types_and_future_schema(project, capture):
    project.catalog.add(capture)
    valid = encode_state(project.store.read())
    data = json.loads(valid)
    key = next(iter(data["schedules"]))
    data["schedules"][key]["interval_days"] = "2"
    with pytest.raises(StateCorruptionError):
        decode_state(json.dumps(data).encode())
    data = json.loads(valid)
    data["schema_version"] = 99
    with pytest.raises(StateCorruptionError):
        decode_state(json.dumps(data).encode())
    with pytest.raises(StateCorruptionError):
        decode_state(b'{"schema_version":1,"schema_version":1}')
    with pytest.raises(StateCorruptionError):
        decode_state(b"{")


def test_backup_restore_and_zip_slip(project, capture, tmp_path):
    p, _ = project.catalog.add(capture)
    archive = backup(project.store)
    assert backup(project.store) == archive
    project.catalog.annotate(p.id, "new private note")
    recovery = restore(project.store, archive)
    assert Path(recovery).is_file()
    assert project.store.read().problems[p.id].notes == ["private-memory"]
    bad = tmp_path / "malicious.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../state.json", b"{}")
    with pytest.raises(ValidationError):
        validate_archive(bad)


def test_corrupt_restore_and_migration(project, capture):
    project.catalog.add(capture)
    archive = backup(project.store)
    project.store.path("state.json").write_bytes(b"corrupt")
    recovery = restore(project.store, archive)
    assert Path(recovery).read_bytes() == b"corrupt"
    data = asdict(project.store.read())
    data["schema_version"] = 0
    project.store.path("state.json").write_text(json.dumps(data), encoding="utf-8")
    assert "Migrated" in project.store.migrate()
    assert project.store.path("state.v0.backup.json").exists()
    assert "Already" in project.store.migrate()


def test_cross_process_lock(project):
    code = "from pathlib import Path; from coderecall.storage.local import LocalStore; from coderecall.domain.errors import StateLockedError; import sys\ntry:\n LocalStore(Path(sys.argv[1])).read()\nexcept StateLockedError:\n sys.exit(10)\n"
    with project.store.lock():
        result = subprocess.run(
            [sys.executable, "-c", code, str(project.root)], capture_output=True, timeout=15
        )
        assert result.returncode == 10, result.stderr
    assert project.store.read().schema_version == 1


def test_config_precedence_and_reject_secrets(project, monkeypatch):
    Config.set(project.root, "git.auto_commit", "false")
    assert not Config(project.root).get("git.auto_commit")
    monkeypatch.setenv("CODERECALL_GIT_AUTO_COMMIT", "true")
    assert Config(project.root).get("git.auto_commit")
    assert not Config(project.root, {"git.auto_commit": False}).get("git.auto_commit")
    with pytest.raises(ConfigurationError):
        Config.set(project.root, "github.token", "not-a-real-token")
    with pytest.raises(ConfigurationError):
        Config.set(project.root, "git.strategy", "fake-commits")


def test_relative_path_roundtrip():
    for i in range(100):
        name = f"python/{i:04}-problem/s_{i}/solution.py"
        assert relative_path(name) == name
