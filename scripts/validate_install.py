"""Build first; validate wheel installation in an isolated temporary environment."""

import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path


def main() -> None:
    wheels = sorted((Path(__file__).resolve().parents[1] / "dist").glob("coderecall-*.whl"))
    from coderecall import __version__

    wheels = [
        wheel for wheel in wheels if wheel.name == f"coderecall-{__version__}-py3-none-any.whl"
    ]
    if len(wheels) != 1:
        raise SystemExit("Build the current-version wheel with python -m build first")
    with tempfile.TemporaryDirectory(prefix="coderecall-install-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        bindir = environment / ("Scripts" if os.name == "nt" else "bin")
        python = bindir / ("python.exe" if os.name == "nt" else "python")
        executable = bindir / ("coderecall.exe" if os.name == "nt" else "coderecall")
        subprocess.run(
            [str(python), "-m", "pip", "install", str(wheels[0])], check=True, timeout=180
        )
        project = root / "practice"
        project.mkdir()
        source = root / "sample.py"
        source.write_text("def solve():\n    return 42\n", encoding="utf-8")

        launcher_blocked = False

        def invoke(*args: str) -> dict[str, object]:
            nonlocal launcher_blocked
            command = [str(python), "-m", "coderecall"] if launcher_blocked else [str(executable)]
            try:
                result = subprocess.run(
                    [*command, "--json", "--non-interactive", *args],
                    cwd=project,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except OSError as exc:
                if getattr(exc, "winerror", None) != 4551:
                    raise
                launcher_blocked = True
                result = subprocess.run(
                    [str(python), "-m", "coderecall", "--json", "--non-interactive", *args],
                    cwd=project,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            return json.loads(result.stdout)

        version = invoke("version")
        invoke("init")
        added = invoke("add", "--title", "Install Acceptance", "--file", str(source), "--no-commit")
        attempt = invoke("revise", str(added["problem_id"]))
        (project / str(attempt["workspace"])).write_text(
            "def solve():\n    return 42\n", encoding="utf-8"
        )
        invoke(
            "recall",
            "submit",
            str(attempt["recall_id"]),
            "--result",
            "pass",
            "--confidence",
            "4",
            "--seconds",
            "60",
        )
        stats = invoke("stats")
        if stats["reviews_completed"] != 1:
            raise SystemExit("Installed workflow failed")
        saved = invoke("backup")
        invoke("restore", str(saved["backup"]), "--yes")
        invoke("export")
        subprocess.run([str(python), "-m", "coderecall", "--version"], cwd=root, check=True)
        print(
            json.dumps(
                {
                    "clean_install": "module workflow passed" if launcher_blocked else "passed",
                    "console_launcher": "blocked by Windows application control (4551)"
                    if launcher_blocked
                    else "passed",
                    "version": version,
                    "workflow": "init/add/recall/stats/backup/restore/export",
                }
            )
        )


if __name__ == "__main__":
    main()
