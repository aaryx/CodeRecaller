import os
import tempfile
from pathlib import Path

from coderecall.domain.errors import ValidationError
from coderecall.domain.validation import relative_path


def safe_path(root: Path, relative: str) -> Path:
    relative_path(relative)
    root = root.resolve()
    target = root.joinpath(*relative.split("/"))
    for part in [target, *target.parents]:
        if part == root:
            break
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValidationError("Symlink/junction paths are not allowed")
    if not target.resolve().is_relative_to(root):
        raise ValidationError("Path escapes the project")
    return target


def atomic_write(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise ValidationError("Refusing to replace a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".cr-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def create_or_match(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValidationError(f"Existing file differs; preserving {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental replacement of user files.
    with path.open("xb") as stream:
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        except OSError:
            stream.close()
            path.unlink(missing_ok=True)
            raise
