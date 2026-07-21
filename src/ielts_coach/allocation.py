from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

from .config import load_profile, load_settings
from .storage import (
    days_since_last_session,
    latest_allocation,
    recent_bands,
    recent_criterion_average,
    save_allocation,
)

MODULES = ("listening", "reading", "writing", "speaking")


@dataclass
class AllocationResult:
    allocation: dict[str, float]
    recent_average: dict[str, float | None]
    reasons: list[str]
    evidence: dict[str, Any]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalise(values: dict[str, float]) -> dict[str, float]:
    total = sum(values.values())
    if total <= 0:
        raise ValueError("Allocation weights must be positive")
    result = {key: round(value / total, 4) for key, value in values.items()}
    drift = round(1.0 - sum(result.values()), 4)
    result["listening"] = round(result["listening"] + drift, 4)
    return result


def _cap_shift(candidate: dict[str, float], previous: dict[str, float], maximum: float) -> dict[str, float]:
    capped = {
        module: _clamp(candidate[module], previous[module] - maximum, previous[module] + maximum)
        for module in MODULES
    }
    # Redistribute residual iteratively while respecting caps.
    for _ in range(12):
        residual = 1.0 - sum(capped.values())
        if abs(residual) < 1e-9:
            break
        eligible = []
        for module in MODULES:
            low, high = previous[module] - maximum, previous[module] + maximum
            if residual > 0 and capped[module] < high - 1e-9:
                eligible.append(module)
            elif residual < 0 and capped[module] > low + 1e-9:
                eligible.append(module)
        if not eligible:
            break
        share = residual / len(eligible)
        for module in eligible:
            low, high = previous[module] - maximum, previous[module] + maximum
            capped[module] = _clamp(capped[module] + share, low, high)
    return _normalise(capped)


def recommend_allocation(home: Path, *, persist: bool = False) -> AllocationResult:
    profile = load_profile(home)
    settings = load_settings(home)
    target: dict[str, float] = profile["target"]
    minimum: dict[str, float] = profile.get("minimum_required", target)
    base: dict[str, float] = profile["base_allocation"]
    policy: dict[str, Any] = profile["allocation_policy"]
    window = int(settings.get("recent_session_window", 3))

    averages: dict[str, float | None] = {}
    gaps: dict[str, float] = {}
    inactivity: dict[str, int | None] = {}
    sample_sizes: dict[str, int] = {}
    for module in MODULES:
        values = recent_bands(home, module, window)
        sample_sizes[module] = len(values)
        averages[module] = mean(values) if values else profile.get("current", {}).get(module)
        current = averages[module]
        gaps[module] = max(0.0, float(target[module]) - float(current)) if current is not None else 0.25
        inactivity[module] = days_since_last_session(home, module)

    lr_share = float(policy.get("listening_reading_share", 0.70))
    lr_min = float(policy.get("minimum_listening_reading_share", 0.60))
    lr_max = float(policy.get("maximum_listening_reading_share", 0.80))
    inactivity_threshold = int(policy.get("inactivity_threshold_days", 14))
    reasons: list[str] = []

    lr_serious = max(gaps["listening"], gaps["reading"]) >= 0.75
    ws_below_min = any(
        averages[m] is not None and float(averages[m]) < float(minimum[m])
        for m in ("writing", "speaking")
    )
    lr_stable = all(
        averages[m] is not None and float(averages[m]) >= float(target[m]) - 0.25
        for m in ("listening", "reading")
    )
    if lr_serious:
        lr_share += 0.05
        reasons.append("听力或阅读与目标差距至少 0.75，听读总占比上调 5%。")
    if ws_below_min:
        lr_share -= 0.10
        reasons.append("写作或口语低于最低单项要求，向写口转移 10%。")
    elif lr_stable and (gaps["writing"] > 0.25 or gaps["speaking"] > 0.25):
        lr_share -= 0.05
        reasons.append("听读已接近目标，释放 5% 给写作或口语。")
    lr_share = _clamp(lr_share, lr_min, lr_max)

    # Weight subjects inside the two strategic groups.
    weights = {
        "listening": 1.0 + gaps["listening"],
        "reading": 1.0 + gaps["reading"],
        "writing": 1.7 + gaps["writing"],
        "speaking": 0.8 + gaps["speaking"],
    }
    for module in MODULES:
        if inactivity[module] is None or inactivity[module] >= inactivity_threshold:
            weights[module] += 0.35
            reasons.append(f"{module.title()} 长期未练或没有记录，增加维护权重。")

    # Criterion-level signals are available after structured Writing/Speaking records exist.
    writing_risk = [
        recent_criterion_average(home, "writing", criterion)
        for criterion in ("TR", "TA", "CC", "LR", "GRA")
    ]
    writing_risk = [value for value in writing_risk if value is not None]
    if writing_risk and min(writing_risk) < float(minimum["writing"]):
        weights["writing"] += 0.35
        reasons.append("写作分项评分存在低于最低要求的维度，增加写作权重。")

    l_total = weights["listening"] + weights["reading"]
    ws_total = weights["writing"] + weights["speaking"]
    candidate = {
        "listening": lr_share * weights["listening"] / l_total,
        "reading": lr_share * weights["reading"] / l_total,
        "writing": (1 - lr_share) * weights["writing"] / ws_total,
        "speaking": (1 - lr_share) * weights["speaking"] / ws_total,
    }
    candidate["speaking"] = max(candidate["speaking"], 0.08)
    candidate["writing"] = 1 - candidate["listening"] - candidate["reading"] - candidate["speaking"]
    candidate = _normalise(candidate)

    iso = date.today().isocalendar()
    period_key = f"{iso.year}-W{iso.week:02d}"
    previous = latest_allocation(home, exclude_period=period_key) or base
    maximum_shift = float(policy.get("maximum_weekly_shift", 0.10))
    allocation = _cap_shift(candidate, previous, maximum_shift)
    if allocation != candidate:
        reasons.append(f"应用每周期单科最多变化 {maximum_shift * 100:.0f}% 的稳定性限制。")

    exam_date = profile.get("exam", {}).get("test_date")
    if exam_date:
        try:
            days_left = (date.fromisoformat(str(exam_date)) - date.today()).days
            if 0 <= days_left <= 60:
                reasons.append(f"距离考试约 {days_left} 天，优先守住最低单项并使用近期真题验证。")
        except ValueError:
            pass

    if not reasons:
        reasons.append("当前证据不足或风险不突出，保持接近默认 70/30 策略。")
    evidence = {
        "recent_average": averages,
        "sample_sizes": sample_sizes,
        "target_gaps": gaps,
        "inactivity_days": inactivity,
        "previous_allocation": previous,
        "period_key": period_key,
    }
    result = AllocationResult(allocation, averages, reasons, evidence)
    if persist:
        save_allocation(home, allocation, reasons, evidence, period_key)
    return result
