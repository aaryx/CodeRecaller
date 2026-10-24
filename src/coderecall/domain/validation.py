import re
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from coderecall.domain.errors import ValidationError

LANGUAGES = {
    "python": (".py", "solution.py"),
    "java": (".java", "Solution.java"),
    "cpp": (".cpp", "solution.cpp"),
    "c": (".c", "solution.c"),
    "javascript": (".js", "solution.js"),
    "typescript": (".ts", "solution.ts"),
    "rust": (".rs", "solution.rs"),
    "go": (".go", "solution.go"),
    "csharp": (".cs", "Solution.cs"),
    "kotlin": (".kt", "Solution.kt"),
    "swift": (".swift", "solution.swift"),
    "ruby": (".rb", "solution.rb"),
    "scala": (".scala", "Solution.scala"),
    "php": (".php", "solution.php"),
    "dart": (".dart", "solution.dart"),
    "r": (".r", "solution.r"),
    "lua": (".lua", "solution.lua"),
    "elixir": (".ex", "solution.ex"),
    "haskell": (".hs", "Solution.hs"),
    "sql": (".sql", "solution.sql"),
    "zig": (".zig", "solution.zig"),
    "nim": (".nim", "solution.nim"),
}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    slug = re.sub(r"[^\w-]+", "-", text, flags=re.UNICODE).strip("-_")
    if not slug or len(slug) > 120:
        raise ValidationError("Provide a title/slug with 1–120 usable characters")
    return slug


def relative_path(value: str) -> str:
    if not value or "\\" in value or ":" in value or value.startswith("/"):
        raise ValidationError("Paths must be portable repository-relative paths")
    path = PurePosixPath(value)
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(10)),
        *(f"LPT{i}" for i in range(10)),
    }
    for part in value.split("/"):
        if (
            part.casefold() in {"", ".", "..", ".git"}
            or part.endswith((".", " "))
            or part.split(".")[0].upper() in reserved
            or any(ord(c) < 32 or c in '<>"|?*' for c in part)
        ):
            raise ValidationError("Unsafe or non-portable path component")
    return path.as_posix()


def validate_url(value: str, leetcode: bool = False) -> str:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or any(ord(c) < 33 for c in value)
        ):
            raise ValueError
        if leetcode and (
            parsed.hostname not in {"leetcode.com", "www.leetcode.com"}
            or not re.fullmatch(r"/problems/[a-z0-9-]+(?:/.*)?", parsed.path)
        ):
            raise ValueError
    except ValueError as exc:
        raise ValidationError(
            "Use a valid HTTPS problem URL (no credentials or custom port)"
        ) from exc
    return value


def performance(seconds: int, attempts: int, hints: int, confidence: int) -> None:
    if (
        not 0 <= seconds <= 604800
        or not 1 <= attempts <= 1000
        or not 0 <= hints <= 5
        or not 1 <= confidence <= 5
    ):
        raise ValidationError(
            "Invalid performance: seconds 0–604800, attempts 1–1000, hints 0–5, confidence 1–5"
        )


def fuzzy_match(query: str, text: str, threshold: float = 0.4) -> float:
    """Simple fuzzy matching using subsequence scoring.

    Returns a score between 0.0 and 1.0 where 1.0 is an exact match.
    Implements a case-insensitive subsequence scorer with bonus for
    consecutive matches and word-boundary alignment.
    """
    query = query.casefold().strip()
    text = text.casefold().strip()

    if not query:
        return 1.0
    if not text:
        return 0.0

    # Exact substring match — highest score
    if query in text:
        return 1.0

    # Subsequence match with scoring
    score = 0.0
    q_idx = 0
    consecutive = 0
    last_match = -2

    for t_idx, char in enumerate(text):
        if q_idx < len(query) and char == query[q_idx]:
            # Base point for matching
            score += 1.0
            # Bonus for consecutive matches
            if t_idx == last_match + 1:
                consecutive += 1
                score += consecutive * 0.5
            else:
                consecutive = 0
            # Bonus for word boundary matches (start of word)
            if t_idx == 0 or text[t_idx - 1] in " -_.,;:":
                score += 0.75
            last_match = t_idx
            q_idx += 1

    if q_idx < len(query):
        return 0.0  # Not all query chars matched

    # Normalize: max possible score ≈ len(query) * (1 + word_bonus + consecutive_bonus)
    max_score = len(query) * 2.25
    normalized = min(1.0, score / max_score)

    return normalized if normalized >= threshold else 0.0
