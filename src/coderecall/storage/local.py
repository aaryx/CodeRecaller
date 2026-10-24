import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from coderecall.domain.errors import ConfigurationError, StateCorruptionError, StateLockedError
from coderecall.domain.models import State
from coderecall.storage.codec import MAX_STATE_BYTES, decode_state, encode_state, json_object
from coderecall.storage.config import DEFAULTS, render_config
from coderecall.storage.paths import atomic_write, safe_path


def discover(start: Path) -> Path:
    for path in [start.resolve(), *start.resolve().parents]:
        if (path / ".coderecall").exists():
            safe_path(path, ".coderecall")
            return path
    raise ConfigurationError("No CodeRecall project found. Run coderecall init")


def _lock(stream: BinaryIO, unlock: bool = False) -> None:
    if sys.platform == "win32":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB)


class LocalStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.directory = safe_path(self.root, ".coderecall")
        self._writes: dict[str, tuple[bytes | None, bytes]] | None = None

    def path(self, name: str) -> Path:
        return safe_path(self.root, f".coderecall/{name}")

    @contextmanager
    def lock(self) -> Iterator[None]:
        if not self.directory.is_dir():
            raise ConfigurationError("Run coderecall init first")
        with self.path("state.lock").open("a+b") as stream:
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            try:
                _lock(stream)
            except OSError as exc:
                raise StateLockedError(
                    "Another CodeRecall process holds the state lock; retry later"
                ) from exc
            try:
                yield
            finally:
                _lock(stream, unlock=True)

    def initialize(self) -> None:
        if self.directory.exists():
            raise ConfigurationError(".coderecall already exists; use doctor to inspect it")
        ignore = safe_path(self.root, ".gitignore")
        content = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
        # Establish privacy before writing any learning data. Preserve all existing rules.
        if not content.rstrip().endswith(".coderecall/"):
            atomic_write(ignore, (content.rstrip("\n") + "\n.coderecall/\n").lstrip("\n").encode())
        self.directory.mkdir(mode=0o700)
        with self.lock():
            atomic_write(self.path("config.toml"), render_config(DEFAULTS))
            atomic_write(
                self.path("manifest.json"), b'{"schema_version": 1, "application": "coderecall"}\n'
            )
            atomic_write(self.path("state.json"), encode_state(State()))

    def load_unlocked(self) -> State:
        from coderecall.storage.journal import recover

        recover(self.root)
        try:
            manifest = json_object(self.path("manifest.json").read_bytes())
            if manifest != {"schema_version": 1, "application": "coderecall"}:
                raise StateCorruptionError("Invalid/incompatible manifest")
            state_path = self.path("state.json")
            if state_path.stat().st_size > MAX_STATE_BYTES:
                raise StateCorruptionError("State exceeds the 64 MiB snapshot limit")
            state = decode_state(state_path.read_bytes())
            for problem in state.problems.values():
                for solution in problem.solutions:
                    safe_path(self.root, solution.path)
            return state
        except FileNotFoundError as exc:
            raise StateCorruptionError("Missing state or manifest; run doctor or restore") from exc

    def read(self) -> State:
        with self.lock():
            return self.load_unlocked()

    def save_unlocked(self, state: State) -> None:
        raw = encode_state(state)
        path = self.path("state.json")
        if path.exists():
            previous = path.read_bytes()
            if raw == previous:
                return
            decode_state(previous)
            atomic_write(self.path("state.previous.json"), previous)
        atomic_write(path, raw)

    @contextmanager
    def transaction(self) -> Iterator[State]:
        with self.lock():
            state = self.load_unlocked()
            self._writes = {}
            try:
                yield state
                if self._writes:
                    from coderecall.storage.journal import prepare, recover

                    prepare(self.root, encode_state(state), self._writes)
                    recover(self.root)
                else:
                    self.save_unlocked(state)
            finally:
                self._writes = None

    def stage_files(self, writes: dict[str, tuple[bytes | None, bytes]]) -> None:
        """Stage compare-and-replace images inside the current transaction."""
        if self._writes is None:
            raise RuntimeError("Generated writes require a state transaction")
        for name, (before, after) in writes.items():
            path = safe_path(self.root, name)
            staged = self._writes.get(name)
            current = staged[1] if staged else path.read_bytes() if path.exists() else None
            if current not in (before, after):
                from coderecall.domain.errors import ValidationError

                raise ValidationError(
                    f"Preserving modified file: {name}. Reconcile it before updating metadata"
                )
        for name, (before, after) in writes.items():
            if name in self._writes:
                before = self._writes[name][0]
            else:
                path = safe_path(self.root, name)
                before = path.read_bytes() if path.exists() else None
            self._writes[name] = (before, after)

    def staged_content(self, name: str) -> bytes | None:
        if self._writes is not None and name in self._writes:
            return self._writes[name][1]
        path = safe_path(self.root, name)
        return path.read_bytes() if path.is_file() else None

    def migrate(self) -> str:
        """Upgrade the documented pre-release v0 envelope, never guess unknown schemas."""
        with self.lock():
            raw = self.path("state.json").read_bytes()
            data = json_object(raw)
            if data.get("schema_version") == 1:
                decode_state(raw)
                return "Already schema 1"
            if data.get("schema_version") != 0:
                raise StateCorruptionError("No migration available for this schema")
            data["schema_version"] = 1
            # v0 used the same record shapes but lacked sync_status.
            data.setdefault("sync_status", "UNKNOWN")
            updated = encode_state(decode_state(json.dumps(data).encode()))
            backup = self.path("state.v0.backup.json")
            if backup.exists():
                raise StateCorruptionError(
                    "Migration backup already exists; inspect before retrying"
                )
            atomic_write(backup, raw)
            atomic_write(self.path("state.json"), updated)
            return "Migrated schema 0 → 1; original saved as state.v0.backup.json"
