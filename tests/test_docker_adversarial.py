import json
from pathlib import Path

import pytest

from coderecall.domain.errors import ProviderError, SandboxError, ValidationError
from coderecall.execution.docker import MAX_INLINE_SCRIPT_BYTES, DockerRunner
from coderecall.execution.runner import ResultState


def make_runner(
    tmp_path: Path, image: str = "python:3.12-alpine", timeout: int = 5
) -> DockerRunner:
    return DockerRunner(tmp_path, image, timeout)


def valid_docker_info() -> str:
    return json.dumps(
        {
            "OSType": "linux",
            "SecurityOptions": ["name=seccomp,profile=builtin"],
            "MemoryLimit": True,
            "PidsLimit": True,
            "CpuCfsQuota": True,
        }
    )


def valid_image_inspect() -> str:
    return json.dumps([{"Id": "sha256:d0cc4e0f1e2a3b4c5d6e", "Os": "linux", "Config": {}}])


# ---------------------------------------------------------------------------
# Input Validation & Guardrails
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_image",
    [
        "",
        "-it",
        "--privileged",
        "; rm -rf /",
        "python:3.12;cat /etc/passwd",
        "a" * 251,
        " space in image",
        "$PATH",
    ],
)
def test_docker_runner_rejects_malicious_image_names(tmp_path, bad_image):
    with pytest.raises(ValidationError, match="Invalid sandbox image or timeout"):
        DockerRunner(tmp_path, bad_image)


@pytest.mark.parametrize("bad_timeout", [0, -1, 61, 100])
def test_docker_runner_rejects_invalid_timeouts(tmp_path, bad_timeout):
    with pytest.raises(ValidationError, match="Invalid sandbox image or timeout"):
        DockerRunner(tmp_path, "python:3.12-alpine", timeout=bad_timeout)


def test_docker_runner_rejects_nonexistent_file(tmp_path):
    runner = make_runner(tmp_path)
    with pytest.raises(ValidationError, match="existing regular file"):
        runner.run(tmp_path / "does_not_exist.py")


def test_docker_runner_rejects_directory(tmp_path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    runner = make_runner(tmp_path)
    with pytest.raises(ValidationError, match="existing regular file"):
        runner.run(sub)


def test_docker_runner_rejects_non_python_files(tmp_path):
    runner = make_runner(tmp_path)
    for ext in [".java", ".cpp", ".rs", ".js", ".sh", ".exe", ".bin"]:
        target = tmp_path / f"solution{ext}"
        target.write_text("print('test')", encoding="utf-8")
        with pytest.raises(ValidationError, match="Docker sandbox currently supports Python"):
            runner.run(target)


def test_docker_runner_rejects_oversized_scripts(tmp_path):
    runner = make_runner(tmp_path)
    oversized = tmp_path / "huge.py"
    oversized.write_bytes(b"# comment\n" * 8000)
    assert oversized.stat().st_size > MAX_INLINE_SCRIPT_BYTES
    with pytest.raises(ValidationError, match="at most 64 KiB"):
        runner.run(oversized)


def test_docker_runner_rejects_empty_script(tmp_path):
    runner = make_runner(tmp_path)
    empty = tmp_path / "empty.py"
    empty.write_text("   \n\t  \n", encoding="utf-8")
    with pytest.raises(ValidationError, match="cannot be empty"):
        runner.run(empty)


def test_docker_runner_rejects_non_utf8_binary(tmp_path):
    runner = make_runner(tmp_path)
    binary = tmp_path / "binary.py"
    binary.write_bytes(b"\x80\xff\xfe\x00\x01\x02")
    with pytest.raises(ValidationError, match="must be valid UTF-8 text"):
        runner.run(binary)


def test_docker_runner_rejects_embedded_null_byte(tmp_path):
    runner = make_runner(tmp_path)
    null_script = tmp_path / "null.py"
    null_script.write_bytes(b"print('hello')\x00print('world')")
    with pytest.raises(ValidationError, match="must not contain null bytes"):
        runner.run(null_script)


def test_docker_runner_read_text_oserror_raises_validation_error(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    script = tmp_path / "script.py"
    script.write_text("print('test')", encoding="utf-8")

    def broken_read(*args, **kwargs):
        raise OSError("Permission denied reading file content")

    monkeypatch.setattr(Path, "read_text", broken_read)
    with pytest.raises(ValidationError, match="Unable to inspect sandbox script"):
        runner.run(script)


def test_docker_runner_command_failure_raises_sandbox_error(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    runner = make_runner(tmp_path)
    fake_proc = MagicMock(returncode=1, stdout="", stderr="error")
    monkeypatch.setattr("coderecall.execution.docker.run", lambda *args, **kwargs: fake_proc)
    with pytest.raises(SandboxError, match="Docker info failed"):
        runner.command("info")


def test_docker_runner_stat_oserror_raises_validation_error(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    script = tmp_path / "script.py"
    script.write_text("print('test')", encoding="utf-8")

    def broken_stat(*args, **kwargs):
        raise OSError("Permission denied reading file metadata")

    monkeypatch.setattr(Path, "stat", broken_stat)
    with pytest.raises(ValidationError, match="Unable to inspect sandbox script"):
        runner.run(script)


# ---------------------------------------------------------------------------
# Host Docker Precondition Checks
# ---------------------------------------------------------------------------


def test_docker_runner_unavailable_when_docker_cli_missing(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)

    def fake_command(*args, **kwargs):
        raise ProviderError("Docker CLI missing")

    monkeypatch.setattr(runner, "command", fake_command)
    script = tmp_path / "test.py"
    script.write_text("assert True", encoding="utf-8")
    result = runner.run(script)
    assert result.state == ResultState.UNAVAILABLE
    assert "Docker or the preinstalled image is unavailable" in result.detail


@pytest.mark.parametrize(
    "missing_capability",
    ["MemoryLimit", "PidsLimit", "CpuCfsQuota"],
)
def test_docker_runner_unavailable_when_resource_limits_unsupported(
    tmp_path, monkeypatch, missing_capability
):
    runner = make_runner(tmp_path)
    info_dict = {
        "OSType": "linux",
        "SecurityOptions": ["name=seccomp,profile=builtin"],
        "MemoryLimit": True,
        "PidsLimit": True,
        "CpuCfsQuota": True,
    }
    info_dict[missing_capability] = False

    def fake_command(*args, **kwargs):
        if args[0] == "info":
            return json.dumps(info_dict)
        return ""

    monkeypatch.setattr(runner, "command", fake_command)
    script = tmp_path / "test.py"
    script.write_text("assert True", encoding="utf-8")
    result = runner.run(script)
    assert result.state == ResultState.UNAVAILABLE
    assert "Docker cannot enforce the required resource limits" in result.detail


def test_docker_runner_unavailable_when_seccomp_missing(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    info_dict = {
        "OSType": "linux",
        "SecurityOptions": ["name=apparmor"],
        "MemoryLimit": True,
        "PidsLimit": True,
        "CpuCfsQuota": True,
    }

    def fake_command(*args, **kwargs):
        if args[0] == "info":
            return json.dumps(info_dict)
        return ""

    monkeypatch.setattr(runner, "command", fake_command)
    script = tmp_path / "test.py"
    script.write_text("assert True", encoding="utf-8")
    result = runner.run(script)
    assert result.state == ResultState.UNAVAILABLE
    assert "default seccomp is required" in result.detail


def test_docker_runner_unavailable_when_image_has_volumes(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)

    def fake_command(*args, **kwargs):
        if args[0] == "info":
            return valid_docker_info()
        if args[0] == "image":
            return json.dumps(
                [{"Id": "sha256:vol", "Os": "linux", "Config": {"Volumes": {"/data": {}}}}]
            )
        return ""

    monkeypatch.setattr(runner, "command", fake_command)
    script = tmp_path / "test.py"
    script.write_text("assert True", encoding="utf-8")
    result = runner.run(script)
    assert result.state == ResultState.UNAVAILABLE
    assert "without declared volumes" in result.detail


def test_docker_runner_unavailable_when_image_is_not_linux(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)

    def fake_command(*args, **kwargs):
        if args[0] == "info":
            return valid_docker_info()
        if args[0] == "image":
            return json.dumps([{"Id": "sha256:win", "Os": "windows", "Config": {}}])
        return ""

    monkeypatch.setattr(runner, "command", fake_command)
    script = tmp_path / "test.py"
    script.write_text("assert True", encoding="utf-8")
    result = runner.run(script)
    assert result.state == ResultState.UNAVAILABLE
    assert "without declared volumes" in result.detail


def test_docker_runner_handles_malformed_docker_info(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)

    def fake_command(*args, **kwargs):
        if args[0] == "info":
            return "NOT_VALID_JSON{}"
        return ""

    monkeypatch.setattr(runner, "command", fake_command)
    script = tmp_path / "test.py"
    script.write_text("assert True", encoding="utf-8")
    result = runner.run(script)
    assert result.state == ResultState.SANDBOX_ERROR
    assert "Invalid Docker capability response" in result.detail


# ---------------------------------------------------------------------------
# Container Orchestration, Exit Codes, and Cleanup
# ---------------------------------------------------------------------------


def test_docker_create_receives_all_security_flags(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    calls = []

    def fake_command(*args, **kwargs):
        calls.append(args)
        if args[0] == "info":
            return valid_docker_info()
        if args[0] == "image":
            return valid_image_inspect()
        if args[0] == "wait":
            return "0"
        if args[0] == "inspect":
            return json.dumps({"OOMKilled": False})
        return ""

    monkeypatch.setattr(runner, "command", fake_command)
    script = tmp_path / "test.py"
    content = "a = 1 + 1\nassert a == 2"
    script.write_text(content, encoding="utf-8")

    result = runner.run(script)
    assert result.state == ResultState.PASS

    create_cmd = next(c for c in calls if c[0] == "create")
    assert "--read-only" in create_cmd
    assert "--network" in create_cmd and create_cmd[create_cmd.index("--network") + 1] == "none"
    assert "--pull" in create_cmd and create_cmd[create_cmd.index("--pull") + 1] == "never"
    assert "--cap-drop" in create_cmd and create_cmd[create_cmd.index("--cap-drop") + 1] == "ALL"
    assert "--security-opt" in create_cmd and "no-new-privileges:true" in create_cmd
    assert "--user" in create_cmd and create_cmd[create_cmd.index("--user") + 1] == "65534:65534"
    assert "--pids-limit" in create_cmd and create_cmd[create_cmd.index("--pids-limit") + 1] == "32"
    assert "--memory" in create_cmd and create_cmd[create_cmd.index("--memory") + 1] == "128m"
    assert (
        "--memory-swap" in create_cmd
        and create_cmd[create_cmd.index("--memory-swap") + 1] == "128m"
    )
    assert "--cpus" in create_cmd and create_cmd[create_cmd.index("--cpus") + 1] == "0.5"
    assert "--ulimit" in create_cmd and "nofile=64:64" in create_cmd
    assert "--ulimit" in create_cmd and "fsize=1048576:1048576" in create_cmd
    assert "--ulimit" in create_cmd and "core=0:0" in create_cmd
    assert (
        "--tmpfs" in create_cmd and "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777" in create_cmd  # noqa: S108
    )
    assert (
        "--log-driver" in create_cmd and create_cmd[create_cmd.index("--log-driver") + 1] == "none"
    )
    assert "--workdir" in create_cmd and create_cmd[create_cmd.index("--workdir") + 1] == "/"
    assert (
        "--entrypoint" in create_cmd
        and create_cmd[create_cmd.index("--entrypoint") + 1] == "python"
    )

    # Verify no host volume mounts
    assert "--volume" not in create_cmd and "-v" not in create_cmd and "--mount" not in create_cmd

    # Verify inline python arguments
    assert create_cmd[-4:] == ("-I", "-B", "-c", content)

    # Verify container removal was executed
    assert calls[-1][0:2] == ("rm", "--force")


def test_docker_create_failure_does_not_attempt_rm(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    calls = []

    def fake_command(*args, **kwargs):
        calls.append(args)
        if args[0] == "info":
            return valid_docker_info()
        if args[0] == "image":
            return valid_image_inspect()
        if args[0] == "create":
            raise SandboxError("docker create failed: daemon rejected request")
        return ""

    monkeypatch.setattr(runner, "command", fake_command)
    script = tmp_path / "test.py"
    script.write_text("assert True", encoding="utf-8")

    result = runner.run(script)
    assert result.state == ResultState.SANDBOX_ERROR
    # Verify that rm --force was NOT called on a non-existent container
    assert not any(c[0] == "rm" for c in calls)


def test_docker_nonzero_exit_codes_reported_accurately(tmp_path, monkeypatch):
    script = tmp_path / "test.py"
    script.write_text("raise ValueError('fail')", encoding="utf-8")

    # Code 1 -> FAIL (assertion/unhandled exception)
    runner = make_runner(tmp_path)
    monkeypatch.setattr(
        runner,
        "command",
        lambda *args, **kwargs: (
            valid_docker_info()
            if args[0] == "info"
            else (
                valid_image_inspect()
                if args[0] == "image"
                else (
                    "1"
                    if args[0] == "wait"
                    else (json.dumps({"OOMKilled": False}) if args[0] == "inspect" else "")
                )
            )
        ),
    )
    res = runner.run(script)
    assert res.state == ResultState.FAIL
    assert "Script failed" in res.detail

    # Code 2 -> RUNTIME_ERROR (syntax error or argument error)
    runner2 = make_runner(tmp_path)
    monkeypatch.setattr(
        runner2,
        "command",
        lambda *args, **kwargs: (
            valid_docker_info()
            if args[0] == "info"
            else (
                valid_image_inspect()
                if args[0] == "image"
                else (
                    "2"
                    if args[0] == "wait"
                    else (json.dumps({"OOMKilled": False}) if args[0] == "inspect" else "")
                )
            )
        ),
    )
    res2 = runner2.run(script)
    assert res2.state == ResultState.RUNTIME_ERROR
    assert "Script exited 2" in res2.detail


def test_docker_timeout_kills_container_and_cleans_up(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    calls = []

    def fake_command(*args, **kwargs):
        calls.append(args)
        if args[0] == "info":
            return valid_docker_info()
        if args[0] == "image":
            return valid_image_inspect()
        if args[0] == "wait":
            raise ProviderError("timeout expired")
        return ""

    monkeypatch.setattr(runner, "command", fake_command)
    script = tmp_path / "loop.py"
    script.write_text("while True: pass", encoding="utf-8")

    result = runner.run(script)
    assert result.state == ResultState.TIMEOUT
    assert "Wall-clock limit exceeded" in result.detail

    # Check kill was called, then rm --force
    kill_cmd = next(c for c in calls if c[0] == "kill")
    assert kill_cmd[0] == "kill"
    rm_cmd = calls[-1]
    assert rm_cmd[0:2] == ("rm", "--force")


def test_docker_timeout_kill_failure_still_reports_timeout(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)

    def fake_command(*args, **kwargs):
        if args[0] == "info":
            return valid_docker_info()
        if args[0] == "image":
            return valid_image_inspect()
        if args[0] == "wait":
            raise ProviderError("timeout expired")
        if args[0] == "kill":
            raise SandboxError("container already dying")
        return ""

    monkeypatch.setattr(runner, "command", fake_command)
    script = tmp_path / "loop.py"
    script.write_text("while True: pass", encoding="utf-8")

    result = runner.run(script)
    # Result must still be TIMEOUT, not overwritten by SANDBOX_ERROR from the kill error
    assert result.state == ResultState.TIMEOUT


def test_docker_cleanup_failure_reports_sandbox_error(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)

    def fake_command(*args, **kwargs):
        if args[0] == "info":
            return valid_docker_info()
        if args[0] == "image":
            return valid_image_inspect()
        if args[0] == "wait":
            return "0"
        if args[0] == "inspect":
            return json.dumps({"OOMKilled": False})
        if args[0] == "rm":
            raise SandboxError("docker rm daemon error")
        return ""

    monkeypatch.setattr(runner, "command", fake_command)
    script = tmp_path / "test.py"
    script.write_text("assert True", encoding="utf-8")

    result = runner.run(script)
    assert result.state == ResultState.SANDBOX_ERROR
    assert "Cleanup failed; remove only the owned container" in result.detail
