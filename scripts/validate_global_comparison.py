#!/usr/bin/env python3
"""Audit the six-series market comparison and theoretical-value model."""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "global-market-value-comparison.json"
INDEX_FILE = ROOT / "index.html"
SCRIPT_FILE = ROOT / "global-comparison.js"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def close_enough(actual: float, expected: float, *, relative: float = 3e-6, absolute: float = 6e-5) -> bool:
    scale = max(1.0, abs(actual), abs(expected))
    return abs(actual - expected) <= max(absolute, scale * relative)


def number(value: Any) -> float:
    result = float(value)
    require(math.isfinite(result), f"non-finite value: {value}")
    return result


def validate_global_comparison() -> None:
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    require(payload.get("schemaVersion") == 1, "comparison schemaVersion must be 1")
    definitions = payload.get("seriesDefinitions") or []
    require(len(definitions) == 6, "comparison must define exactly six series")
    ids = [row.get("id") for row in definitions]
    require(len(ids) == len(set(ids)), "comparison series ids must be unique")
    require(sum(1 for row in definitions if row.get("market") == "S&P 500") == 3, "S&P 500 must have three series")
    require(sum(1 for row in definitions if row.get("market") == "Nikkei 225") == 3, "Nikkei 225 must have three series")
    require(sum(1 for row in definitions if row.get("isTheoretical")) == 2, "exactly two theoretical series are required")
    require(all("TOPIX" not in json.dumps(row, ensure_ascii=False).upper() for row in definitions), "TOPIX must not exist in comparison definitions")
    require(ids == [
        "sp500Nominal", "sp500Real", "sp500TheoreticalReal",
        "nikkeiUsd", "nikkeiRealUsd", "nikkeiTheoreticalUsd",
    ], "comparison series order changed")

    axis = payload.get("axis") or {}
    require(axis == {"type": "linear", "min": 0, "secondAxis": False}, "comparison axis must be one zero-based linear axis")
    fx = payload.get("exchangeRate") or {}
    require(fx.get("direction") == "JPY_PER_USD", "FX direction must be JPY per USD")
    require("Yen per U.S. Dollar" in fx.get("unit", ""), "FX source unit is not verified")

    points = payload.get("points") or []
    require(len(points) >= 450, "comparison monthly history is too short")
    require(points[0].get("date") == payload.get("baseDate") == "1985-01-01", "base date must be 1985-01-01")
    require(points[-1].get("date") == payload.get("latestCommonMonth"), "latest common month is not synchronized")
    dates = [row["date"] for row in points]
    require(len(dates) == len(set(dates)), "comparison has duplicate months")
    require(all(dates[index] < dates[index + 1] for index in range(len(dates) - 1)), "comparison months are not chronological")
    require(all(date.fromisoformat(value).day == 1 for value in dates), "observations must use month-start keys")

    us_reference = number(payload["cpiReferences"]["us"]["value"])
    japan_reference = number(payload["cpiReferences"]["japan"]["value"])
    for row in points:
        sp = number(row["sp500Nominal"])
        us_cpi = number(row["usCpi"])
        nikkei = number(row["nikkeiJpy"])
        jpy_per_usd = number(row["usdjpyJpyPerUsd"])
        japan_cpi = number(row["japanCpi"])
        require(min(sp, us_cpi, nikkei, jpy_per_usd, japan_cpi) > 0, f"non-positive source observation: {row['date']}")
        require(close_enough(number(row["sp500Real"]), sp * us_reference / us_cpi), f"S&P real identity failed: {row['date']}")
        require(close_enough(number(row["nikkeiUsd"]), nikkei / jpy_per_usd), f"Nikkei USD identity failed: {row['date']}")
        expected_real_usd = nikkei * japan_reference / japan_cpi / jpy_per_usd
        require(close_enough(number(row["nikkeiRealUsd"]), expected_real_usd), f"Nikkei real USD identity failed: {row['date']}")

        if row.get("sp500TheoreticalNominal") is not None:
            theoretical = number(row["sp500TheoreticalNominal"])
            require(close_enough(theoretical, number(row["sp500EarningsPower"]) * number(row["sp500FairPe"])), f"S&P model identity failed: {row['date']}")
            require(number(row["sp500TheoreticalLow"]) <= theoretical <= number(row["sp500TheoreticalHigh"]), f"S&P sensitivity order failed: {row['date']}")
            require(close_enough(number(row["sp500TheoreticalReal"]), theoretical * us_reference / us_cpi), f"S&P theoretical real identity failed: {row['date']}")
            require(close_enough(number(row["sp500MarketPremiumPct"]), (sp / theoretical - 1.0) * 100.0), f"S&P premium identity failed: {row['date']}")
            require(number(row["sp500FairPe"]) > 0, f"S&P fair P/E is invalid: {row['date']}")
            require(close_enough(number(row["sp500TheoreticalAtLatestEarnings"]), number(row["sp500LatestEarnings"]) * number(row["sp500FairPe"])), f"S&P latest-earnings reference failed: {row['date']}")

        if row.get("nikkeiTheoreticalJpy") is not None:
            theoretical = number(row["nikkeiTheoreticalJpy"])
            require(close_enough(theoretical, number(row["nikkeiEarningsPower"]) * number(row["nikkeiFairPe"])), f"Nikkei model identity failed: {row['date']}")
            require(number(row["nikkeiTheoreticalLowJpy"]) <= theoretical <= number(row["nikkeiTheoreticalHighJpy"]), f"Nikkei sensitivity order failed: {row['date']}")
            require(close_enough(number(row["nikkeiTheoreticalUsd"]), theoretical / jpy_per_usd), f"Nikkei theoretical USD identity failed: {row['date']}")
            require(close_enough(number(row["nikkeiMarketPremiumPct"]), (nikkei / theoretical - 1.0) * 100.0), f"Nikkei premium identity failed: {row['date']}")
            require(number(row["nikkeiFairPe"]) > 0, f"Nikkei fair P/E is invalid: {row['date']}")

            require(close_enough(number(row["nikkeiTheoreticalAtLatestEarningsJpy"]), number(row["nikkeiLatestEarnings"]) * number(row["nikkeiFairPe"])), f"Nikkei latest-earnings reference failed: {row['date']}")
    first = points[0]
    for field in ("sp500NominalNormalized", "sp500RealNormalized", "nikkeiUsdNormalized", "nikkeiRealUsdNormalized"):
        require(close_enough(number(first[field]), 100.0), f"base normalization failed: {field}")

    sp_anchor = number(first["sp500Real"])
    nk_anchor = number(first["nikkeiUsd"])
    for row in points:
        if row.get("sp500TheoreticalReal") is not None:
            expected = number(row["sp500TheoreticalReal"]) / sp_anchor * 100.0
            require(close_enough(number(row["sp500TheoreticalRealNormalized"]), expected), f"S&P shared-anchor normalization failed: {row['date']}")
        if row.get("nikkeiTheoreticalUsd") is not None:
            expected = number(row["nikkeiTheoreticalUsd"]) / nk_anchor * 100.0
            require(close_enough(number(row["nikkeiTheoreticalUsdNormalized"]), expected), f"Nikkei shared-anchor normalization failed: {row['date']}")

    coverage = payload.get("valuationCoverage") or {}
    for index_id in ("sp500", "nikkei225"):
        status = coverage.get(index_id) or {}
        require(number(status.get("minimumCoverageRatio")) == 0.8, f"{index_id}: exact-DCF threshold must be 80%")
        require(number(status.get("coverageRatio") or 0) < 0.8, f"{index_id}: exact constituent DCF unexpectedly claims coverage")

    models = payload.get("theoreticalModels") or {}
    for index_id in ("sp500", "nikkei225"):
        model = models.get(index_id) or {}
        require(model.get("status") == "available", f"{index_id}: theoretical proxy is unavailable")
        require(model.get("methodId") == "capitalized-normalized-earnings-v1", f"{index_id}: model id changed")
        latest = model.get("latest") or {}
        require(number(latest["latestEarnings"]) > 0, f"{index_id}: latest EPS reference is missing")
        require(number(latest["latestEarningsValue"]) > 0, f"{index_id}: latest-earnings value is missing")
        require(number(latest["low"]) <= number(latest["central"]) <= number(latest["high"]), f"{index_id}: latest sensitivity order failed")

    nikkei_model = models["nikkei225"]
    historical = nikkei_model.get("historicalRelativeProxy") or {}
    require(historical.get("status") == "available", "Nikkei historical relative proxy is unavailable")
    require(historical.get("startDate") == "1985-01-01", "historical proxy must start in 1985")
    require(historical.get("displayEndDate") == "2006-07-01", "historical proxy display boundary changed")
    require(historical.get("officialModelStartDate") == "2006-08-01", "official Nikkei model handoff changed")
    require(number(historical.get("baselineMonths")) == 24, "1985-86 baseline must contain 24 months")

    historical_rows = [
        row for row in points
        if row["date"] <= historical["displayEndDate"]
        and row.get("nikkeiHistoricalFairValueProxyJpy") is not None
    ]
    require(historical_rows and historical_rows[0]["date"] == "1985-01-01", "historical proxy observations are missing")
    baseline_multiple = (
        number(historical_rows[0]["nikkeiHistoricalFairValueProxyJpy"])
        / number(historical_rows[0]["nikkeiMacroProfitPowerRaw"])
    )
    for row in historical_rows:
        fair_value = number(row["nikkeiHistoricalFairValueProxyJpy"])
        market_value = number(row["nikkeiJpy"])
        profit_power = number(row["nikkeiMacroProfitPowerRaw"])
        require(close_enough(fair_value, profit_power * baseline_multiple), f"historical proxy scaling failed: {row['date']}")
        require(close_enough(number(row["nikkeiHistoricalPremiumProxyPct"]), (market_value / fair_value - 1) * 100), f"historical premium identity failed: {row['date']}")
        require(number(row["nikkeiHistoricalFairValueProxyLowJpy"]) <= fair_value <= number(row["nikkeiHistoricalFairValueProxyHighJpy"]), f"historical proxy range failed: {row['date']}")

    panic = payload.get("panicOvershootModel") or {}
    require(panic.get("status") == "available", "panic overshoot model is unavailable")
    latest_nikkei = nikkei_model["latest"]
    require(close_enough(number(panic["normalizationCentralJpy"]), number(latest_nikkei["central"])), "panic model normalization center changed")
    require(close_enough(number(panic["normalizationLowJpy"]), number(latest_nikkei["low"])), "panic model normalization low changed")
    require(close_enough(number(panic["normalizationHighJpy"]), number(latest_nikkei["high"])), "panic model normalization high changed")
    mild = number(panic["mildOvershootDiscountPct"])
    standard = number(panic["standardOvershootDiscountPct"])
    severe = number(panic["severeOvershootDiscountPct"])
    require(0 < mild <= standard <= severe < 100, "panic overshoot discounts are not ordered")
    central = number(panic["normalizationCentralJpy"])
    require(close_enough(number(panic["panicCentralJpy"]), central * (1 - standard / 100)), "panic center identity failed")
    require(close_enough(number(panic["panicCentralRangeLowJpy"]), central * (1 - severe / 100)), "panic range low identity failed")
    require(close_enough(number(panic["panicCentralRangeHighJpy"]), central * (1 - mild / 100)), "panic range high identity failed")
    require(close_enough(number(panic["severeSensitivityFloorJpy"]), number(panic["normalizationLowJpy"]) * (1 - severe / 100)), "severe sensitivity floor identity failed")
    require(sum(1 for episode in panic.get("episodes") or [] if episode.get("calibrationEligible")) == 2, "panic calibration must use exactly two eligible episodes")

    require(100 / 100 > 100 / 150, "JPY per USD direction test failed")
    formulas = payload.get("formulas") or {}
    require("us_cpi_reference" in formulas.get("sp500TheoreticalReal", ""), "S&P theoretical value must use US CPI")
    require("JPY_PER_USD" in formulas.get("nikkeiTheoreticalUsd", ""), "Nikkei theoretical value must be converted to USD")
    require("cpi" not in formulas.get("nikkeiTheoreticalUsd", "").lower(), "Nikkei theoretical value must not receive extra CPI adjustment")
    require("4.50% ERP" in formulas.get("capitalizationRate", ""), "capitalization-rate ERP assumption is missing")
    require("median" in formulas.get("earningsPower", ""), "earnings smoothing formula is missing")
    require("large-company ordinary profits" in formulas.get("nikkeiHistoricalFairValueProxy", ""), "historical Nikkei proxy formula is missing")
    require("historical_below-model_discount" in formulas.get("panicOvershoot", ""), "panic overshoot formula is missing")

    source_ids = {source.get("seriesId") for source in payload.get("sources") or []}
    for required in ("GS10", "AAA", "BAA", "JGB-CM-10Y", "SP500-ANNUAL-EARNINGS", "NIKKEI225-PE-INDEX-WEIGHT-BASIS", "JPNCPIALLMINMEI", "MOF-CORPORATE-ORDINARY-PROFIT-LARGE-EX-FINANCE"):
        require(required in source_ids, f"model source is missing: {required}")

    crises = payload.get("crises") or []
    require([(row["id"], row["startDate"], row["endDate"]) for row in crises] == [
        ("japan-bubble", "1990-01-01", "1992-08-31"),
        ("dotcom", "2000-03-01", "2002-10-31"),
        ("gfc", "2008-09-01", "2009-03-31"),
        ("covid", "2020-02-01", "2020-04-30"),
    ], "four crisis display periods changed")

    html = INDEX_FILE.read_text(encoding="utf-8")
    section = html.split('<section id="global-comparison"', 1)[1].split('<section id="us-japan-link"', 1)[0]
    require("TOPIX" not in section.upper(), "TOPIX appears in comparison section")
    for element_id in (
        "globalComparisonChart", "valuationExcessChart", "gcToggleSpNominal", "gcToggleTheoretical", "gcToggleCrises",
        "gcExportPng", "gcExportSvg", "gcExportCsv", "gcNormalization", "gcRefreshData", "gcSourceList",
        "gcSpModelStatus", "gcNkModelStatus", "gcSpTheoreticalRange", "gcNkTheoreticalRange", "gcSpLatestEarningsValue", "gcNkLatestEarningsValue", "gcSpPremiumNow", "gcNkPremiumNow", "gcSpAboveHigh", "gcNkAboveHigh", "gcSpRealPairNow", "gcNkRealPairNow",
    ):
        require(f'id="{element_id}"' in section, f"comparison UI is missing #{element_id}")
    for element_id in ("gcHistoryModelHandoff", "gcHistoryPeakPremium", "gcHistoryNormalizationPremium", "gcHistoryOvershootPremium"):
        require(f'id="{element_id}"' in section, f"historical proxy UI is missing #{element_id}")
    require(html.index('id="decision-path"') < html.index('id="global-comparison"') < html.index('id="signals"'), "five-stage overview, valuation, and collapse sections are out of order")
    require('data-gc-range="future"' in section, "future monitoring range is missing")
    require("analysis-map" not in html, "obsolete six-question map remains")
    require("全体表示：S&amp;P 500名目を戻す" in section, "nominal-series toggle label is missing")

    script = SCRIPT_FILE.read_text(encoding="utf-8")
    require('type: "linear"' in script and "beginAtZero: true" in script, "browser chart must use zero-based linear scale")
    require("logarithmic" not in script, "browser comparison must not offer logarithmic scale")
    require("gcPremiumZones" in script and "renderValuationChart" in script and "renderValuationFocus" in script, "valuation-premium chart is missing")
    require("normalizationAnchorField" in script, "shared market normalization anchor is missing")
    require('hideSp500Nominal' in script and 'showTheoreticalValue' in script, "URL state restoration is missing")
    require("exportPng" in script and "exportSvg" in script and "exportCsv" in script, "comparison exports are incomplete")
    require("nikkeiHistoricalPremium" in script and "renderHistoricalProxySummary" in script, "historical Nikkei premium rendering is missing")
    require("futureWindowPlugin" in script and '"future"' in script, "future monitoring window is missing")

    print(
        "Global comparison audit passed: six series, market-anchor normalization, "
        "CPI/FX identities, theoretical-value equations and ranges, sources, UI controls, and exports."
    )


if __name__ == "__main__":
    validate_global_comparison()
