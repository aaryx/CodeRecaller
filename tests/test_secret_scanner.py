import pytest

from coderecall.domain.errors import GitError, SyncConflictError, ValidationError
from coderecall.integrations.git import SECRET, LocalGitProvider, SyncPlan


@pytest.mark.parametrize(
    "secret_sample",
    [
        "-----BEGIN " + "PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASC",
        "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0Y",
        "-----BEGIN " + "EC PRIVATE KEY-----\nMHcCAQEEI",
        "-----BEGIN " + "DSA PRIVATE KEY-----\nMIIBvAIBAAKBgQD9",
        "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAA",
        "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----\nMIIFDjBABgkqhkiG9w0BBQ0w",
        "ghp_" + "12345678901234567890abcdefghij",
        "gho_" + "12345678901234567890abcdefghij",
        "ghu_" + "12345678901234567890abcdefghij",
        "ghs_" + "12345678901234567890abcdefghij",
        "ghr_" + "12345678901234567890abcdefghij",
        "github_pat_" + "11ABCD1234_567890abcdef1234567890abcdef",
        "AKIA" + "IOSFODNN7EXAMPLE",
        "ASIA" + "IOSFODNN7EXAMPLE",
        "sk-" + "1234567890abcdef1234567890abcdef",
        "sk-ant-" + "api03-1234567890abcdef1234567890",
        "hf_" + "abcdefghijklmnopqrstuvwxyz0123456789",
        "xoxb-" + "123456789012-1234567890123-abcdef123456",
        "sk_" + "live_" + "1234567890abcdef12345678",
        "rk_" + "live_" + "1234567890abcdef12345678",
        "api_" + 'key = "abcdef1234567890"',
        "token: '" + "super_secret_token_value_here'",
        "pass" + 'word="production_password_xyz123"',
        "auth_" + 'token = "auth_token_value_here_1234"',
    ],
)
def test_secret_scanner_detects_credentials(secret_sample):
    assert SECRET.search(secret_sample) is not None


@pytest.mark.parametrize(
    "safe_sample",
    [
        "def solve(nums: list[int]) -> int: return len(nums)",
        "token_count = 5",
        "api_key = ''",
        "password = None",
        "class SecretSharingAlgorithm:",
        "def test_token_refresh(): pass",
        "public_key = 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC'",
        "user_id = 'user_12345'",
    ],
)
def test_secret_scanner_avoids_false_positives(safe_sample):
    assert SECRET.search(safe_sample) is None


def test_command_error_suppresses_credential_leak(tmp_path, monkeypatch):
    provider = LocalGitProvider(tmp_path)
    # Simulate git error with credential in stderr
    from unittest.mock import MagicMock

    fake_proc = MagicMock(
        returncode=128, stdout="", stderr="fatal: https://token:secret_token_val@github.com failed"
    )
    monkeypatch.setattr("coderecall.integrations.git.run", lambda *args, **kwargs: fake_proc)

    with pytest.raises(GitError) as caught:
        provider.command("push")
    # Verify the exception message does NOT leak the credential
    assert "secret_token_val" not in str(caught.value)
    assert "inspect with git directly. Local data preserved" in str(caught.value)


def test_remote_url_with_credentials_rejected(tmp_path, monkeypatch):
    provider = LocalGitProvider(tmp_path)
    monkeypatch.setattr(provider, "status", lambda: {"branch": "main"})
    monkeypatch.setattr(
        provider,
        "command",
        lambda *args, **kwargs: (
            "origin" if args[0] == "config" else "https://token:secret@github.com/repo.git"
        ),
    )

    with pytest.raises(GitError, match="Remove credentials from the remote URL"):
        provider.remote()


def test_git_status_absent_when_not_a_repo(tmp_path, monkeypatch):
    provider = LocalGitProvider(tmp_path)
    monkeypatch.setattr(provider, "command", lambda *args, **kwargs: "false")
    assert provider.status() == {"repository": "absent", "branch": "", "changes": ""}


def test_git_diff_empty_paths(tmp_path):
    provider = LocalGitProvider(tmp_path)
    assert provider.diff([]) == "No owned files"


def test_git_commit_validates_message(tmp_path):
    provider = LocalGitProvider(tmp_path)
    with pytest.raises(ValidationError, match="Commit message must have 1–200 characters"):
        provider.commit([], "")
    with pytest.raises(ValidationError, match="Commit message must have 1–200 characters"):
        provider.commit([], "x" * 201)


def test_git_commit_rejects_detached_head(tmp_path, monkeypatch):
    provider = LocalGitProvider(tmp_path)
    monkeypatch.setattr(provider, "available", lambda: True)
    monkeypatch.setattr(provider, "status", lambda: {"branch": "DETACHED"})
    with pytest.raises(GitError, match="Attach HEAD to a branch before committing"):
        provider.commit([], "commit message")


def test_git_remote_validates_protocols_and_names(tmp_path, monkeypatch):
    provider = LocalGitProvider(tmp_path)
    monkeypatch.setattr(provider, "status", lambda: {"branch": "main"})

    # Malicious remote names
    for bad_name in ["-remote", ".", ";rm -rf", "remote name with spaces"]:
        monkeypatch.setattr(provider, "command", (lambda b: lambda *args, **kwargs: b)(bad_name))
        with pytest.raises(GitError, match="A named remote tracking branch is required"):
            provider.remote()

    # Unsupported protocol
    monkeypatch.setattr(
        provider,
        "command",
        lambda *args, **kwargs: "origin" if args[0] == "config" else "ext::sh -c evil",
    )
    with pytest.raises(GitError, match="Unsupported Git remote protocol"):
        provider.remote()


def test_git_upstream_missing_raises(tmp_path, monkeypatch):
    provider = LocalGitProvider(tmp_path)
    monkeypatch.setattr(provider, "command", lambda *args, **kwargs: "")
    with pytest.raises(GitError, match="No upstream"):
        provider.upstream()


def test_scan_outgoing_rejects_coderecall_private_state(tmp_path, monkeypatch):
    provider = LocalGitProvider(tmp_path)
    monkeypatch.setattr(provider, "upstream", lambda: "origin/main")
    monkeypatch.setattr(
        provider,
        "command",
        lambda *args, **kwargs: (
            "commit_sha_123"
            if args[0] == "rev-list"
            else "100644 blob abc123\t.coderecall/state.json"
        ),
    )
    with pytest.raises(
        ValidationError, match="Outgoing history contains private .coderecall state"
    ):
        provider.scan_outgoing()


def test_scan_outgoing_rejects_oversized_blobs(tmp_path, monkeypatch):
    provider = LocalGitProvider(tmp_path)
    monkeypatch.setattr(provider, "upstream", lambda: "origin/main")

    def mock_command(*args, **kwargs):
        if args[0] == "rev-list":
            return "commit_sha_123"
        if args[0] == "ls-tree":
            return "100644 blob abc123\tsolution.py"
        if args[0] == "cat-file" and args[1] == "-s":
            return str(9 * 1024 * 1024)  # 9 MiB > 8 MiB limit
        return ""

    monkeypatch.setattr(provider, "command", mock_command)
    with pytest.raises(ValidationError, match="Outgoing blob exceeds secret scan limit"):
        provider.scan_outgoing()


def test_push_rejects_diverged_or_conflict_state(tmp_path, monkeypatch):
    provider = LocalGitProvider(tmp_path)
    monkeypatch.setattr(provider, "plan", lambda: SyncPlan("DIVERGED"))
    with pytest.raises(SyncConflictError, match="Fetch and reconcile remote changes"):
        provider.push()
