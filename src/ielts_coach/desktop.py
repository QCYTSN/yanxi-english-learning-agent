from __future__ import annotations

import argparse
import ctypes
import os
import time
from pathlib import Path

from ielts_coach.paths import resolve_home
from ielts_coach.web.server import open_ui, serve_ui, stop_ui, ui_status


def _show_error(message: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(0, message, "IELTS Study Desk", 0x10)
    else:  # pragma: no cover - Windows is the packaged desktop target
        print(message)


def main() -> None:
    """Start or reopen the local product without requiring a terminal."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-open", action="store_true")
    args, _ = parser.parse_known_args()
    if args.serve:
        serve_ui(resolve_home(args.home), port=args.port, open_browser=False)
        return
    if args.stop:
        home = resolve_home(args.home)
        stop_ui(home)
        deadline = time.monotonic() + 10
        while ui_status(home).get("running") and time.monotonic() < deadline:
            time.sleep(0.1)
        return
    try:
        open_ui(
            resolve_home(args.home),
            port=args.port,
            open_browser=not args.no_open,
        )
    except Exception as exc:  # pragma: no cover - native launcher safety net
        _show_error(
            "IELTS Study Desk could not start.\n\n"
            f"{exc}\n\n"
            "Use Settings > System after repairing the installation for diagnostics."
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
