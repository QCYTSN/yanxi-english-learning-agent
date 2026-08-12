from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import os
import tempfile

import yaml
from filelock import FileLock

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
    "active_learning_track_id", "exam", "target", "minimum_required", "stretch_target", "current",
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


def update_profile(
    home: Path,
    updates: dict[str, Any] | None = None,
    *,
    mark_ready: bool = False,
) -> dict[str, Any]:
    path = home / "config" / "profile.yaml"
    supplied = updates or {}
    unsupported = set(supplied) - ONBOARDING_FIELDS
    if unsupported:
        raise ValueError(f"Unsupported onboarding fields: {', '.join(sorted(unsupported))}")
    requested_exam = (supplied.get("exam") or {}).get("type")
    if requested_exam not in (None, "academic", "none"):
        raise ValueError(
            "Unsupported exam type; choose 'academic' for IELTS preparation "
            "or 'none' for the General English track"
        )
    requested_track = supplied.get("active_learning_track_id")
    if requested_track:
        from .domain_packs import get_domain_pack

        pack = get_domain_pack(str(requested_track))
        if pack.status != "active":
            raise ValueError(f"Learning track is not active: {pack.track_id}")
    lock_path = home / "runtime" / "locks" / "profile.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(lock_path), timeout=30):
        raw = load_yaml(path)
        profile = _merge_mapping(load_profile(home), supplied)
        # Target and minimum scores are editable in the UI while the stretch
        # target remains an internal planning ceiling. Keep hidden planning
        # bounds coherent instead of rejecting a valid visible form.
        if isinstance(supplied.get("target"), dict):
            target_scores = profile.get("target") or {}
            minimum_scores = profile.get("minimum_required") or {}
            stretch_scores = profile.get("stretch_target") or {}
            for key, value in target_scores.items():
                if key in minimum_scores and float(minimum_scores[key]) > float(value):
                    minimum_scores[key] = value
                if key in stretch_scores and float(stretch_scores[key]) < float(value):
                    stretch_scores[key] = value
            profile["minimum_required"] = minimum_scores
            profile["stretch_target"] = stretch_scores
        if mark_ready:
            profile["onboarding"] = {
                **(profile.get("onboarding") or {}),
                "status": "ready",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        profile = validate_data(profile, "profile")
        raw.update(profile)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".profile-",
            suffix=".yaml",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            yaml.safe_dump(raw, handle, allow_unicode=True, sort_keys=False)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return {
        "onboarding": onboarding_status(home),
        "profile": load_profile(home),
    }


def complete_onboarding(home: Path, updates: dict[str, Any] | None = None) -> dict[str, Any]:
    result = update_profile(home, updates, mark_ready=True)
    return result["onboarding"]
