"""Stable errors shared by application and adapters."""


class CodeRecallError(Exception):
    exit_code = 1


class ConfigurationError(CodeRecallError):
    exit_code = 3


class AuthenticationError(CodeRecallError):
    exit_code = 4


class SyncConflictError(CodeRecallError):
    exit_code = 5


class ProviderError(CodeRecallError):
    exit_code = 6


class ValidationError(CodeRecallError):
    exit_code = 7


class SandboxError(CodeRecallError):
    exit_code = 8


class StateCorruptionError(CodeRecallError):
    exit_code = 9


class StateLockedError(CodeRecallError):
    exit_code = 10


class GitError(CodeRecallError):
    exit_code = 11


class ImportError_(CodeRecallError):
    """Import-specific errors (avoid shadowing builtin ImportError)."""

    exit_code = 12


class SchedulerError(CodeRecallError):
    exit_code = 13


class ExportError(CodeRecallError):
    exit_code = 14


class PluginError(CodeRecallError):
    exit_code = 15
