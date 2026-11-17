"""Launch-day Twitch audience forecaster (gta6-twitch-ccu-forecast-01).

Idea: a launch day's hourly viewer curve, measured as log-ratios to the day's
first hour, has a repeatable shape for comparable game launches — a quiet
post-unlock start in UTC, a step up when North America unlocks, a mid-day
plateau and a long evening climb into US prime time. Each case file carries
dozens of past launches with their full hourly curves, so this program builds
the forecast from them at run time:

  1. Every comparable launch contributes its release-day curve of
     log(viewers[h] / viewers[hour 1]) for h = 2..24.
  2. Each comparable is weighted by how much it resembles this launch:
     curated tier (clean comparable vs early-access-contaminated vs weak),
     unlock pattern (rolling midnight-local vs one simultaneous global time),
     whether it launched on PC as well as console, and how close its own
     first-hour audience is in scale to this case's first-hour print.
  3. The five forecast quantiles of an hour are the weighted quantiles of the
     comparables' log-ratios at that hour, with the spread around the median
     slightly tightened (calibrated on the kit's practice launches), applied
     on top of this case's hour-1 print.

If a case carried no usable comparables the program falls back to holding
hour 1's level with a slowly widening lognormal band, so it always writes a
valid forecast. Pure standard library, no randomness: two runs on the same
case produce the same bytes.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# Weight of a comparable by the tier its unlock note assigns it. Early-access
# launches had their audience spread over earlier days, so their release-day
# shape is a weaker guide; "weak" analogues (free-to-play, slow-burn) likewise.
TIER_WEIGHT = {"clean": 1.0, "early-access": 0.3, "weak": 0.4}
# Every launch this contest asks about (the practice four and GTA VI) unlocks
# at rolling midnight local time on console only, so comparables that did the
# same count for more than simultaneous-global or PC-including launches.
ROLLING_WEIGHT = 1.9
SIMULTANEOUS_WEIGHT = 0.45
PC_WEIGHT = 0.78
CONSOLE_ONLY_WEIGHT = 1.5
# Gaussian kernel bandwidth, in log units, for first-hour scale similarity,
# floored so a much bigger launch still hears the structurally similar
# smaller ones (a mega-launch's own scale peers are mostly PC launches with
# front-loaded days, unlike a rolling console launch).
SCALE_BANDWIDTH = 1.0
SCALE_FLOOR = 0.1
# The raw cross-launch dispersion is a touch wider than the scored hours need;
# the band around the median is scaled by this factor.
SPREAD_SCALE = 0.85

# Standard-normal quantiles, used only by the no-comparables fallback.
Z_LEVEL = {0.05: -1.645, 0.25: -0.674, 0.5: 0.0, 0.75: 0.674, 0.95: 1.645}


def parse_ts(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def release_day(comp):
    """A comparable's release-day viewers by hour index 0..23 (UTC)."""
    start = parse_ts(comp["day_start"])
    by_hour = {}
    for point in comp["hourly"]:
        when = parse_ts(point["from"])
        if start <= when < start + timedelta(hours=24):
            viewers = point.get("viewers")
            if viewers:
                by_hour[(when - start).seconds // 3600] = float(viewers)
    return by_hour


def tier_of(comp):
    note = comp.get("unlock", "")
    if "target-history" in note:
        return None  # the target category's own pre-release history, no launch
    if "early-access" in note:
        return "early-access"
    if "Tier: weak" in note:
        return "weak"
    return "clean"


def pattern_weight(comp):
    note = comp.get("unlock", "").lower()
    rolling = "midnight local" in note or "rolling" in note
    simultaneous = "simultaneous" in note or "single global" in note or "one global" in note
    if rolling and not simultaneous:
        return ROLLING_WEIGHT
    if simultaneous and not rolling:
        return SIMULTANEOUS_WEIGHT
    return 1.0


def platform_weight(comp):
    parts = [p.strip().upper() for p in comp.get("platforms", "").replace("/", ",").split(",")]
    return PC_WEIGHT if any(p.startswith("PC") for p in parts) else CONSOLE_ONLY_WEIGHT


def comparable_curves(case, first_hour):
    """(log-ratio curve {hour index 1..23: value}, weight) per usable comparable."""
    curves = []
    for comp in case.get("comparables", []):
        tier = tier_of(comp)
        if tier is None:
            continue
        day = release_day(comp)
        if len(day) < 20 or day.get(0, 0.0) <= 0:
            continue
        weight = TIER_WEIGHT[tier] * pattern_weight(comp) * platform_weight(comp)
        scale_gap = abs(math.log(day[0] / first_hour))
        kernel = math.exp(-0.5 * (scale_gap / SCALE_BANDWIDTH) ** 2)
        weight *= SCALE_FLOOR + (1.0 - SCALE_FLOOR) * kernel
        if weight <= 1e-9:
            continue
        curve = {h: math.log(day[h] / day[0]) for h in range(1, 24) if day.get(h, 0.0) > 0}
        if curve:
            curves.append((curve, weight))
    return curves


def weighted_quantile(sorted_pairs, tau):
    """Interpolated weighted quantile of (value, weight) pairs sorted by value."""
    total = sum(w for _, w in sorted_pairs)
    if total <= 0:
        return sorted_pairs[len(sorted_pairs) // 2][0]
    cumulative = 0.0
    for i, (value, weight) in enumerate(sorted_pairs):
        cumulative += weight
        if cumulative / total >= tau:
            if i == 0:
                return value
            prev_value = sorted_pairs[i - 1][0]
            share = (tau * total - (cumulative - weight)) / weight if weight > 0 else 0.0
            return prev_value + share * (value - prev_value)
    return sorted_pairs[-1][0]


def first_hour_print(case):
    """Hour 1's print: the known row, else the last history hour, else 1."""
    for row in case.get("known", []):
        if row.get("hour") == 1 and row.get("viewers"):
            return max(1.0, float(row["viewers"]))
    history = case.get("history_hourly") or []
    if history and history[-1].get("viewers"):
        return max(1.0, float(history[-1]["viewers"]))
    return 1.0


def forecast_case(case):
    p1 = first_hour_print(case)
    levels = [float(t) for t in case["levels"]]
    curves = comparable_curves(case, p1)
    rows = []
    for want in case["forecast"]:
        hour = want["hour"]
        idx = hour - 1  # curve index of this hour relative to hour 1
        if curves:
            pairs = sorted((curve[idx], w) for curve, w in curves if idx in curve)
            if pairs:
                raw = [weighted_quantile(pairs, t) for t in levels]
                median = raw[levels.index(0.5)] if 0.5 in levels else raw[len(raw) // 2]
                ratios = [median + (q - median) * SPREAD_SCALE for q in raw]
            else:
                ratios = None
        else:
            ratios = None
        if ratios is None:
            # Fallback: hold hour 1's level, band widening with the hour.
            ratios = [Z_LEVEL.get(t, 0.0) * 0.22 * math.sqrt(idx) for t in levels]
        quantiles = sorted(min(1e9, max(1e-6, p1 * math.exp(r))) for r in ratios)
        rows.append({"hour": hour, "q": [round(q, 2) for q in quantiles]})
    rows.sort(key=lambda r: r["hour"])
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        result = forecast_case(case)
        payload = json.dumps(result, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / f"{path.stem}.out").write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
