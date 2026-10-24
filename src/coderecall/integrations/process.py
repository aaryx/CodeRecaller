import os
import shutil
import subprocess
from pathlib import Path

from coderecall.domain.errors import ProviderError


def run(
    executable: str, arguments: list[str], cwd: Path, timeout: int = 30, interactive: bool = False
) -> subprocess.CompletedProcess[str]:
    resolved = shutil.which(executable)
    if not resolved:
        raise ProviderError(f"Required executable unavailable: {executable}")
    author_keys = {
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    }
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k in author_keys}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_LITERAL_PATHSPECS": "1", "NO_COLOR": "1"})
    try:
        return subprocess.run(
            [resolved, *arguments],
            cwd=cwd,
            env=env,
            shell=False,
            capture_output=not interactive,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(f"{executable} timed out; local data is preserved") from exc
    except OSError as exc:
        raise ProviderError(f"Unable to start {executable}") from exc
