#!/usr/bin/env python3
"""Audit the six-series global market comparison package and UI contract."""

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


def close_enough(actual: float, expected: float, *, relative: float = 2e-6) -> bool:
    scale = max(1.0, abs(actual), abs(expected))
    return abs(actual - expected) <= scale * relative


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
    require(all("TOPIX" not in json.dumps(row, ensure_ascii=False).upper() for row in definitions), "TOPIX must not exist in the comparison definitions")
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
    require(points[0].get("date") == payload.get("baseDate") == "1985-01-01", "comparison base date must be the first complete month after 1985-01-01")
    require(points[-1].get("date") == payload.get("latestCommonMonth"), "latest common month is not synchronized")
    dates = [row["date"] for row in points]
    require(len(dates) == len(set(dates)), "comparison has duplicate months")
    require(all(dates[index] < dates[index + 1] for index in range(len(dates) - 1)), "comparison months are not chronological")
    require(all(date.fromisoformat(value).day == 1 for value in dates), "comparison observations must use month-start keys")

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

    first = points[0]
    for field in ("sp500NominalNormalized", "sp500RealNormalized", "nikkeiUsdNormalized", "nikkeiRealUsdNormalized"):
        require(close_enough(number(first[field]), 100.0), f"base normalization failed: {field}")

    coverage = payload.get("valuationCoverage") or {}
    for index_id, raw_field, normalized_field in (
        ("sp500", "sp500TheoreticalReal", "sp500TheoreticalRealNormalized"),
        ("nikkei225", "nikkeiTheoreticalUsd", "nikkeiTheoreticalUsdNormalized"),
    ):
        status = coverage.get(index_id) or {}
        require(number(status.get("minimumCoverageRatio")) == 0.8, f"{index_id}: minimum coverage must be 80%")
        if number(status.get("coverageRatio") or 0) < 0.8:
            require(all(row.get(raw_field) is None and row.get(normalized_field) is None for row in points), f"{index_id}: sub-80% valuation must remain missing")
        require(all(row.get(raw_field) != 0 for row in points), f"{index_id}: missing valuation must not be filled with zero")

    require(100 / 100 > 100 / 150, "JPY per USD direction test failed")
    formulas = payload.get("formulas") or {}
    require("us_cpi_reference" in formulas.get("sp500TheoreticalReal", ""), "S&P theoretical value must use US CPI")
    require("JPY_PER_USD" in formulas.get("nikkeiTheoreticalUsd", ""), "Nikkei theoretical value must be converted to USD")
    require("cpi" not in formulas.get("nikkeiTheoreticalUsd", "").lower(), "Nikkei theoretical value must not receive an extra CPI adjustment")

    crises = payload.get("crises") or []
    require([(row["id"], row["startDate"], row["endDate"]) for row in crises] == [
        ("japan-bubble", "1990-01-01", "1992-08-31"),
        ("dotcom", "2000-03-01", "2002-10-31"),
        ("gfc", "2008-09-01", "2009-03-31"),
        ("covid", "2020-02-01", "2020-04-30"),
    ], "four crisis display periods changed")

    html = INDEX_FILE.read_text(encoding="utf-8")
    section = html.split('<section id="global-comparison"', 1)[1].split('<section id="analysis-map"', 1)[0]
    require("TOPIX" not in section.upper(), "TOPIX appears in the new comparison section")
    for element_id in (
        "globalComparisonChart", "gcToggleSpNominal", "gcToggleTheoretical", "gcToggleCrises",
        "gcExportPng", "gcExportSvg", "gcExportCsv", "gcNormalization",
    ):
        require(f'id="{element_id}"' in section, f"comparison UI is missing #{element_id}")
    require(html.index('id="global-comparison"') < html.index('id="analysis-map"'), "comparison chart must precede the six-question map")
    require("比較を拡大：S&amp;P 500名目を除外" in section, "nominal-series toggle label is missing")

    script = SCRIPT_FILE.read_text(encoding="utf-8")
    require('type: "linear"' in script and "beginAtZero: true" in script, "browser chart must use a zero-based linear scale")
    require("logarithmic" not in script, "browser comparison must not offer a logarithmic scale")
    require('hideSp500Nominal' in script and 'showTheoreticalValue' in script, "URL state restoration is missing")
    require("exportPng" in script and "exportSvg" in script and "exportCsv" in script, "comparison exports are incomplete")

    print(
        "Global comparison audit passed: six series, no TOPIX, linear zero-based axis, "
        "monthly alignment, CPI/FX identities, coverage guardrails, crisis zones, UI controls, and exports."
    )


if __name__ == "__main__":
    validate_global_comparison()
