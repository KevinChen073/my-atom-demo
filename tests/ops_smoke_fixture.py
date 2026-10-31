"""Create synthetic operations records in an isolated SQLite file for UI smoke checks.

Usage: python tests/ops_smoke_fixture.py data/ops-smoke.sqlite3
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Provide an isolated SQLite output path")
    # The script is run from the repository root. Keep fixture data out of source.
    from backend.store import Store

    path = Path(sys.argv[1]).resolve()
    if path.exists():
        raise SystemExit("Fixture path already exists; choose a fresh path")
    store = Store(path)
    for number, source, code in (
        (1, "agent", "model_output_invalid"),
        (2, "build", "build_failed"),
    ):
        project = store.create_project(f"fixture-owner-{number}", f"联调项目 {number}")
        run, _ = store.create_run(project["id"], "联调专用的合成任务", f"fixture-{number}")
        store.update_run(run["id"], status="failed", phase="NeedsUser",
                         event_type="failed", event_payload={"private_fixture": "not-for-ops"})
        store.record_exception(trace_id=run["trace_id"], project_id=project["id"],
                               run_id=run["id"], source=source, phase="Clarify" if number == 1 else "BuildTest",
                               code=code, exception_type="ModelOutputError" if number == 1 else "BuildFailure")
    print(f"Created 2 synthetic exception records in {path}")


if __name__ == "__main__":
    main()
