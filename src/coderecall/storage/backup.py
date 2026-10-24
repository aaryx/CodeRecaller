import hashlib
import io
import stat
import zipfile
from pathlib import Path

from coderecall.domain.errors import StateCorruptionError, ValidationError
from coderecall.storage.codec import MAX_STATE_BYTES, decode_state, encode_state, json_object
from coderecall.storage.config import parse_config
from coderecall.storage.local import LocalStore
from coderecall.storage.paths import atomic_write

ENTRIES = {"state.json", "config.toml", "manifest.json"}


def backup_unlocked(store: LocalStore) -> Path:
    files = {name: store.path(name).read_bytes() for name in sorted(ENTRIES)}
    decode_state(files["state.json"])
    parse_config(files["config.toml"])
    if json_object(files["manifest.json"]) != {"schema_version": 1, "application": "coderecall"}:
        raise StateCorruptionError("Invalid manifest; repair it before backing up")
    digest = hashlib.sha256(b"".join(files.values())).hexdigest()[:20]
    path = store.path(f"backups/backup-{digest}.zip")
    if path.exists():
        if validate_archive(path) != files["state.json"]:
            raise StateCorruptionError(
                "Existing content-addressed backup does not match its snapshot"
            )
        return path
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    atomic_write(path, buffer.getvalue())
    return path


def backup(store: LocalStore) -> Path:
    with store.lock():
        store.load_unlocked()
        return backup_unlocked(store)


def validate_archive(path: Path) -> bytes:
    try:
        if path.stat().st_size > MAX_STATE_BYTES:
            raise ValidationError("Archive exceeds size limit")
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) != 3 or {item.filename for item in entries} != ENTRIES:
                raise ValidationError(
                    "Backup must contain exactly state.json, config.toml, manifest.json"
                )
            if sum(item.file_size for item in entries) > MAX_STATE_BYTES:
                raise ValidationError("Uncompressed archive exceeds size limit")
            for item in entries:
                mode = item.external_attr >> 16
                if stat.S_ISLNK(mode) or item.is_dir() or item.flag_bits & 1:
                    raise ValidationError("Unsafe archive entry")
            state = archive.read("state.json")
            decode_state(state)
            parse_config(archive.read("config.toml"))
            if json_object(archive.read("manifest.json")) != {
                "schema_version": 1,
                "application": "coderecall",
            }:
                raise ValidationError("Invalid backup manifest")
            return state
    except (zipfile.BadZipFile, RuntimeError, EOFError) as exc:
        raise ValidationError("Invalid backup archive") from exc


def restore(store: LocalStore, archive: Path) -> str:
    raw = validate_archive(archive)
    with store.lock():
        if store.path("transaction.json").exists():
            raise StateCorruptionError(
                "A transaction is pending; run doctor to recover it before restoring a different snapshot"
            )
        for problem in decode_state(raw).problems.values():
            for solution in problem.solutions:
                from coderecall.storage.paths import safe_path

                safe_path(store.root, solution.path)
        try:
            recovery = str(backup_unlocked(store))
        except (StateCorruptionError, FileNotFoundError):
            old = store.path("state.json")
            previous = old.read_bytes() if old.exists() else b""
            recovery_path = store.path(
                "backups/corrupt-" + hashlib.sha256(previous).hexdigest()[:20] + ".json"
            )
            atomic_write(recovery_path, previous)
            recovery = str(recovery_path)
        atomic_write(store.path("state.json"), encode_state(decode_state(raw)))
        manifest = store.path("manifest.json")
        expected = b'{"schema_version":1,"application":"coderecall"}\n'
        if manifest.exists():
            previous_manifest = manifest.read_bytes()
            try:
                valid = json_object(previous_manifest) == {
                    "schema_version": 1,
                    "application": "coderecall",
                }
            except StateCorruptionError:
                valid = False
            if not valid:
                saved = store.path(
                    "backups/manifest-"
                    + hashlib.sha256(previous_manifest).hexdigest()[:20]
                    + ".json"
                )
                atomic_write(saved, previous_manifest)
                atomic_write(manifest, expected)
        else:
            atomic_write(manifest, expected)
    return recovery
