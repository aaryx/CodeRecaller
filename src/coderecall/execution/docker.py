"""Optional Linux-container runner. No host mounts, network, image pull or shell."""

import json
import re
from pathlib import Path
from uuid import uuid4

from coderecall.domain.errors import ProviderError, SandboxError, ValidationError
from coderecall.execution.runner import ResultState, RunResult
from coderecall.integrations.process import run

# Maximum script size permitted for inline container execution (64 KiB).
# This is well below the Linux kernel MAX_ARG_STRLEN (128 KiB) to prevent execve E2BIG errors.
MAX_INLINE_SCRIPT_BYTES = 64 * 1024


class DockerRunner:
    def __init__(self, root: Path, image: str, timeout: int = 5):
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@:-]{0,249}", image)
            or not 1 <= timeout <= 60
        ):
            raise ValidationError("Invalid sandbox image or timeout")
        self.root, self.image, self.timeout = root, image, timeout

    def command(self, *args: str, timeout: int = 15) -> str:
        result = run("docker", list(args), self.root, timeout=timeout)
        if result.returncode:
            raise SandboxError(f"Docker {args[0]} failed; container details suppressed")
        return result.stdout.strip()

    def run(self, source: Path) -> RunResult:
        if source.is_symlink() or not source.is_file():
            raise ValidationError("Sandbox accepts an existing regular file")

        if source.suffix != ".py":
            raise ValidationError(
                "Docker sandbox currently supports Python (.py) scripts using a trusted "
                "Linux Python Docker image. Other languages are not supported in the "
                "read-only sandbox without language-specific container manifests."
            )

        try:
            size = source.stat().st_size
        except OSError as exc:
            raise ValidationError(f"Unable to inspect sandbox script: {exc}") from exc

        if size > MAX_INLINE_SCRIPT_BYTES:
            raise ValidationError(
                f"Sandbox accepts Python scripts at most {MAX_INLINE_SCRIPT_BYTES // 1024} KiB"
            )

        try:
            source_content = source.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError("Sandbox script must be valid UTF-8 text") from exc

        if not source_content.strip():
            raise ValidationError("Sandbox script cannot be empty")

        entrypoint = "python"
        args = ["-I", "-B", "-c", source_content]

        try:
            info = json.loads(self.command("info", "--format", "{{json .}}"))
            if info.get("OSType") != "linux" or not any(
                "seccomp" in item for item in info.get("SecurityOptions", [])
            ):
                return RunResult(
                    ResultState.UNAVAILABLE, "Linux Docker with default seccomp is required"
                )
            if not all(info.get(key) for key in ["MemoryLimit", "PidsLimit", "CpuCfsQuota"]):
                return RunResult(
                    ResultState.UNAVAILABLE, "Docker cannot enforce the required resource limits"
                )
            image = json.loads(self.command("image", "inspect", self.image))[0]
            if image.get("Os") != "linux" or image.get("Config", {}).get("Volumes"):
                return RunResult(
                    ResultState.UNAVAILABLE, "Use a Linux image without declared volumes"
                )
        except (ProviderError, SandboxError):
            return RunResult(
                ResultState.UNAVAILABLE,
                "Docker or the preinstalled image is unavailable; no image was pulled",
            )
        except (ValueError, KeyError, TypeError, IndexError):
            return RunResult(ResultState.SANDBOX_ERROR, "Invalid Docker capability response")

        name = "coderecall-" + uuid4().hex
        created = False
        result = RunResult(ResultState.SANDBOX_ERROR, "Container did not complete")
        try:
            cmd = [
                "create",
                "--name",
                name,
                "--pull",
                "never",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--user",
                "65534:65534",
                "--pids-limit",
                "32",
                "--memory",
                "128m",
                "--memory-swap",
                "128m",
                "--cpus",
                "0.5",
                "--ulimit",
                "nofile=64:64",
                "--ulimit",
                "fsize=1048576:1048576",
                "--ulimit",
                "core=0:0",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",  # noqa: S108
                "--log-driver",
                "none",
                "--workdir",
                "/",
                "--entrypoint",
                entrypoint,
                str(image["Id"]),
            ] + args

            self.command(*cmd)
            created = True

            self.command("start", name)
            try:
                exit_code = int(self.command("wait", name, timeout=self.timeout))
            except ProviderError:
                try:
                    self.command("kill", name)
                except (ProviderError, SandboxError):
                    pass
                result = RunResult(ResultState.TIMEOUT, "Wall-clock limit exceeded")
            else:
                status = json.loads(self.command("inspect", "--format", "{{json .State}}", name))
                if status.get("OOMKilled"):
                    result = RunResult(ResultState.MEMORY_LIMIT, "128 MiB memory limit exceeded")
                elif exit_code == 0:
                    result = RunResult(
                        ResultState.PASS,
                        "Script exited zero; only explicitly supplied assertions were checked, not general problem correctness",
                    )
                elif exit_code == 1:
                    result = RunResult(
                        ResultState.FAIL,
                        "Script failed (assertion or exception); output is discarded",
                    )
                else:
                    result = RunResult(ResultState.RUNTIME_ERROR, f"Script exited {exit_code}")
        except (ProviderError, SandboxError, ValueError, KeyError, TypeError, OSError):
            result = RunResult(
                ResultState.SANDBOX_ERROR, "Sandbox operation failed; no host execution fallback"
            )
        finally:
            if created:
                try:
                    self.command("rm", "--force", name)
                except (ProviderError, SandboxError):
                    result = RunResult(
                        ResultState.SANDBOX_ERROR,
                        f"Cleanup failed; remove only the owned container with: docker rm --force {name}",
                    )
        return result
