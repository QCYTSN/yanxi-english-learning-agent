from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_BUDGETS = {
    "largest_javascript_bytes": 450 * 1024,
    "total_javascript_bytes": 2 * 1024 * 1024,
    "total_stylesheet_bytes": 400 * 1024,
}


def build_report(dist: Path) -> dict[str, object]:
    assets = dist / "assets"
    javascript = sorted(assets.glob("*.js")) if assets.is_dir() else []
    stylesheets = sorted(assets.glob("*.css")) if assets.is_dir() else []
    if not javascript:
        raise ValueError(f"No production JavaScript assets found under {assets}")
    measured = {
        "largest_javascript_bytes": max(path.stat().st_size for path in javascript),
        "total_javascript_bytes": sum(path.stat().st_size for path in javascript),
        "total_stylesheet_bytes": sum(path.stat().st_size for path in stylesheets),
    }
    checks = {
        name: {
            "measured_bytes": measured[name],
            "budget_bytes": budget,
            "passed": measured[name] <= budget,
        }
        for name, budget in DEFAULT_BUDGETS.items()
    }
    return {
        "dist": str(dist.resolve()),
        "asset_counts": {
            "javascript": len(javascript),
            "stylesheets": len(stylesheets),
        },
        "checks": checks,
        "passed": all(item["passed"] for item in checks.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dist",
        type=Path,
        default=Path("src/ielts_coach/web/static"),
    )
    args = parser.parse_args()
    report = build_report(args.dist)
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit("Frontend production assets exceeded the release budget")


if __name__ == "__main__":
    main()
