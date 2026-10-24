import json
import os
import tomllib
from pathlib import Path

from coderecall.domain.errors import ConfigurationError
from coderecall.storage.paths import atomic_write, safe_path

DEFAULTS: dict[str, dict[str, str | bool | int]] = {
    "repository": {"layout": "{language}/{external_id}-{slug}/{solution_id}", "editor": ""},
    "git": {
        "auto_commit": True,
        "auto_push": False,
        "strategy": "every-solution",
        "scan_secrets": True,
    },
    "revision": {
        "enabled": True,
        "scheduler": "fsrs",
        "daily_new": 2,
        "target_retention": 90,
    },
    "streak": {"activities": "solution,review,study"},
    "execution": {"enabled": False, "image": "python:3.12-alpine", "timeout": 5},
    "ai": {"enabled": False, "plugin": "", "model": "gpt-4.1-mini"},
    "analytics": {
        "track_time_of_day": True,
        "achievements_enabled": True,
    },
}


def parse_config(raw: bytes) -> dict[str, dict[str, str | bool | int]]:
    try:
        data = tomllib.loads(raw.decode("utf-8"))
        for section, values in data.items():
            if section not in DEFAULTS or not isinstance(values, dict):
                raise ValueError("Unknown configuration section")
            for key, value in values.items():
                if key not in DEFAULTS[section] or type(value) is not type(DEFAULTS[section][key]):
                    raise ValueError(f"Invalid config key/type: {section}.{key}")
        return data
    except (ValueError, UnicodeError) as exc:
        raise ConfigurationError(f"Invalid TOML configuration: {exc}") from exc


def render_config(data: dict[str, dict[str, str | bool | int]]) -> bytes:
    return (
        "\n\n".join(
            f"[{section}]\n"
            + "\n".join(
                f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in values.items()
            )
            for section, values in data.items()
        )
        + "\n"
    ).encode()


class Config:
    def __init__(self, root: Path, overrides: dict[str, str | bool | int] | None = None):
        self.values = {section: values.copy() for section, values in DEFAULTS.items()}
        user = (
            Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
            / "coderecall/config.toml"
        )
        for path in [user, safe_path(root, ".coderecall/config.toml")]:
            if path.exists():
                for section, values in parse_config(path.read_bytes()).items():
                    self.values[section].update(values)
        for section, values in self.values.items():
            for key, default in values.items():
                env = os.environ.get(f"CODERECALL_{section}_{key}".upper())
                if env is not None:
                    values[key] = self.coerce(default, env)
        for key, value in (overrides or {}).items():
            section, name = key.split(".", 1)
            self.values[section][name] = value
        if self.get("git.strategy") not in {
            "every-solution",
            "daily",
            "manual",
            "solution-and-review",
        }:
            raise ConfigurationError("Invalid git.strategy")
        if not 0 <= int(self.get("revision.daily_new")) <= 100:
            raise ConfigurationError("revision.daily_new must be 0–100")
        if not 1 <= int(self.get("execution.timeout")) <= 60:
            raise ConfigurationError("execution.timeout must be 1–60 seconds")
        if not set(str(self.get("streak.activities")).split(",")) <= {
            "solution",
            "review",
            "study",
        }:
            raise ConfigurationError("Streak activities may only contain solution,review,study")
        if not 70 <= int(self.get("revision.target_retention")) <= 99:
            raise ConfigurationError("revision.target_retention must be 70–99")

    @staticmethod
    def coerce(default: str | bool | int, value: str) -> str | bool | int:
        if isinstance(default, bool):
            if value.lower() not in {"true", "false"}:
                raise ConfigurationError("Boolean config values must be true or false")
            return value.lower() == "true"
        if isinstance(default, int):
            try:
                return int(value)
            except ValueError as exc:
                raise ConfigurationError("Expected integer config value") from exc
        return value

    def get(self, key: str) -> str | bool | int:
        try:
            section, name = key.split(".", 1)
            return self.values[section][name]
        except (ValueError, KeyError) as exc:
            raise ConfigurationError("Unknown configuration key") from exc

    @staticmethod
    def set(root: Path, key: str, value: str) -> None:
        try:
            section, name = key.split(".", 1)
            default = DEFAULTS[section][name]
        except (ValueError, KeyError) as exc:
            raise ConfigurationError(
                "Unknown configuration key; credentials are never accepted"
            ) from exc
        path = safe_path(root, ".coderecall/config.toml")
        data = parse_config(path.read_bytes())
        data.setdefault(section, {})[name] = Config.coerce(default, value)
        Config(root, {key: data[section][name]})
        atomic_write(path, render_config(data))
