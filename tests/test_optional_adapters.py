import io
import json
import os
import urllib.error
from unittest.mock import MagicMock

import pytest

from coderecall.domain.errors import AuthenticationError, ProviderError
from coderecall.execution.docker import DockerRunner
from coderecall.integrations.openai import OpenAIProvider


def response(monkeypatch, body):
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: opener)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-credential")
    return opener


def test_openai_fixed_endpoint_separate_data_no_tools(monkeypatch):
    opener = response(
        monkeypatch, {"choices": [{"finish_reason": "stop", "message": {"content": "Explanation"}}]}
    )
    assert (
        OpenAIProvider("test-model").generate("system instruction", "untrusted source")
        == "Explanation"
    )
    request = opener.open.call_args.args[0]
    data = json.loads(request.data)
    assert request.full_url == "https://api.openai.com/v1/chat/completions"
    assert data["store"] is False and "tools" not in data
    assert data["messages"][1] == {"role": "user", "content": "untrusted source"}


@pytest.mark.parametrize(
    "status,exception,calls",
    [
        (401, AuthenticationError, 1),
        (403, AuthenticationError, 1),
        (429, ProviderError, 1),
        (500, ProviderError, 3),
    ],
)
def test_openai_failures_bounded_redacted(monkeypatch, status, exception, calls):
    opener = response(monkeypatch, {})
    opener.open.side_effect = urllib.error.HTTPError("url", status, "private credential", {}, None)
    monkeypatch.setattr("coderecall.integrations.openai.time.sleep", lambda _: None)
    with pytest.raises(exception) as caught:
        OpenAIProvider("test").generate("instruction", "source")
    assert "private credential" not in str(caught.value)
    assert opener.open.call_count == calls


def test_openai_incomplete_or_tool_response_rejected(monkeypatch):
    response(
        monkeypatch,
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {"content": "delete", "tool_calls": [{}]},
                }
            ]
        },
    )
    with pytest.raises(ProviderError):
        OpenAIProvider("test").generate("instruction", "source")


@pytest.mark.parametrize(
    "exit_code,oom,timeout,expected",
    [
        (0, False, False, "PASS"),
        (1, False, False, "FAIL"),
        (137, True, False, "MEMORY_LIMIT"),
        (0, False, True, "TIMEOUT"),
    ],
)
def test_docker_constraints_and_cleanup(tmp_path, monkeypatch, exit_code, oom, timeout, expected):
    source = tmp_path / "test.py"
    source.write_text("assert 1 + 1 == 2", encoding="utf-8")
    runner = DockerRunner(tmp_path, "python:test")
    calls = []

    def command(*args, **kwargs):
        calls.append(args)
        if args[0] == "info":
            return json.dumps(
                {
                    "OSType": "linux",
                    "SecurityOptions": ["name=seccomp,profile=builtin"],
                    "MemoryLimit": True,
                    "PidsLimit": True,
                    "CpuCfsQuota": True,
                }
            )
        if args[0] == "image":
            return json.dumps([{"Id": "sha256:trusted", "Os": "linux", "Config": {}}])
        if args[0] == "wait":
            if timeout:
                raise ProviderError("timeout")
            return str(exit_code)
        if args[0] == "inspect":
            return json.dumps({"OOMKilled": oom})
        return ""

    monkeypatch.setattr(runner, "command", command)
    assert runner.run(source).state == expected
    create = next(c for c in calls if c[0] == "create")
    for flag in [
        "--read-only",
        "--cap-drop",
        "--security-opt",
        "--memory",
        "--memory-swap",
        "--pids-limit",
        "--user",
    ]:
        assert flag in create
    assert create[create.index("--network") + 1] == "none"
    assert create[create.index("--pull") + 1] == "never"
    assert "--volume" not in create and "--mount" not in create
    assert calls[-1][0:2] == ("rm", "--force")


def test_docker_unavailable_never_executes_source(tmp_path, monkeypatch):
    source = tmp_path / "evil.py"
    source.write_text("raise RuntimeError('do not execute')", encoding="utf-8")
    runner = DockerRunner(tmp_path, "python:test")

    def unavailable(*args, **kwargs):
        raise ProviderError("not installed")

    monkeypatch.setattr(runner, "command", unavailable)
    assert runner.run(source).state == "UNAVAILABLE"


@pytest.mark.skipif(
    os.environ.get("CODERECALL_TEST_DOCKER") != "1",
    reason="Explicit opt-in to live Docker tests required",
)
def test_real_docker_isolation(tmp_path):
    source = tmp_path / "isolation.py"
    source.write_text(
        "import os, socket\nassert os.getuid() == 65534\nassert not os.path.exists('/var/run/docker.sock')\nassert not os.path.exists('/host')\ntry:\n open('/escape','w')\nexcept OSError:\n pass\nelse:\n raise AssertionError('root writable')\ntry:\n socket.create_connection(('1.1.1.1',443),timeout=1)\nexcept OSError:\n pass\nelse:\n raise AssertionError('network enabled')\n",
        encoding="utf-8",
    )
    assert DockerRunner(tmp_path, "python:3.12-alpine").run(source).state == "PASS"
