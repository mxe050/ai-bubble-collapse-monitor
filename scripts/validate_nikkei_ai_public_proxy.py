#!/usr/bin/env python3
"""Schema and invariant audit for the public Nikkei contribution proxy."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "nikkei-ai-three-series.json"
CONFIG = ROOT / "config" / "nikkei-ai-overheat-config.json"


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def validate() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    meta, summary, quality = payload["meta"], payload["summary"], payload["quality"]
    require(config["method_version"] == "2.0", "method v2 config is missing")
    require(config["mode"] in {"public_contribution_proxy", "exact_reconstruction"}, "invalid mode")
    require(meta["title"] == "日経平均からAI過熱候補の寄与を分ける", "new title is missing")
    require(meta["calculation_frequency"] == "daily" and meta["display_frequency"] == "weekly", "frequency is wrong")
    require(meta["dividends_included"] is False and "Adj Close" in meta["price_field"], "price-field disclosure is wrong")
    require(meta["synthetic_series_are_official"] is False, "proxy cannot be official")
    require(datetime.fromisoformat(meta["generated_at"]).tzinfo is not None, "generation time needs timezone")
    require(date.fromisoformat(meta["start_date"]) <= date.fromisoformat(meta["market_date"]) <= date.fromisoformat(meta["end_date"]), "market dates are invalid")

    actual = payload["actual_series"]
    display = payload["series"]
    require(len(actual) >= 500, "10-year actual series is incomplete")
    actual_dates = [date.fromisoformat(row["date"]) for row in actual]
    require(actual_dates == sorted(actual_dates) and len(actual_dates) == len(set(actual_dates)), "actual dates are invalid")
    require(actual[0]["nikkei_actual"] == 100, "actual full-period base must be 100")
    base = num(actual[0]["nikkei_close"])
    require(base is not None and base > 0, "actual base close is invalid")
    for row in actual:
        close, index = num(row["nikkei_close"]), num(row["nikkei_actual"])
        require(close is not None and index is not None and abs(index - 100 * close / base) <= .02, "actual path changed")
    require(display and display[0]["date"] == meta["display_start_date"] and display[-1]["date"] == meta["display_end_date"], "display dates are invalid")

    candidates, selected, keeps = payload["candidates"], payload["selected_candidates"], payload["explicit_keep"]
    require(len(candidates) >= 9, "candidate universe should include existing 8 plus Kioxia")
    require(any(row["code"] == "285A" for row in candidates), "Kioxia is absent")
    require("7203" in {row["code"] for row in keeps}, "Toyota explicit_keep is absent")
    require(not {"7203"} & {row["code"] for row in selected}, "Toyota cannot be selected")
    for row in candidates:
        require(row["status"] in {"auto_screened_provisional", "manual_include", "manual_exclude", "explicit_keep", "not_selected"}, "candidate status invalid")
        require(set(row["conditions"]) == {"A", "B", "C", "D"}, "screen details missing")
    for row in selected:
        require(row["status"] in {"auto_screened_provisional", "manual_include"}, "selected candidate status invalid")

    counts = quality["day_counts"]
    require(sum(counts.values()) == quality["calculation_day_count"], "quality day counts do not reconcile")
    coverage = num(quality["coverage_pct"])
    require(coverage is not None and abs(coverage - 100 * quality["valid_proxy_day_count"] / quality["calculation_day_count"]) < .01, "coverage is invalid")
    maximum = num(quality["maximum_combined_weight_pct"])
    if maximum is not None:
        require(0 <= maximum < 100, "all target weights must remain below one")
    require(quality["data_state"] == meta["comparison_status"], "quality state diverges")
    require("採用・除外" in quality.get("membership_handling", ""), "membership handling is not disclosed")
    audit = quality.get("candidate_price_audit") or []
    require(len(audit) == len(candidates), "candidate price audit is incomplete")
    require(all(isinstance(item.get("split_events"), list) for item in audit), "split-event audit is invalid")

    status = meta["comparison_status"]
    if status == "public-contribution-proxy":
        require(selected, "proxy cannot calculate with zero targets")
        require(display[0]["nikkei_actual"] == display[0]["ai_overheat_normalized"] == display[0]["ai_overheat_excluded"] == 100, "three proxy paths need common base")
        require(all(num(row["ai_overheat_normalized"]) is not None and num(row["ai_overheat_excluded"]) is not None for row in display), "proxy values are missing in displayed segment")
    else:
        require(all(row["ai_overheat_normalized"] is None and row["ai_overheat_excluded"] is None for row in display), "actual-only state must not fake a proxy")
    if coverage < 90:
        require(summary["full_period_returns_visible"] is False, "partial data must not show 10-year proxy returns")
    require(all(str(row.get("url") or "").startswith("https://") for row in payload["sources"]), "sources must be HTTPS")
    require(not _has_non_finite(payload), "payload contains NaN or infinity")


def _has_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, list):
        return any(_has_non_finite(item) for item in value)
    if isinstance(value, dict):
        return any(_has_non_finite(item) for item in value.values())
    return False


def main() -> None:
    validate()
    print("Nikkei AI public contribution proxy validation passed")


if __name__ == "__main__":
    main()
