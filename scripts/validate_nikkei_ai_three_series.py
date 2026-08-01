#!/usr/bin/env python3
"""Schema and invariant audit for the Nikkei AI-overheat comparison package."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "nikkei-ai-three-series.json"
CONFIG_FILE = ROOT / "config" / "nikkei-ai-overheat-stocks.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def close_enough(left: float, right: float, tolerance: float = 1e-4) -> bool:
    return abs(left - right) <= tolerance


def validate_nikkei_ai_three_series() -> None:
    require(DATA_FILE.exists(), "Nikkei AI three-series package is missing")
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    meta = payload.get("meta") or {}
    summary = payload.get("summary") or {}
    quality = payload.get("quality") or {}
    series = payload.get("series") or []

    for key in (
        "title", "generated_at", "market_date", "start_date", "end_date",
        "base_value", "calculation_frequency", "display_frequency",
        "dividends_included", "price_field", "normalization_method",
        "normalization_buffer", "exclusion_mode", "synthetic_series_are_official",
    ):
        require(key in meta, f"meta.{key} is missing")
    generated = datetime.fromisoformat(meta["generated_at"])
    require(generated.tzinfo is not None, "generated_at must be timezone-aware")
    market_date = date.fromisoformat(meta["market_date"])
    start_date = date.fromisoformat(meta["start_date"])
    end_date = date.fromisoformat(meta["end_date"])
    require(start_date <= market_date == end_date <= generated.date(), "market dates are inconsistent")
    require((generated.date() - market_date).days <= 10, "market date is stale relative to generation time")
    require(meta["base_value"] == 100, "base value must remain 100")
    require(meta["calculation_frequency"] == "daily", "calculation must use daily Close")
    require(meta["display_frequency"] == "weekly", "display must be weekly")
    require(meta["dividends_included"] is False, "price index cannot include dividends")
    require("Adj Close" in meta["price_field"], "raw Close disclosure is missing")
    require(meta["synthetic_series_are_official"] is False, "synthetic series cannot claim official status")

    require(isinstance(series, list) and len(series) >= 500, "ten-year weekly series is incomplete")
    dates = [date.fromisoformat(row["date"]) for row in series]
    require(dates == sorted(dates), "series dates are not ascending")
    require(len(dates) == len(set(dates)), "series dates are duplicated")
    require(dates[0] == start_date, "base-date observation is missing from the graph")
    require(dates[-1] == market_date, "series extends beyond its official market date")

    first = series[0]
    require(close_enough(finite(first["nikkei_actual"]) or float("nan"), 100.0), "first actual observation must be 100")
    base_close = finite(first.get("nikkei_close"))
    require(base_close is not None and base_close > 0, "base Close is invalid")
    for row in series:
        actual = finite(row.get("nikkei_actual"))
        close = finite(row.get("nikkei_close"))
        require(actual is not None and close is not None and close > 0, "actual Close row is invalid")
        expected = 100.0 * close / base_close
        require(close_enough(actual, expected, tolerance=0.01), "actual series is not normalized Close")
        for key in (
            "ai_overheat_normalized", "ai_overheat_excluded",
            "actual_minus_normalized", "normalized_minus_excluded",
        ):
            value = row.get(key)
            require(value is None or finite(value) is not None, f"{key} contains a non-finite value")

    targets = payload.get("bubble_suspect") or []
    keeps = payload.get("explicit_keep") or []
    target_codes = {str(row.get("code")) for row in targets if isinstance(row, dict)}
    keep_codes = {str(row.get("code")) for row in keeps if isinstance(row, dict)}
    require("7203" in keep_codes, "Toyota 7203 must be explicit_keep")
    require(not (target_codes & keep_codes), "a code cannot be both kept and excluded")
    require(summary.get("bubble_suspect_count") == len(targets), "target count is inconsistent")

    if not targets:
        require(summary.get("ai_excess_contribution_percentage_points") == 0.0, "empty targets must have zero excess contribution")
        require(summary.get("retained_normal_contribution_percentage_points") == 0.0, "empty targets must have zero retained contribution")
        require(summary.get("normalized_return_pct") == summary.get("actual_return_pct"), "empty targets changed normalized return")
        require(summary.get("excluded_return_pct") == summary.get("actual_return_pct"), "empty targets changed excluded return")
        for row in series:
            require(row["nikkei_actual"] == row["ai_overheat_normalized"] == row["ai_overheat_excluded"], "empty target paths must be identical")
            require(row["actual_minus_normalized"] == row["normalized_minus_excluded"] == 0.0, "empty target gaps must be zero")
        require(any(str(item).startswith("AI") for item in payload.get("warnings") or []), "safe empty-target warning is missing")

    monthly = quality.get("monthly_crosscheck") or {}
    require(monthly.get("matched_months", 0) >= 100, "monthly cross-check is incomplete")
    require(monthly.get("missing_months") == [], "monthly cross-check has missing months")
    require(monthly.get("within_0_02_jpy") is True, "monthly cross-check exceeds tolerance")
    require(finite(monthly.get("max_abs_error_jpy")) is not None, "monthly error is missing")
    require((quality.get("data_state") or "").startswith("actual-only") or targets, "empty config data state is wrong")

    sources = payload.get("sources") or []
    require(len(sources) >= 3, "source catalog is incomplete")
    require(all(str(row.get("url") or "").startswith("https://") for row in sources), "source URL must be HTTPS")
    require(config.get("bubble_suspect") == targets, "published target configuration differs from payload")


def main() -> None:
    validate_nikkei_ai_three_series()
    print("Nikkei AI three-series validation passed")


if __name__ == "__main__":
    main()
