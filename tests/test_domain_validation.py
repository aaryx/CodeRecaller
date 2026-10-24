import pytest

from coderecall.domain.errors import ValidationError
from coderecall.domain.validation import (
    LANGUAGES,
    fuzzy_match,
    performance,
    relative_path,
    slugify,
    validate_url,
)


def test_slugify_edge_cases():
    assert slugify("Two Sum") == "two-sum"
    assert slugify("  hello world  ") == "hello-world"
    assert slugify("C++ 20 & Algorithms!") == "c-20-algorithms"
    # Unicode NFKC normalization
    assert slugify(" café ") == "café"

    # Empty slug
    with pytest.raises(ValidationError, match="1–120 usable characters"):
        slugify("")
    with pytest.raises(ValidationError, match="1–120 usable characters"):
        slugify("!!!???---")

    # Overly long slug
    with pytest.raises(ValidationError, match="1–120 usable characters"):
        slugify("a" * 150)


def test_relative_path_safety():
    assert relative_path("solutions/two-sum.py") == "solutions/two-sum.py"
    assert relative_path("a/b/c.txt") == "a/b/c.txt"

    # Unsafe slashes or backslashes
    with pytest.raises(ValidationError, match="portable repository-relative paths"):
        relative_path("/absolute/path")
    with pytest.raises(ValidationError, match="portable repository-relative paths"):
        relative_path("C:\\windows\\path")
    with pytest.raises(ValidationError, match="portable repository-relative paths"):
        relative_path("folder\\file.py")

    # Reserved Windows device names
    for reserved in ["CON", "prn", "AUX", "NUL", "COM1", "LPT9"]:
        with pytest.raises(ValidationError, match="Unsafe or non-portable path component"):
            relative_path(f"folder/{reserved}/file.py")
        with pytest.raises(ValidationError, match="Unsafe or non-portable path component"):
            relative_path(f"folder/{reserved}.txt")

    # Trailing dots and spaces
    with pytest.raises(ValidationError, match="Unsafe or non-portable path component"):
        relative_path("folder./file.py")
    with pytest.raises(ValidationError, match="Unsafe or non-portable path component"):
        relative_path("folder /file.py")

    # Directory traversal
    with pytest.raises(ValidationError, match="Unsafe or non-portable path component"):
        relative_path("../outside.py")
    with pytest.raises(ValidationError, match="Unsafe or non-portable path component"):
        relative_path("a/../b.py")
    with pytest.raises(ValidationError, match="Unsafe or non-portable path component"):
        relative_path(".git/HEAD")

    # Illegal control chars and punctuation
    with pytest.raises(ValidationError, match="Unsafe or non-portable path component"):
        relative_path("folder<bad>/file.py")
    with pytest.raises(ValidationError, match="Unsafe or non-portable path component"):
        relative_path("folder|pipe/file.py")


def test_validate_url_security():
    # Valid HTTPS URLs
    assert validate_url("https://example.com/problem") == "https://example.com/problem"
    assert (
        validate_url("https://leetcode.com/problems/two-sum/", leetcode=True)
        == "https://leetcode.com/problems/two-sum/"
    )

    # Insecure HTTP
    with pytest.raises(ValidationError, match="valid HTTPS problem URL"):
        validate_url("http://example.com")

    # Embedded credentials
    with pytest.raises(ValidationError, match="valid HTTPS problem URL"):
        validate_url("https://user:pass@example.com")

    # Custom port
    with pytest.raises(ValidationError, match="valid HTTPS problem URL"):
        validate_url("https://example.com:8080/problem")

    # LeetCode domain or path check
    with pytest.raises(ValidationError, match="valid HTTPS problem URL"):
        validate_url("https://hackerrank.com/challenges/solve", leetcode=True)
    with pytest.raises(ValidationError, match="valid HTTPS problem URL"):
        validate_url("https://leetcode.com/discuss/general", leetcode=True)


def test_performance_validation():
    # Valid
    performance(seconds=100, attempts=2, hints=1, confidence=4)
    performance(seconds=0, attempts=1, hints=0, confidence=1)
    performance(seconds=604800, attempts=1000, hints=5, confidence=5)

    # Out of range seconds
    with pytest.raises(ValidationError, match="Invalid performance"):
        performance(seconds=-1, attempts=1, hints=0, confidence=3)
    with pytest.raises(ValidationError, match="Invalid performance"):
        performance(seconds=604801, attempts=1, hints=0, confidence=3)

    # Out of range attempts
    with pytest.raises(ValidationError, match="Invalid performance"):
        performance(seconds=10, attempts=0, hints=0, confidence=3)
    with pytest.raises(ValidationError, match="Invalid performance"):
        performance(seconds=10, attempts=1001, hints=0, confidence=3)

    # Out of range hints
    with pytest.raises(ValidationError, match="Invalid performance"):
        performance(seconds=10, attempts=1, hints=-1, confidence=3)
    with pytest.raises(ValidationError, match="Invalid performance"):
        performance(seconds=10, attempts=1, hints=6, confidence=3)

    # Out of range confidence
    with pytest.raises(ValidationError, match="Invalid performance"):
        performance(seconds=10, attempts=1, hints=0, confidence=0)
    with pytest.raises(ValidationError, match="Invalid performance"):
        performance(seconds=10, attempts=1, hints=0, confidence=6)


def test_fuzzy_match_scoring():
    # Empty query or text
    assert fuzzy_match("", "anything") == 1.0
    assert fuzzy_match("something", "") == 0.0

    # Exact substring matches
    assert fuzzy_match("two sum", "Two Sum Problem") == 1.0
    assert fuzzy_match("abc", "abcdef") == 1.0

    # Subsequence match with word boundaries and consecutive bonuses
    score = fuzzy_match("tws", "Two Sum")
    assert score > 0.3

    # Completely non-matching query
    assert fuzzy_match("xyz", "Two Sum") == 0.0

    # Threshold cutoff
    assert fuzzy_match("z", "Two Sum", threshold=0.9) == 0.0


def test_language_definitions():
    assert "python" in LANGUAGES
    assert LANGUAGES["python"][0] == ".py"
    assert "rust" in LANGUAGES
    assert LANGUAGES["rust"][0] == ".rs"
    assert "cpp" in LANGUAGES
    assert LANGUAGES["cpp"][0] == ".cpp"
