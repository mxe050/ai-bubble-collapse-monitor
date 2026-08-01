#!/usr/bin/env python3
"""Network-free tests for the Nikkei AI-overheat three-series generator."""

from __future__ import annotations

import copy
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nikkei_ai_three_series as module  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def expect_configuration_error(payload: dict, message: str) -> None:
    try:
        module.validate_config(payload)
    except module.ConfigurationError:
        return
    raise AssertionError(message)


def synthetic_sources() -> tuple[list[dict], list[dict], list[dict]]:
    """Make >10 years of aligned Close-only data without network requests."""

    start = date(2016, 7, 31)
    end = date(2026, 7, 31)
    rows: list[dict] = []
    observed = start
    index = 0
    while observed <= end:
        # A deterministic, positive Close path.  Calendar days are sufficient
        # for unit tests because the generator only needs chronological dates.
        close = 16_000.0 + index * 4.25
        rows.append({"date": observed, "close": close})
        observed += timedelta(days=1)
        index += 1

    month_end: dict[tuple[int, int], dict] = {}
    for row in rows:
        month_end[(row["date"].year, row["date"].month)] = row
    monthly = [
        {
            "date": date(year, month, 1),
            "close": row["close"],
        }
        for (year, month), row in sorted(month_end.items())
    ]
    return list(rows), list(rows), monthly


def test_empty_targets_are_explicitly_uncomputed() -> None:
    config = module.load_config(ROOT / "config" / "nikkei-ai-overheat-stocks.json")
    yahoo, official_daily, official_monthly = synthetic_sources()
    payload = module.build_payload(
        config,
        yahoo_rows=yahoo,
        official_daily=official_daily,
        official_monthly=official_monthly,
        generated_at=datetime(2026, 8, 1, 0, 0, tzinfo=module.JST),
    )

    require(payload["summary"]["bubble_suspect_count"] == 0, "empty config must retain zero targets")
    require(payload["meta"]["comparison_status"] == "actual-only-comparison-uncomputed-no-targets", "empty config must be explicitly uncomputed")
    require(payload["summary"]["normalized_return_pct"] is None, "empty config must not create a normalized return")
    require(payload["summary"]["excluded_return_pct"] is None, "empty config must not create an excluded return")
    require(payload["summary"]["ai_excess_contribution_percentage_points"] is None, "empty config must not claim zero excess contribution")
    require(payload["summary"]["retained_normal_contribution_percentage_points"] is None, "empty config must not claim zero retained contribution")
    require(payload["meta"]["market_date"] == payload["meta"]["end_date"], "series cannot extend beyond the official end date")
    require(payload["quality"]["monthly_crosscheck"]["matched_months"] >= 100, "monthly cross-check must cover ten years")
    require(payload["quality"]["monthly_crosscheck"]["missing_months"] == [], "monthly cross-check cannot skip months")
    require(payload["quality"]["monthly_crosscheck"]["within_0_02_jpy"], "monthly cross-check tolerance failed")
    require(payload["series"][0]["nikkei_actual"] == 100.0, "first actual point must be 100")
    for row in payload["series"]:
        require(row["ai_overheat_normalized"] is None, "empty targets must keep normalized path uncomputed")
        require(row["ai_overheat_excluded"] is None, "empty targets must keep excluded path uncomputed")
        require(row["actual_minus_normalized"] is None, "empty targets must not claim a zero gap")
        require(row["normalized_minus_excluded"] is None, "empty targets must not claim a zero exclusion gap")
    require(
        any(text.startswith("AI") for text in payload["warnings"]),
        "safe empty-target warning is missing",
    )


def test_future_yahoo_rows_are_excluded() -> None:
    config = module.load_config(ROOT / "config" / "nikkei-ai-overheat-stocks.json")
    yahoo, official_daily, official_monthly = synthetic_sources()
    yahoo.append({"date": date(2026, 8, 3), "close": 99_999.0})
    payload = module.build_payload(
        config,
        yahoo_rows=yahoo,
        official_daily=official_daily,
        official_monthly=official_monthly,
        generated_at=datetime(2026, 8, 1, 0, 0, tzinfo=module.JST),
    )
    require(payload["meta"]["market_date"] == "2026-07-31", "official market date changed unexpectedly")
    require(payload["meta"]["end_date"] == "2026-07-31", "future Yahoo bar leaked into the series")
    require(payload["series"][-1]["nikkei_close"] != 99_999.0, "future Yahoo close leaked into the series")


def test_config_and_numeric_guards() -> None:
    baseline = module.load_config(ROOT / "config" / "nikkei-ai-overheat-stocks.json")
    overlap = copy.deepcopy(baseline)
    overlap["bubble_suspect"] = [{"code": "7203", "name": "??", "reason": "test"}]
    expect_configuration_error(overlap, "keep/bubble overlap must fail")

    wrong_lookback = copy.deepcopy(baseline)
    wrong_lookback["lookback_years"] = 10.5
    expect_configuration_error(wrong_lookback, "fractional lookback must fail")

    bool_buffer = copy.deepcopy(baseline)
    bool_buffer["normalization_buffer"] = True
    expect_configuration_error(bool_buffer, "boolean buffer must fail")

    missing_keep = copy.deepcopy(baseline)
    missing_keep["explicit_keep"] = []
    expect_configuration_error(missing_keep, "Toyota 7203 must stay explicitly kept")
    missing_reason = copy.deepcopy(baseline)
    missing_reason["bubble_suspect"] = [{"code": "9998", "name": "Target"}]
    expect_configuration_error(missing_reason, "exclusion target must have a reason")


    invalid_date = copy.deepcopy(baseline)
    invalid_date["bubble_suspect"] = [{"code": "9999", "name": "Target", "reason": "test", "effective_from": "2026-15-99"}]
    expect_configuration_error(invalid_date, "invalid effective date must fail")

    require(module.normalize_price(120.0, 100.0) == 100.0, "normalization must remove only excess")
    require(module.normalize_price(80.0, 100.0) == 80.0, "normalization must never raise a price")
    require(module.parse_number("64,362.02") == 64362.02, "number parser lost Nikkei close")
    require(not module.json_is_finite({"bad": float("nan")}), "NaN must be rejected")


def test_configured_target_fails_closed() -> None:
    config = module.load_config(ROOT / "config" / "nikkei-ai-overheat-stocks.json")
    config = copy.deepcopy(config)
    config["bubble_suspect"] = [{
        "code": "9999",
        "name": "TargetWithReason",
        "reason": "network-free fail-closed test",
        "effective_from": "2020-01-01",
    }]
    config = module.validate_config(config)
    yahoo, official_daily, official_monthly = synthetic_sources()
    payload = module.build_payload(
        config,
        yahoo_rows=yahoo,
        official_daily=official_daily,
        official_monthly=official_monthly,
        generated_at=datetime(2026, 8, 1, 0, 0, tzinfo=module.JST),
    )
    require(payload["summary"]["bubble_suspect_count"] == 1, "configured target count is wrong")
    require(payload["meta"]["comparison_status"] == "comparison-uncomputed-missing-historical-inputs", "configured target must disclose missing historical inputs")
    require(payload["summary"]["normalized_return_pct"] is None, "missing inputs must not create synthetic return")
    require(payload["summary"]["excluded_return_pct"] is None, "missing inputs must not create excluded return")
    require(all(row["ai_overheat_normalized"] is None for row in payload["series"]), "normalized line must fail closed")
    require(all(row["ai_overheat_excluded"] is None for row in payload["series"]), "excluded line must fail closed")


def main() -> None:
    test_empty_targets_are_explicitly_uncomputed()
    test_future_yahoo_rows_are_excluded()
    test_config_and_numeric_guards()
    test_configured_target_fails_closed()
    print("Nikkei AI three-series unit tests passed")


if __name__ == "__main__":
    main()
