"""Bounded import preview: retain paths and digests, never a repository's source in RAM."""

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from coderecall.application.catalog import Capture, Catalog, validate_capture
from coderecall.domain.errors import CodeRecallError, ValidationError
from coderecall.domain.validation import LANGUAGES
from coderecall.integrations.problems import ProblemMetadata
from coderecall.storage.codec import json_object
from coderecall.storage.paths import safe_path


@dataclass
class Candidate:
    path: str
    fingerprint: str
    size: int


@dataclass
class ImportPlan:
    root: Path
    captures: list[Candidate] = field(default_factory=list)
    recognized: list[str] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)
    unsupported: int = 0
    languages: dict[str, int] = field(default_factory=dict)

    def summary(self) -> dict[str, object]:
        return {
            "recognized": len(self.captures),
            "candidates": len(self.captures) + len(self.needs_review),
            "needs_review": self.needs_review,
            "unsupported": self.unsupported,
            "languages": self.languages,
            "files": self.recognized,
            "modified": False,
        }


def read_candidate(root: Path, relative: str) -> tuple[Capture, str]:
    path = safe_path(root, relative)
    if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValidationError("Source must be a regular file at most 2 MiB")
    with path.open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    language = next(
        (name for name, pair in LANGUAGES.items() if pair[0] == path.suffix.lower()), ""
    )
    metadata_path = (
        safe_path(root, path.parent.relative_to(root).as_posix() + "/metadata.json")
        if path.parent != root
        else safe_path(root, "metadata.json")
    )
    metadata_raw = b""
    if metadata_path.exists():
        if not metadata_path.is_file() or metadata_path.stat().st_size > 65536:
            raise ValidationError("Unsafe metadata")
        metadata_raw = metadata_path.read_bytes()
        data = json_object(metadata_raw)
        if data.get("schema_version", 1) != 1:
            raise ValidationError("Unsupported public metadata schema")
        strings = [
            "title",
            "platform",
            "external_id",
            "slug",
            "url",
            "difficulty",
            "approach",
            "time_complexity",
            "space_complexity",
        ]
        if any(key in data and not isinstance(data[key], str) for key in strings):
            raise ValidationError("Invalid metadata fields")
        lists: dict[str, list[str]] = {}
        for key in ["topics", "patterns", "tags"]:
            value = data.get(key, [])
            if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
                raise ValidationError(f"Invalid {key}")
            lists[key] = value
        meta = ProblemMetadata(
            str(data.get("title", "")),
            str(data.get("platform", "custom")),
            str(data.get("external_id", "")),
            str(data.get("slug", "")),
            str(data.get("url", "")),
            str(data.get("difficulty", "unknown")),
            lists["topics"],
        )
        capture = Capture(
            meta,
            language,
            raw.decode("utf-8"),
            str(data.get("approach", "")),
            str(data.get("time_complexity", "unknown")),
            str(data.get("space_complexity", "unknown")),
            patterns=lists["patterns"],
            tags=lists["tags"],
        )
    else:
        match = next(
            (
                m
                for value in [path.stem, path.parent.name, path.parent.parent.name]
                if (m := re.fullmatch(r"(\d+)[ ._-]+(.+)", value))
            ),
            None,
        )
        if not match:
            raise ValidationError("Cannot infer identity")
        external, title = match.groups()
        capture = Capture(
            ProblemMetadata(
                title.replace("-", " ").replace("_", " "), "custom", str(int(external))
            ),
            language,
            raw.decode("utf-8"),
        )
    validate_capture(capture)
    fingerprint = hashlib.sha256(raw + b"\0" + metadata_raw).hexdigest()
    return capture, fingerprint


def scan(root: Path) -> ImportPlan:
    if not root.is_dir() or root.is_symlink() or getattr(root, "is_junction", lambda: False)():
        raise ValidationError("Import source must be a real directory")
    root = root.resolve()
    plan = ImportPlan(root)
    suffixes = {pair[0] for pair in LANGUAGES.values()}
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(
            f
            for f in folders
            if f.casefold()
            not in {".git", ".coderecall", ".venv", "venv", "node_modules", "__pycache__"}
            and not (Path(directory) / f).is_symlink()
            and not getattr(Path(directory) / f, "is_junction", lambda: False)()
        )
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix.lower() not in suffixes:
                plan.unsupported += 1
                continue
            relative = path.relative_to(root).as_posix()
            try:
                capture, fingerprint = read_candidate(root, relative)
                plan.languages[capture.language] = plan.languages.get(capture.language, 0) + 1
                plan.captures.append(Candidate(relative, fingerprint, len(capture.code.encode())))
                plan.recognized.append(relative)
            except (CodeRecallError, UnicodeError, OSError):
                plan.needs_review.append(relative)
    return plan


def apply_import(catalog: Catalog, plan: ImportPlan) -> dict[str, object]:
    added = duplicates = 0
    errors: list[dict[str, str]] = []
    # Each bounded batch is durable. Retry deduplicates completed batches after a later failure.
    batches: list[list[Candidate]] = []
    batch: list[Candidate] = []
    size = 0
    for candidate in plan.captures:
        if batch and (len(batch) >= 100 or size + candidate.size > 8 * 1024 * 1024):
            batches.append(batch)
            batch, size = [], 0
        batch.append(candidate)
        size += candidate.size
    if batch:
        batches.append(batch)
    for batch in batches:
        batch_added = batch_duplicates = 0
        with catalog.store.transaction() as state:
            index = catalog.identity_index(state)
            for candidate in batch:
                try:
                    capture, fingerprint = read_candidate(plan.root, candidate.path)
                    if fingerprint != candidate.fingerprint:
                        raise ValidationError(
                            "Source or metadata changed after preview; preview again"
                        )
                    _, created = catalog.capture_into(state, capture, index)
                    batch_added += int(created)
                    batch_duplicates += int(not created)
                except (ValidationError, UnicodeError, OSError) as exc:
                    errors.append({"file": candidate.path, "error": str(exc)})
        added += batch_added
        duplicates += batch_duplicates
    return {
        "added": added,
        "duplicates": duplicates,
        "errors": errors,
        "needs_review": plan.needs_review,
    }
