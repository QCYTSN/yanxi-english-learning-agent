from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import load_profile, load_yaml
from .validation import validate_data


def onboarding_status(home: Path) -> dict[str, Any]:
    profile = load_profile(home)
    onboarding = profile.get("onboarding") or {}
    current = profile.get("current") or {}
    baseline_count = sum(value is not None for value in current.values())
    return {
        "status": onboarding.get("status", "pending"),
        "completed_at": onboarding.get("completed_at"),
        "baseline_status": "complete" if baseline_count == 4 else "partial" if baseline_count else "missing",
        "baseline_modules": [key for key, value in current.items() if value is not None],
    }


ONBOARDING_FIELDS = {
    "exam", "target", "minimum_required", "stretch_target", "current",
    "base_allocation", "allocation_policy", "preferences", "privacy",
}


def _merge_mapping(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = dict(current)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_mapping(result[key], value)
        else:
            result[key] = value
    return result


def complete_onboarding(home: Path, updates: dict[str, Any] | None = None) -> dict[str, Any]:
    path = home / "config" / "profile.yaml"
    raw = load_yaml(path)
    profile = load_profile(home)
    supplied = updates or {}
    unsupported = set(supplied) - ONBOARDING_FIELDS
    if unsupported:
        raise ValueError(f"Unsupported onboarding fields: {', '.join(sorted(unsupported))}")
    requested_exam = (supplied.get("exam") or {}).get("type")
    if requested_exam and requested_exam != "academic":
        raise ValueError(
            "IELTS AI Coach currently supports IELTS Academic only; "
            "General Training Reading and Writing tasks are not implemented"
        )
    profile = _merge_mapping(profile, supplied)
    profile["onboarding"] = {
        **(profile.get("onboarding") or {}),
        "status": "ready",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    profile = validate_data(profile, "profile")
    # Preserve any future user-owned top-level fields while writing the validated merge.
    raw.update(profile)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return onboarding_status(home)
