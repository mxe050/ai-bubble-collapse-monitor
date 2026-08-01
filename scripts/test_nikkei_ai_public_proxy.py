#!/usr/bin/env python3
"""Network-free invariants for the public contribution proxy."""

from __future__ import annotations

import copy
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import nikkei_ai_public_proxy as proxy  # noqa: E402


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def sources() -> tuple[list[dict], list[dict], list[dict], list[dict], dict, dict]:
    start, end = date(2016, 7, 31), date(2026, 7, 31)
    actual, topix, stock, toyota, summaries = [], [], [], [], {}
    day, index = start, 0
    while day <= end:
        actual_close = 16_000 + index * 3
        topix_close = 1_000 + index * .18
        # A 3-year surge makes 6857 pass A, B, and C without making every
        # monitored AI-linked issuer automatically selected.
        stock_close = 1_000 + index * .05
        if day >= date(2023, 7, 31):
            stock_close += (day - date(2023, 7, 31)).days * 4.0
        toyota_close = stock_close
        actual.append({"date": day, "close": actual_close})
        topix.append({"date": day, "close": topix_close})
        stock.append({"date": day, "close": stock_close})
        toyota.append({"date": day, "close": toyota_close})
        summaries[day.isoformat()] = {
            "weights": {"6857": .02, "7203": .02},
            "divisor": 30.0,
        }
        day += timedelta(days=1)
        index += 1
    month_last = {}
    for row in actual:
        month_last[(row["date"].year, row["date"].month)] = row["close"]
    monthly = [{"date": date(year, month, 1), "close": close}
               for (year, month), close in sorted(month_last.items())]
    prices = {
        "6857": {"rows": stock},
        "7203": {"rows": toyota},
        "285A": {"rows": stock[-250:]},
    }
    return actual, actual, monthly, topix, prices, summaries


def payload(*, missing: bool = False, flat: bool = False, mode: str | None = None) -> dict:
    config = proxy.load_config(ROOT / "config" / "nikkei-ai-overheat-config.json")
    if mode is not None:
        config["mode"] = mode
    yahoo, official, monthly, topix, prices, summaries = sources()
    if missing:
        summaries.pop("2025-01-01")
    catalog = [
        {"code": "6857", "name": "アドバンテスト", "symbol": "6857.T", "universe_source": "test"},
        {"code": "7203", "name": "トヨタ自動車", "symbol": "7203.T", "universe_source": "test"},
        {"code": "285A", "name": "キオクシアホールディングス", "symbol": "285A.T", "universe_source": "test"},
    ]
    if flat:
        catalog = [{"code": "285A", "name": "キオクシアホールディングス", "symbol": "285A.T", "universe_source": "test"}]
    return proxy.build_payload(
        config,
        yahoo_rows=yahoo,
        official_daily=official,
        official_monthly=monthly,
        topix_rows=topix,
        candidate_prices=prices,
        official_summaries=summaries,
        candidate_catalog=catalog,
        generated_at=datetime(2026, 8, 1, 0, 0, tzinfo=proxy.JST),
    )


def test_screen_and_proxy() -> None:
    result = payload()
    selected = result["selected_candidates"]
    require([row["code"] for row in selected] == ["6857"], "only screened candidate should be selected")
    candidate = next(row for row in result["candidates"] if row["code"] == "6857")
    require(candidate["status"] == "auto_screened_provisional", "screened candidate status is wrong")
    require(candidate["passed_conditions"] == ["A", "B", "C"], "screen conditions are wrong")
    kept = next(row for row in result["candidates"] if row["code"] == "7203")
    require(kept["status"] == "explicit_keep" and not kept["selected_for_proxy"], "7203 must remain explicit_keep")
    require(result["meta"]["comparison_status"] == "public-contribution-proxy", "public proxy should calculate")
    require(result["series"][0]["nikkei_actual"] == 100, "actual proxy start must be 100")
    require(result["series"][0]["ai_overheat_normalized"] == 100, "normalized proxy start must be 100")
    require(result["series"][0]["ai_overheat_excluded"] == 100, "excluded proxy start must be 100")
    require(result["quality"]["maximum_combined_weight_pct"] < 100, "target weights must sum below one")
    require(result["quality"]["day_counts"]["exact"] > 0, "exact daily weight days are missing")
    require(len(result["quality"]["candidate_price_audit"]) == 3, "candidate price audit is missing")
    require("採用・除外" in result["quality"]["membership_handling"], "membership handling disclosure is missing")
    events = result["historical_events"]
    require(len(events) >= 8 and events[0]["date"] == "2016-11-08", "historical event timeline is missing")
    require([item["date"] for item in events] == sorted(item["date"] for item in events), "historical events must be chronological")
    require(all(item["source_url"].startswith("https://") for item in events), "historical event source must be HTTPS")
    require(result["meta"]["nominal_chart_unit"] == "JPY", "nominal chart unit is missing")
    require(proxy.json_is_finite(result), "payload contains NaN or infinity")


def test_exact_mode_requires_licensed_inputs() -> None:
    result = payload(mode="exact_reconstruction")
    require(result["meta"]["comparison_status"] == "data-insufficient-exact-reconstruction-inputs", "exact mode must not fall through to a public proxy")
    require(all(row["ai_overheat_normalized"] is None and row["ai_overheat_excluded"] is None for row in result["series"]), "exact mode without licensed inputs must show actual only")


def test_actual_only_and_missing_behavior() -> None:
    result = payload(flat=True)
    require(result["meta"]["comparison_status"] == "actual-only-no-screened-candidates", "zero candidate state is wrong")
    require(result["summary"]["normalized_return_pct"] is None, "zero candidates must not fabricate normalized returns")
    require(result["summary"]["excluded_return_pct"] is None, "zero candidates must not fabricate excluded returns")
    require(all(row["ai_overheat_normalized"] is None for row in result["series"]), "zero candidates must show actual only")
    missing = payload(missing=True)
    require(missing["quality"]["missing_date_count"] > 0, "missing input must remain missing")
    require(missing["quality"]["coverage_pct"] < 100, "missing input cannot be filled")
    require(proxy.weight({"confirmed_non_members": ["6857"], "weights": {}}, "6857")[0] == 0, "confirmed non-member should be zero")
    require(proxy.weight({"weights": {}}, "6857")[0] is None, "unlisted top-10 issuer cannot be silently zero")


def test_denominator_and_config_guards() -> None:
    actual = [{"date": date(2026, 1, 1), "close": 100}, {"date": date(2026, 1, 2), "close": 101}]
    rows = proxy.proxy_rows(
        actual,
        {date(2026, 1, 1): 100, date(2026, 1, 2): 101},
        {"6857": {date(2026, 1, 1): 100, date(2026, 1, 2): 101}},
        {date(2026, 1, 1): {"weights": {"6857": 1.0}}},
        [{"code": "6857"}],
    )
    require(not rows[0]["computed"], "rExcluded denominator <= 0 must stop")
    require("分母" in rows[0]["missing"][0], "denominator stop must be disclosed")
    # Weight/PAF changes cannot create a stock-price return by themselves:
    # the daily formula uses only the previous-day weight and close-to-close returns.
    event_rows = proxy.proxy_rows(
        actual,
        {date(2026, 1, 1): 100, date(2026, 1, 2): 101},
        {"6857": {date(2026, 1, 1): 100, date(2026, 1, 2): 101}},
        {date(2026, 1, 1): {"weights": {"6857": .25}}, date(2026, 1, 2): {"weights": {"6857": .75}}},
        [{"code": "6857"}],
    )
    require(event_rows[0]["computed"], "weight-change fixture should calculate")
    require(abs(event_rows[0]["nikkei_return"] - .01) < 1e-12, "actual return changed by a weight event")
    require(abs(event_rows[0]["normalized_return"] - .01) < 1e-12, "normalized return changed by a weight event")
    require(abs(event_rows[0]["excluded_return"] - .01) < 1e-12, "excluded return changed by a weight event")
    source = Path(proxy.__file__).read_text(encoding="utf-8").lower()
    require('quote.get("close")' in source and "adjclose" not in source, "Adj Close must not be used")
    config = proxy.load_config(ROOT / "config" / "nikkei-ai-overheat-config.json")
    invalid = copy.deepcopy(config)
    invalid["explicit_keep"] = []
    try:
        proxy.validate_config(invalid)
    except proxy.ConfigurationError:
        pass
    else:
        raise AssertionError("7203 explicit_keep guard did not fire")


def main() -> None:
    test_screen_and_proxy()
    test_exact_mode_requires_licensed_inputs()
    test_actual_only_and_missing_behavior()
    test_denominator_and_config_guards()
    print("Nikkei AI public contribution proxy tests passed")


if __name__ == "__main__":
    main()
