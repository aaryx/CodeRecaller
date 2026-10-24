"""No unsafe fallback. Execution is unavailable without an explicitly trusted runner."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class ResultState(StrEnum):
    PASS = "PASS"  # noqa: S105 -- execution result, not a credential
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    MEMORY_LIMIT = "MEMORY_LIMIT"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    SANDBOX_ERROR = "SANDBOX_ERROR"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class RunResult:
    state: ResultState
    detail: str


class CodeRunner(Protocol):
    def run(self, source: Path) -> RunResult: ...


class UnavailableRunner:
    def run(self, source: Path) -> RunResult:
        return RunResult(
            ResultState.UNAVAILABLE,
            "Execution is disabled. Enable execution.enabled and install a trusted Linux Python Docker image to use the optional sandbox.",
        )
