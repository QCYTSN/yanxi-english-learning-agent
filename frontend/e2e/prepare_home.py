from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from ielts_coach.config import load_yaml, write_yaml
from ielts_coach.init_home import initialise_home


def main() -> None:
    home_value = sys.argv[1] if len(sys.argv) > 1 else os.environ["IELTS_HOME"]
    home = Path(home_value).resolve()
    initialise_home(home)
    profile_path = home / "config" / "profile.yaml"
    profile = load_yaml(profile_path)
    profile["onboarding"] = {
        "status": "ready",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    profile["current"] = {
        "listening": 6.5,
        "reading": 6.5,
        "writing": 6.0,
        "speaking": 6.0,
    }
    write_yaml(profile_path, profile, force=True)
    print(home)


if __name__ == "__main__":
    main()
