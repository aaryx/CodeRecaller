from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from coderecall.application.catalog import Capture
from coderecall.application.project import Project
from coderecall.integrations.problems import ProblemMetadata
from coderecall.storage.local import LocalStore


@dataclass
class FakeClock:
    value: datetime = datetime(2026, 1, 1, 12, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture(autouse=True)
def isolated_user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user-config"))
    monkeypatch.delenv("CODERECALL_GIT_AUTO_COMMIT", raising=False)


@pytest.fixture
def project(tmp_path: Path, clock):
    root = tmp_path / "project"
    root.mkdir()
    LocalStore(root).initialize()
    return Project(root, clock)


@pytest.fixture
def capture():
    return Capture(
        ProblemMetadata(
            "Two Sum",
            "leetcode",
            "1",
            "two-sum",
            "https://leetcode.com/problems/two-sum/",
            "easy",
            ["array", "hash-table"],
        ),
        "python",
        "def solve(nums, target):\n    return [0, 1]\n",
        "Hash map",
        "O(n)",
        "O(n)",
        "private-memory",
        seconds=120,
    )
