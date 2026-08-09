from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .validation import validate_data

DEFAULT_PROFILE: dict[str, Any] = {
    "profile_version": 4,
    "active_learning_track_id": "ielts-academic",
    "onboarding": {"status": "pending", "completed_at": None},
    "exam": {"type": "academic", "test_date": None},
    "target": {"overall": 7.0, "listening": 8.0, "reading": 8.0, "writing": 6.5, "speaking": 6.0},
    "minimum_required": {"overall": 6.5, "listening": 6.0, "reading": 6.0, "writing": 6.5, "speaking": 5.5},
    "stretch_target": {"overall": 7.5, "listening": 8.0, "reading": 8.0, "writing": 7.0, "speaking": 6.0},
    "current": {"listening": None, "reading": None, "writing": None, "speaking": None},
    "base_allocation": {"listening": 0.35, "reading": 0.35, "writing": 0.20, "speaking": 0.10},
    "allocation_policy": {
        "listening_reading_share": 0.70,
        "minimum_listening_reading_share": 0.60,
        "maximum_listening_reading_share": 0.80,
        "maximum_weekly_shift": 0.10,
        "inactivity_threshold_days": 14,
    },
    "preferences": {
        "interface_language": "zh-CN", "feedback_language": "bilingual",
        "model_answers_visible_by_default": False, "writing_target_band": 6.5,
        "speaking_target_band": 6.0,
    },
    "privacy": {"allow_private_corpus": True, "allow_cloud_upload": False, "store_raw_voice_audio": False},
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "database_filename": "ielts.db", "weekly_report_days": 7,
    "recent_session_window": 3, "question_draw_limit": 100000,
    "content_inbox_quota_bytes": 10 * 1024 * 1024 * 1024,
    "local_storage_quota_bytes": 25 * 1024 * 1024 * 1024,
}


def _merge(default: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(default)
    for key, value in current.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def write_yaml(path: Path, data: dict[str, Any], force: bool = False) -> None:
    if path.exists() and not force:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing configuration file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return data


def load_profile(home: Path) -> dict[str, Any]:
    return validate_data(_merge(DEFAULT_PROFILE, load_yaml(home / "config" / "profile.yaml")), "profile")


def load_settings(home: Path) -> dict[str, Any]:
    return _merge(DEFAULT_SETTINGS, load_yaml(home / "config" / "settings.yaml"))


def migrate_configuration(home: Path) -> None:
    """Add new defaults without replacing user-owned configuration values."""
    profile_path = home / "config" / "profile.yaml"
    settings_path = home / "config" / "settings.yaml"

    current_profile = load_yaml(profile_path)
    merged_profile = _merge(DEFAULT_PROFILE, current_profile)
    merged_profile["profile_version"] = max(
        int(current_profile.get("profile_version", 1)),
        int(DEFAULT_PROFILE["profile_version"]),
    )
    merged_profile = validate_data(merged_profile, "profile")
    if merged_profile != current_profile:
        profile_path.write_text(
            yaml.safe_dump(merged_profile, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    current_settings = load_yaml(settings_path)
    merged_settings = _merge(DEFAULT_SETTINGS, current_settings)
    if merged_settings != current_settings:
        settings_path.write_text(
            yaml.safe_dump(merged_settings, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
