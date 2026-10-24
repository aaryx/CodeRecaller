"""Recoverable roll-forward transactions for generated files and the state snapshot.

The caller holds the project lock. Once intent is durable, recovery completes it
only if every destination still matches its recorded before/after image.
"""

import base64
import hashlib
import json
from pathlib import Path

from coderecall.domain.errors import StateCorruptionError, ValidationError
from coderecall.storage.codec import MAX_STATE_BYTES, decode_state, json_object
from coderecall.storage.paths import atomic_write, safe_path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(root: Path, state: bytes, writes: dict[str, tuple[bytes | None, bytes]]) -> None:
    path = safe_path(root, ".coderecall/transaction.json")
    if path.exists():
        raise StateCorruptionError("A pending transaction must be recovered first")
    previous = safe_path(root, ".coderecall/state.json").read_bytes()
    record = {
        "version": 1,
        "before_state": digest(previous),
        "state": base64.b64encode(state).decode("ascii"),
        "files": [
            {
                "path": name,
                "before": digest(before) if before is not None else None,
                "after": base64.b64encode(after).decode("ascii"),
            }
            for name, (before, after) in writes.items()
        ],
    }
    raw = json.dumps(record, separators=(",", ":")).encode()
    if len(raw) > MAX_STATE_BYTES:
        raise ValidationError("Transaction exceeds 64 MiB; import a smaller batch")
    atomic_write(path, raw)


def recover(root: Path) -> bool:
    journal = safe_path(root, ".coderecall/transaction.json")
    if not journal.exists():
        return False
    try:
        if journal.stat().st_size > MAX_STATE_BYTES:
            raise ValueError("Oversized journal")
        record = json_object(journal.read_bytes())
        if set(record) != {"version", "before_state", "state", "files"} or record["version"] != 1:
            raise ValueError("Unknown journal format")
        state = base64.b64decode(str(record["state"]), validate=True)
        decoded = decode_state(state)
        # A journal may only modify public paths owned by its resulting state.
        owned = {s.path for p in decoded.problems.values() for s in p.solutions}
        owned.update(
            str(Path(p).parent / name).replace("\\", "/")
            for p in tuple(owned)
            for name in ["README.md", "metadata.json"]
        )
        entries = record["files"]
        if not isinstance(entries, list):
            raise ValueError("Invalid file entries")
        writes: list[tuple[Path, bytes]] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"path", "before", "after"}:
                raise ValueError("Invalid file record")
            name = entry["path"]
            if not isinstance(name, str) or name not in owned or name in seen:
                raise ValueError("Unowned/duplicate journal path")
            seen.add(name)
            path = safe_path(root, name)
            after = base64.b64decode(entry["after"], validate=True)
            current = digest(path.read_bytes()) if path.exists() else None
            if current not in {entry["before"], digest(after)}:
                raise StateCorruptionError(
                    f"Recovery stopped: {name} changed after transaction preparation. "
                    "Preserve that file and the transaction journal before resolving the conflict"
                )
            if current != digest(after):
                writes.append((path, after))
        snapshot = safe_path(root, ".coderecall/state.json")
        current_state = snapshot.read_bytes()
        if digest(current_state) not in {record["before_state"], digest(state)}:
            raise StateCorruptionError(
                "Recovery stopped: learning state changed after transaction preparation"
            )
        for path, after in writes:
            atomic_write(path, after)
        if current_state != state:
            atomic_write(safe_path(root, ".coderecall/state.previous.json"), current_state)
            atomic_write(snapshot, state)
        journal.unlink()
        return True
    except (ValueError, TypeError, KeyError) as exc:
        raise StateCorruptionError(
            "Invalid transaction journal; preserve it and recover from a backup"
        ) from exc
