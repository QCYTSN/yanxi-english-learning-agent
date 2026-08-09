from __future__ import annotations

import sys
from pathlib import Path

from .agent_jobs import AgentJobManager
from .background_jobs import execute_background_job


def run_agent_job(home: Path, run_id: str) -> None:
    manager = AgentJobManager(home, workers=1, process_isolation=False)
    try:
        manager.execute_now(run_id)
    finally:
        manager.shutdown()


def main(argv: list[str] | None = None) -> int:
    values = list(argv if argv is not None else sys.argv[1:])
    if len(values) != 3 or values[0] not in {"agent-run", "background-job"}:
        raise SystemExit(
            "Usage: python -m ielts_coach.local_worker "
            "{agent-run|background-job} HOME JOB_ID"
        )
    if values[0] == "agent-run":
        run_agent_job(Path(values[1]), values[2])
    else:
        execute_background_job(Path(values[1]), values[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
