"""All Git operations are centralized; no destructive synchronization."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from coderecall.domain.errors import GitError, SyncConflictError, ValidationError
from coderecall.integrations.process import run
from coderecall.storage.paths import safe_path


class GitProvider(Protocol):
    def status(self) -> dict[str, str]: ...
    def commit(self, paths: list[str], message: str) -> str: ...


@dataclass
class SyncPlan:
    state: str
    ahead: int = 0
    behind: int = 0
    action: str = "none"
    local_ref: str = ""
    remote_ref: str = ""


SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----|"
    r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})|"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}|"
    r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}|"
    r"hf_[A-Za-z0-9]{30,}|"
    r"xox[baprs]-[0-9A-Za-z]{10,48}|"
    r"(?:sk|rk)_live_[0-9a-zA-Z]{24}|"
    r"(?i:(?:api[_-]?key|password|secret|token|auth[_-]?token)\s*[:=]\s*['\"])[^'\"\s]{12,}"
)


class LocalGitProvider:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def command(self, *args: str, check: bool = True, timeout: int = 30) -> str:
        result = run("git", ["-c", "core.quotepath=false", *args], self.root, timeout)
        if check and result.returncode:
            # Git errors can contain credential-bearing remote URLs. Do not echo them.
            raise GitError(
                f"Git {args[0]} failed (exit {result.returncode}); inspect with git directly. Local data preserved"
            )
        return result.stdout.rstrip("\n")

    def available(self) -> bool:
        return self.command("rev-parse", "--is-inside-work-tree", check=False) == "true"

    def status(self) -> dict[str, str]:
        if not self.available():
            return {"repository": "absent", "branch": "", "changes": ""}
        return {
            "repository": str(self.root),
            "branch": self.command("symbolic-ref", "--short", "HEAD", check=False) or "DETACHED",
            "changes": self.command("status", "--porcelain=v1"),
        }

    def diff(self, paths: list[str]) -> str:
        if not paths:
            return "No owned files"
        return "\n".join(
            self.command("diff", "--no-ext-diff", "--no-textconv", "--", *paths[start : start + 40])
            for start in range(0, len(paths), 40)
        )

    def changed_owned(self, paths: list[str]) -> list[str]:
        if not paths:
            return []
        for path in paths:
            safe_path(self.root, path)
        changed = set(self.command("diff", "--name-only", "-z").split("\0"))
        changed.update(self.command("diff", "--cached", "--name-only", "-z").split("\0"))
        changed.update(self.command("ls-files", "--others", "--exclude-standard", "-z").split("\0"))
        return sorted(changed.intersection(paths))

    def commit(self, paths: list[str], message: str) -> str:
        if not message.strip() or len(message) > 200:
            raise ValidationError("Commit message must have 1–200 characters")
        if self.status()["branch"] == "DETACHED":
            raise GitError("Attach HEAD to a branch before committing")
        if self.command("ls-files", "-u"):
            raise SyncConflictError("Resolve existing Git conflicts first")
        staged = set(self.command("diff", "--cached", "--name-only", "-z").split("\0")) - {""}
        if staged - set(paths):
            raise GitError("Unrelated staged files exist; commit or unstage them yourself first")
        changed = self.changed_owned(paths)
        if not changed:
            return "No owned changes to commit"
        for start in range(0, len(changed), 40):
            self.command("add", "--", *changed[start : start + 40])
        self.command("commit", "-m", message)
        return self.command("rev-parse", "HEAD")

    def upstream(self) -> str:
        value = self.command(
            "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", check=False
        )
        if not value:
            raise GitError("No upstream. Configure a remote and tracking branch with Git first")
        return value

    def remote(self) -> str:
        branch = self.status()["branch"]
        remote = self.command("config", "--get", f"branch.{branch}.remote", check=False)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", remote) or remote.startswith("-") or remote == ".":
            raise GitError("A named remote tracking branch is required")
        url = self.command("remote", "get-url", remote)
        # Git's ext transport can execute commands. Restrict the supported remote protocols.
        if (
            "::" in url
            or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url)
            and not url.startswith(("https://", "ssh://", "file://"))
        ):
            raise GitError("Unsupported Git remote protocol")
        if url.startswith("https://") and "@" in url.split("/", 3)[2]:
            raise GitError("Remove credentials from the remote URL; use a credential manager")
        return remote

    def plan(self, fetch: bool = False) -> SyncPlan:
        if self.command("ls-files", "-u"):
            return SyncPlan("CONFLICT", action="resolve conflicts manually")
        if self.status()["changes"]:
            raise SyncConflictError(
                "Working tree is dirty; commit or preserve your work before sync"
            )
        self.upstream()
        remote = self.remote()
        if fetch:
            self.command("fetch", "--no-tags", remote, timeout=60)
        counts = self.command("rev-list", "--left-right", "--count", "HEAD...@{upstream}").split()
        ahead, behind = map(int, counts)
        refs = {
            "local_ref": self.command("rev-parse", "HEAD"),
            "remote_ref": self.command("rev-parse", "@{upstream}"),
        }
        if ahead and behind:
            return SyncPlan("DIVERGED", ahead, behind, "reconcile manually", **refs)
        if behind:
            return SyncPlan("REMOTE_AHEAD", ahead, behind, "fast-forward", **refs)
        if ahead:
            return SyncPlan("LOCAL_AHEAD", ahead, behind, "push", **refs)
        return SyncPlan("CLEAN", local_ref=refs["local_ref"], remote_ref=refs["remote_ref"])

    def scan_outgoing(self) -> None:
        self.upstream()
        commits = self.command("rev-list", "@{upstream}..HEAD").splitlines()
        checked: set[str] = set()
        for commit in commits:
            tree = self.command("ls-tree", "-r", "-z", commit)
            for entry in filter(None, tree.split("\0")):
                header, path = entry.split("\t", 1)
                _, kind, oid = header.split()
                if path.casefold() == ".coderecall" or path.casefold().startswith(".coderecall/"):
                    raise ValidationError(
                        "Outgoing history contains private .coderecall state; remove it from history before pushing"
                    )
                if kind != "blob" or oid in checked:
                    continue
                checked.add(oid)
                if int(self.command("cat-file", "-s", oid)) > 8 * 1024 * 1024:
                    raise ValidationError(
                        "Outgoing blob exceeds secret scan limit; inspect it manually"
                    )
                if SECRET.search(self.command("cat-file", "blob", oid)):
                    raise ValidationError(
                        "Likely secret found in outgoing history; push blocked (secret content suppressed)"
                    )

    def push(self, scan: bool = True) -> str:
        plan = self.plan()
        if plan.state in {"DIVERGED", "CONFLICT", "REMOTE_AHEAD"}:
            raise SyncConflictError("Fetch and reconcile remote changes before pushing")
        if scan:
            self.scan_outgoing()
        remote = self.remote()
        branch = self.status()["branch"]
        merge = self.command("config", "--get", f"branch.{branch}.merge")
        if not merge.startswith("refs/heads/"):
            raise GitError("Invalid tracking branch")
        self.command("push", remote, f"HEAD:{merge}", timeout=60)
        return "Pushed genuine local commits"

    def execute_plan(self, plan: SyncPlan, scan: bool = True) -> str:
        if self.plan() != plan:
            raise SyncConflictError("Git state changed since preview; calculate a new plan")
        if plan.state in {"DIVERGED", "CONFLICT"}:
            raise SyncConflictError(
                "Sync stopped; reconcile branches with Git. No reset/clean was performed"
            )
        if plan.state == "REMOTE_AHEAD":
            entries = self.command("ls-tree", "-r", "-z", "@{upstream}").split("\0")
            for entry in filter(None, entries):
                header, path = entry.split("\t", 1)
                if path.casefold() == ".coderecall" or path.casefold().startswith(".coderecall/"):
                    raise SyncConflictError(
                        "Remote contains private .coderecall paths; refusing to overwrite learning state"
                    )
                if header.startswith("120000"):
                    raise SyncConflictError("Remote contains symlinks; inspect and merge manually")
            self.command("merge", "--ff-only", "@{upstream}")
            return "Fast-forwarded local branch; use import to adopt new solution metadata"
        if plan.state == "LOCAL_AHEAD":
            return self.push(scan)
        return "Already synchronized"
