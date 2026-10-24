import base64
import json
import zipfile
from dataclasses import asdict

import pytest

from coderecall.application.catalog import Capture
from coderecall.application.project import doctor
from coderecall.domain.errors import (
    ConfigurationError,
    StateCorruptionError,
    ValidationError,
)
from coderecall.integrations.problems import ProblemMetadata
from coderecall.storage.backup import backup, restore, validate_archive, verify_backup
from coderecall.storage.codec import encode_state
from coderecall.storage.journal import digest, prepare, recover
from coderecall.storage.local import discover
from coderecall.storage.paths import safe_path


def make_capture(name: str = "Test Problem", slug: str = "test-problem") -> Capture:
    return Capture(
        ProblemMetadata(
            name, "leetcode", "1", slug, f"https://leetcode.com/problems/{slug}/", "easy", ["array"]
        ),
        "python",
        "def solve(): return True",
        "def test_solve(): assert solve()",
        "notes",
        "O(1)",
        "O(1)",
        "note",
        [],
        [],
        [],
        60,
        1,
    )


# ---------------------------------------------------------------------------
# Backup Verification & Safer Restore (Candidate B)
# ---------------------------------------------------------------------------


def test_verify_backup_inspects_valid_archive(project, capture):
    project.catalog.add(capture)
    archive = backup(project.store)

    summary = verify_backup(archive)
    assert summary["valid"] is True
    assert summary["archive"] == str(archive)
    assert summary["archive_size_bytes"] > 0
    assert summary["schema_version"] == 1
    assert summary["problems_count"] == 1
    assert summary["solutions_count"] == 1
    assert summary["reviews_count"] == 0


def test_verify_backup_rejects_corrupted_manifest(project, capture, tmp_path):
    project.catalog.add(capture)
    archive = backup(project.store)

    # Rebuild archive with corrupted manifest
    corrupt_archive = tmp_path / "corrupt_manifest.zip"
    with zipfile.ZipFile(archive, "r") as zin, zipfile.ZipFile(corrupt_archive, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "manifest.json":
                data = b'{"schema_version": 99, "application": "coderecall"}'
            zout.writestr(item, data)

    with pytest.raises(ValidationError, match="Invalid backup manifest"):
        verify_backup(corrupt_archive)


def test_verify_backup_rejects_missing_entry(project, capture, tmp_path):
    project.catalog.add(capture)
    archive = backup(project.store)

    incomplete = tmp_path / "incomplete.zip"
    with zipfile.ZipFile(archive, "r") as zin, zipfile.ZipFile(incomplete, "w") as zout:
        for item in zin.infolist():
            if item.filename != "config.toml":
                zout.writestr(item, zin.read(item.filename))

    with pytest.raises(
        ValidationError, match="must contain exactly state.json, config.toml, manifest.json"
    ):
        verify_backup(incomplete)


def test_verify_backup_rejects_extra_entry(project, capture, tmp_path):
    project.catalog.add(capture)
    archive = backup(project.store)

    extra = tmp_path / "extra.zip"
    with zipfile.ZipFile(archive, "r") as zin, zipfile.ZipFile(extra, "w") as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.writestr("extra.txt", b"malicious content")

    with pytest.raises(
        ValidationError, match="must contain exactly state.json, config.toml, manifest.json"
    ):
        verify_backup(extra)


def test_restore_rejects_pending_transaction(project, capture):
    project.catalog.add(capture)
    archive = backup(project.store)

    # Create dummy transaction journal
    project.store.path("transaction.json").write_text("{}", encoding="utf-8")
    with pytest.raises(StateCorruptionError, match="A transaction is pending"):
        restore(project.store, archive)


# ---------------------------------------------------------------------------
# Workspace Diagnostics: Backup & Transaction Health (Candidate A)
# ---------------------------------------------------------------------------


def test_doctor_reports_backup_and_transaction_health(project, capture):
    result_before = doctor(project.root)
    assert any(
        c["check"] == "backups" and c["status"] == "warning" for c in result_before["checks"]
    )
    assert any(
        c["check"] == "pending transactions" and c["status"] == "ok"
        for c in result_before["checks"]
    )

    # Create backup
    project.catalog.add(capture)
    backup(project.store)

    result_after = doctor(project.root)
    assert any(c["check"] == "backups" and c["status"] == "ok" for c in result_after["checks"])


# ---------------------------------------------------------------------------
# Storage Failure Matrix & Journal Crash Durability
# ---------------------------------------------------------------------------


def test_journal_recover_returns_false_when_no_transaction(project):
    assert recover(project.root) is False


def test_journal_prepare_rejects_concurrent_unrecovered_transaction(project):
    state_bytes = encode_state(project.store.read())
    prepare(project.root, state_bytes, {})
    with pytest.raises(StateCorruptionError, match="pending transaction must be recovered"):
        prepare(project.root, state_bytes, {})


def test_journal_recover_handles_truncated_journal(project):
    project.store.path("transaction.json").write_bytes(b'{"version": 1, "before_st')
    with pytest.raises(StateCorruptionError, match="Malformed JSON|Invalid transaction journal"):
        recover(project.root)


def test_journal_recover_handles_invalid_json(project):
    project.store.path("transaction.json").write_bytes(b"NOT_JSON_DATA")
    with pytest.raises(StateCorruptionError, match="Malformed JSON|Invalid transaction journal"):
        recover(project.root)


def test_journal_recover_detects_destination_file_modified_after_prepare(project, capture):
    p, _ = project.catalog.add(capture)
    solution_file = safe_path(project.root, p.solutions[0].path)

    before_content = solution_file.read_bytes()
    after_content = b"# updated solution"
    writes = {p.solutions[0].path: (before_content, after_content)}

    with project.store.lock():
        state = project.store.load_unlocked()
        prepare(project.root, encode_state(state), writes)

    # Simulate tampering: file on disk was modified out of band
    solution_file.write_bytes(b"# third party edit")

    with pytest.raises(StateCorruptionError, match="changed after transaction preparation"):
        recover(project.root)


def test_journal_recover_detects_learning_state_tampering(project, capture):
    p, _ = project.catalog.add(capture)
    solution_file = safe_path(project.root, p.solutions[0].path)

    before_content = solution_file.read_bytes()
    after_content = b"# updated solution"
    writes = {p.solutions[0].path: (before_content, after_content)}

    with project.store.lock():
        state = project.store.load_unlocked()
        prepare(project.root, encode_state(state), writes)

    # Tamper with state.json on disk
    project.store.path("state.json").write_bytes(b"tampered state data")

    with pytest.raises(
        StateCorruptionError, match="learning state changed after transaction preparation"
    ):
        recover(project.root)


def test_journal_successful_roll_forward(project, capture):
    p, _ = project.catalog.add(capture)
    solution_file = safe_path(project.root, p.solutions[0].path)

    before_content = solution_file.read_bytes()
    after_content = b"# rolled forward solution"
    writes = {p.solutions[0].path: (before_content, after_content)}

    with project.store.lock():
        state = project.store.load_unlocked()
        prepare(project.root, encode_state(state), writes)

    assert project.store.path("transaction.json").exists()
    assert recover(project.root) is True

    # After recovery, file is updated, journal is unlinked, previous snapshot is kept
    assert solution_file.read_bytes() == after_content
    assert not project.store.path("transaction.json").exists()
    assert project.store.path("state.previous.json").exists()

    # Idempotent re-recovery returns False
    assert recover(project.root) is False


def test_staged_files_outside_transaction_raises_runtime_error(project):
    with pytest.raises(RuntimeError, match="Generated writes require a state transaction"):
        project.store.stage_files({})


def test_staged_files_conflict_raises_validation_error(project, capture):
    p, _ = project.catalog.add(capture)
    solution_rel = p.solutions[0].path

    with pytest.raises(ValidationError, match="Preserving modified file"):
        with project.store.transaction():
            # Pass incorrect before image to simulate conflicting concurrent edit
            project.store.stage_files({solution_rel: (b"mismatched before content", b"after")})


def test_discover_missing_project_raises_configuration_error(tmp_path):
    with pytest.raises(ConfigurationError, match="No CodeRecall project found"):
        discover(tmp_path)


def test_initialize_already_exists_raises_configuration_error(project):
    with pytest.raises(ConfigurationError, match=".coderecall already exists"):
        project.store.initialize()


def test_corrupt_content_addressed_backup_detected(project, capture):
    project.catalog.add(capture)
    archive = backup(project.store)

    # Intentionally corrupt the archive file on disk
    archive.write_bytes(b"corrupt archive payload")

    with pytest.raises(ValidationError, match="Invalid backup archive"):
        backup(project.store)


def test_backup_unlocked_rejects_corrupted_manifest(project):
    from coderecall.storage.backup import backup_unlocked

    project.store.path("manifest.json").write_bytes(b'{"schema_version": 2}')
    with pytest.raises(StateCorruptionError, match="Invalid manifest; repair it before backing up"):
        backup_unlocked(project.store)


def test_validate_archive_rejects_symlink_entry(tmp_path):
    archive = tmp_path / "symlink_entry.zip"
    zinfo = zipfile.ZipInfo("state.json")
    zinfo.external_attr = 0o120755 << 16  # S_IFLNK
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(zinfo, b"target")
        z.writestr("config.toml", b"")
        z.writestr("manifest.json", b"")
    with pytest.raises(ValidationError, match="Unsafe archive entry"):
        validate_archive(archive)


def test_journal_recover_rejects_unknown_format(project):
    project.store.path("transaction.json").write_bytes(
        json.dumps({"version": 99, "before_state": "a", "state": "b", "files": []}).encode()
    )
    with pytest.raises(StateCorruptionError, match="Invalid transaction journal"):
        recover(project.root)


def test_journal_recover_rejects_invalid_file_entries(project):
    project.store.path("transaction.json").write_bytes(
        json.dumps(
            {"version": 1, "before_state": "a", "state": "b", "files": "NOT_A_LIST"}
        ).encode()
    )
    with pytest.raises(StateCorruptionError, match="Invalid transaction journal"):
        recover(project.root)


def test_journal_recover_rejects_unowned_journal_path(project):
    state = project.store.read()
    raw_state = encode_state(state)
    b64_state = base64.b64encode(raw_state).decode("ascii")
    record = {
        "version": 1,
        "before_state": digest(raw_state),
        "state": b64_state,
        "files": [
            {
                "path": "unowned/evil.py",
                "before": None,
                "after": base64.b64encode(b"evil").decode("ascii"),
            }
        ],
    }
    project.store.path("transaction.json").write_bytes(json.dumps(record).encode())
    with pytest.raises(StateCorruptionError, match="Invalid transaction journal"):
        recover(project.root)


def test_local_store_load_rejects_corrupt_manifest(project):
    project.store.path("manifest.json").write_bytes(b'{"schema_version": 999}')
    with pytest.raises(StateCorruptionError, match="Invalid/incompatible manifest"):
        project.store.read()


def test_local_store_load_rejects_missing_state(project):
    project.store.path("state.json").unlink()
    with pytest.raises(StateCorruptionError, match="Missing state or manifest"):
        project.store.read()


def test_local_store_migrate_unsupported_version_raises(project):
    data = asdict(project.store.read())
    data["schema_version"] = 2
    project.store.path("state.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(StateCorruptionError, match="No migration available for this schema"):
        project.store.migrate()


def test_local_store_migrate_backup_exists_raises(project):
    data = asdict(project.store.read())
    data["schema_version"] = 0
    project.store.path("state.json").write_text(json.dumps(data), encoding="utf-8")
    # Pre-create the backup file
    project.store.path("state.v0.backup.json").write_bytes(b"existing backup")
    with pytest.raises(StateCorruptionError, match="Migration backup already exists"):
        project.store.migrate()
