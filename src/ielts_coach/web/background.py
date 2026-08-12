from __future__ import annotations

import argparse
from pathlib import Path

from .server import open_ui, serve_ui


def main() -> None:
    parser = argparse.ArgumentParser(description="言蹊 (Yanxi) background launcher")
    parser.add_argument("action", choices=("serve", "open"))
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if args.action == "serve":
        serve_ui(args.home, port=args.port, open_browser=False)
    else:
        open_ui(args.home, port=args.port, open_browser=True)


if __name__ == "__main__":
    main()
