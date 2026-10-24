"""Reproducible local snapshot benchmark; reports actual timings, no network."""

import argparse
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

from coderecall.application.project import Project
from coderecall.domain.models import Activity, Problem, Review, Schedule, Solution
from coderecall.storage.local import LocalStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=int, default=0, help="Reviews per problem")
    parser.add_argument("--sizes", type=int, nargs="+", default=[10, 100, 1000, 10000])
    args = parser.parse_args()
    if not 0 <= args.history <= 10:
        parser.error("history must be 0–10")
    results = []
    for size in args.sizes:
        with tempfile.TemporaryDirectory(prefix="coderecall-benchmark-") as directory:
            root = Path(directory)
            store = LocalStore(root)
            store.initialize()
            now = datetime.now(UTC)
            start = perf_counter()
            with store.transaction() as state:
                for i in range(size):
                    pid = f"cr_{i:032x}"
                    state.problems[pid] = Problem(
                        pid,
                        "custom",
                        str(i),
                        f"problem-{i}",
                        f"Problem {i}",
                        "",
                        "easy",
                        ["array"],
                        [],
                        [],
                        now.isoformat(),
                    )
                    state.schedules[pid] = Schedule(pid, (now + timedelta(days=1)).isoformat())
                    if args.history:
                        path = root / f"python/problem-{i}/solution.py"
                        path.parent.mkdir(parents=True)
                        path.write_text("def solve():\n    return 42\n", encoding="utf-8")
                        state.problems[pid].solutions.append(
                            Solution(
                                f"s_{i}",
                                "python",
                                path.relative_to(root).as_posix(),
                                "Synthetic benchmark",
                                "O(1)",
                                "O(1)",
                                now.isoformat(),
                                now.isoformat(),
                                "benchmark",
                            )
                        )
                        for j in range(args.history):
                            at = (now - timedelta(days=j + 1)).isoformat()
                            state.reviews.append(
                                Review(f"r_{i}_{j}", pid, at, at, 0, j % 3 != 0, 300, 1, 0, 4)
                            )
                            state.activities.append(Activity("review", pid, at, 300))
            write = perf_counter() - start
            start = perf_counter()
            store.read()
            read = perf_counter() - start
            start = perf_counter()
            Project(root).list_problems(query="Problem 9")
            search = perf_counter() - start
            start = perf_counter()
            Project(root).stats()
            stats = perf_counter() - start
            results.append(
                {
                    "problems": size,
                    "reviews": size * args.history,
                    "bytes": store.path("state.json").stat().st_size,
                    "write_seconds": round(write, 4),
                    "read_seconds": round(read, 4),
                    "search_seconds": round(search, 4),
                    "stats_seconds": round(stats, 4),
                }
            )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
