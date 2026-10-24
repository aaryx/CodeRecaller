from pathlib import Path
from typing import Protocol

from coderecall.domain.errors import AuthenticationError
from coderecall.integrations.process import run


class GitHostingProvider(Protocol):
    def status(self) -> dict[str, object]: ...
    def connect(self) -> str: ...
    def disconnect(self) -> str: ...


class GitHubProvider:
    """Delegate credential storage to GitHub CLI; never retrieve or print tokens."""

    def __init__(self, root: Path):
        self.root = root

    def status(self) -> dict[str, object]:
        result = run("gh", ["auth", "status", "--hostname", "github.com"], self.root)
        return {
            "authenticated": result.returncode == 0,
            "credential_owner": "GitHub CLI",
            "network": True,
        }

    def connect(self) -> str:
        result = run(
            "gh",
            ["auth", "login", "--hostname", "github.com", "--web", "--git-protocol", "https"],
            self.root,
            300,
            interactive=True,
        )
        if result.returncode:
            raise AuthenticationError("GitHub login failed; run gh auth login directly")
        return "Connected using GitHub CLI credential storage"

    def disconnect(self) -> str:
        result = run(
            "gh", ["auth", "logout", "--hostname", "github.com"], self.root, interactive=True
        )
        if result.returncode:
            raise AuthenticationError("GitHub logout failed")
        return "Disconnected from GitHub CLI (shared gh authentication)"
