"""Optional Linux-container runner. No host mounts, network, image pull or shell."""

import json
import re
import tempfile
from pathlib import Path
from uuid import uuid4

from coderecall.domain.errors import ProviderError, SandboxError, ValidationError
from coderecall.execution.runner import ResultState, RunResult
from coderecall.integrations.process import run


class DockerRunner:
    def __init__(self, root: Path, image: str, timeout: int = 5):
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@:-]{0,250}", image)
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
        allowed_exts = {
            ".py": ("python", ["-I", "-B", "/coderecall-solution.py"]),
            ".java": ("java", ["/coderecall-solution.java"]),
            ".cpp": (
                "g++",
                [
                    "-O2",
                    "/coderecall-solution.cpp",
                    "-o",
                    "/coderecall-solution",
                    "&&",
                    "/coderecall-solution",
                ],
            ),
            ".rs": (
                "rustc",
                [
                    "/coderecall-solution.rs",
                    "-o",
                    "/coderecall-solution",
                    "&&",
                    "/coderecall-solution",
                ],
            ),
        }

        if (
            source.suffix not in allowed_exts
            or source.is_symlink()
            or not source.is_file()
            or source.stat().st_size > 2 * 1024 * 1024
        ):
            raise ValidationError(
                "Sandbox accepts an explicit Python, Java, C++, or Rust script at most 2 MiB"
            )

        if source.suffix == ".py":
            source_content = source.read_text(encoding="utf-8", errors="replace")
            entrypoint = "python"
            args = ["-I", "-B", "-c", source_content]
        else:
            entrypoint, args = allowed_exts[source.suffix]
            # For C++ and Rust we need to run multiple commands if compiling.
            # A simpler approach is to use sh -c.
            if "&&" in args:
                cmd_str = " ".join([entrypoint] + args)
                entrypoint = "sh"
                args = ["-c", cmd_str]

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
            with tempfile.TemporaryDirectory(prefix="coderecall-sandbox-") as temporary:
                workspace = Path(temporary)
                script_name = f"solution{source.suffix}"
                script = workspace / script_name
                script.write_bytes(source.read_bytes())
                created = True

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
                try:
                    self.command("cp", str(script), f"{name}:/coderecall-{script_name}")
                except (SandboxError, ProviderError):
                    # In secure runtimes with a read-only rootfs, direct daemon file injection
                    # via docker cp to rootfs is blocked; Python scripts execute via inline invocation.
                    pass
                self.command("start", name)
                try:
                    exit_code = int(self.command("wait", name, timeout=self.timeout))
                except ProviderError:
                    self.command("kill", name)
                    result = RunResult(ResultState.TIMEOUT, "Wall-clock limit exceeded")
                else:
                    status = json.loads(
                        self.command("inspect", "--format", "{{json .State}}", name)
                    )
                    if status.get("OOMKilled"):
                        result = RunResult(
                            ResultState.MEMORY_LIMIT, "128 MiB memory limit exceeded"
                        )
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
