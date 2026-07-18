#!/usr/bin/env python3
"""Fail the public build when core data or audited calculation contracts break."""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "latest.json"
APP_FILE = ROOT / "app.js"
INDEX_FILE = ROOT / "index.html"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def close_enough(actual: float, expected: float, *, relative: float = 1e-8) -> bool:
    scale = max(1.0, abs(actual), abs(expected))
    return abs(actual - expected) <= scale * relative


def dcf_value(fcf: float, growth_pct: float, discount_pct: float, terminal_pct: float, years: int = 10) -> float:
    growth = growth_pct / 100
    discount = discount_pct / 100
    terminal = terminal_pct / 100
    require(fcf > 0, "DCF input FCF must be positive")
    require(discount > terminal, "DCF discount rate must exceed terminal growth")
    future = fcf
    present = 0.0
    for year in range(1, years + 1):
        future *= 1 + growth
        present += future / (1 + discount) ** year
    present += future * (1 + terminal) / (discount - terminal) / (1 + discount) ** years
    return present


def check_yoy_dates(company: dict[str, Any], prefix: str) -> None:
    current = company.get(f"{prefix}CurrentDate")
    prior = company.get(f"{prefix}PriorDate")
    if current is None and prior is None:
        return
    require(bool(current and prior), f"{company['ticker']} {prefix}: one comparison date is missing")
    gap = (date.fromisoformat(current) - date.fromisoformat(prior)).days
    require(320 <= gap <= 410, f"{company['ticker']} {prefix}: comparison is not year-over-year ({gap} days)")


def main() -> None:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    require(data.get("schemaVersion") == 7, "schemaVersion must be 7")
    require(data.get("methodVersion") == "3.4.0", "methodVersion must be 3.4.0")

    generated = datetime.fromisoformat(data["generatedAtUtc"]).date()
    market_day = date.fromisoformat(data["marketDate"])
    require(0 <= (generated - market_day).days <= 10, "market date is future-dated or stale")

    series = data["market"]["series"]
    for key in ("SOX", "NASDAQ", "NIKKEI"):
        row = series.get(key)
        require(bool(row), f"missing core market series: {key}")
        require(finite(row.get("close")) and row["close"] > 0, f"invalid close: {key}")
        require(finite(row.get("drawdown3yPct")) and 0 <= row["drawdown3yPct"] <= 100, f"invalid drawdown: {key}")
        require(finite(row.get("weeksBelowSma200")) and row["weeksBelowSma200"] >= 0, f"invalid SMA duration: {key}")
        calculated_drawdown = (1 - row["close"] / row["peak3y"]) * 100
        require(close_enough(calculated_drawdown, row["drawdown3yPct"]), f"{key}: drawdown identity failed")

    companies = data.get("companies") or []
    require(len(companies) == 26, f"expected 26 companies, got {len(companies)}")
    category_counts = {
        category: sum(1 for company in companies if company.get("category") == category)
        for category in ("overseas-ai", "japan-ai", "japan-diversified")
    }
    require(category_counts == {"overseas-ai": 10, "japan-ai": 8, "japan-diversified": 8}, f"category counts changed: {category_counts}")

    tickers = set()
    for company in companies:
        ticker = company["ticker"]
        require(ticker not in tickers, f"duplicate ticker: {ticker}")
        tickers.add(ticker)
        require(finite(company.get("price")) and company["price"] > 0, f"{ticker}: invalid price")
        require(finite(company.get("marketCap")) and company["marketCap"] > 0, f"{ticker}: invalid market cap")
        require(finite(company.get("drawdown3yPct")) and 0 <= company["drawdown3yPct"] <= 100, f"{ticker}: invalid drawdown")
        price_row = series.get(ticker)
        require(bool(price_row), f"{ticker}: market series is missing")
        calculated_drawdown = (1 - company["price"] / price_row["peak3y"]) * 100
        require(close_enough(calculated_drawdown, company["drawdown3yPct"]), f"{ticker}: company drawdown identity failed")
        if finite(company.get("enterpriseValue")):
            expected_ev = company["marketCap"] + (company.get("debt") or 0) - (company.get("cash") or 0)
            require(close_enough(company["enterpriseValue"], expected_ev), f"{ticker}: EV identity failed")
        valuation_fcf = company.get("valuationFcf")
        if finite(valuation_fcf):
            expected_yield = valuation_fcf / company["marketCap"] * 100
            require(close_enough(company["valuationFcfYieldPct"], expected_yield), f"{ticker}: valuation FCF yield failed")
        assumptions = company.get("assumptions") or {}
        discount = assumptions.get("discountRatePct")
        terminal = assumptions.get("terminalGrowthPct")
        base_growth = assumptions.get("baseGrowthPct")
        years = assumptions.get("forecastYears")
        require(finite(discount) and 6 <= discount <= 16, f"{ticker}: discount assumption out of range")
        require(finite(terminal) and 0 <= terminal <= 4, f"{ticker}: terminal assumption out of range")
        require(discount > terminal, f"{ticker}: discount must exceed terminal growth")
        require(finite(base_growth) and -10 <= base_growth <= 35, f"{ticker}: base growth assumption out of range")
        require(years == 10, f"{ticker}: forecast horizon changed without audit")
        if finite(valuation_fcf) and valuation_fcf > 0:
            base_value = dcf_value(valuation_fcf, base_growth, discount, terminal, years)
            require(finite(base_value) and base_value > 0, f"{ticker}: invalid base DCF")
        require(company.get("ttmCapex") is None or company["ttmCapex"] >= 0, f"{ticker}: CapEx magnitude must be non-negative")
        check_yoy_dates(company, "revenueGrowth")
        check_yoy_dates(company, "freeCashFlowGrowth")
        check_yoy_dates(company, "capexGrowth")

    overseas = data["market"]["aiBasket"]
    japan = data["market"]["japanAiBasket"]
    require(len(overseas.get("constituents") or []) == 10, "overseas AI basket must contain 10 companies")
    require(len(japan.get("constituents") or []) == 8, "Japan transmission basket must contain 8 companies")
    require(japan.get("label", "").startswith("日本AI・半導体連動8社"), "Japan basket must be labelled as a site-specific proxy")

    derived = data["derived"]
    require(derived.get("latestQuarterRevenueGrowthCoverage", 0) >= 7, "revenue YoY coverage below 7/10")
    require(derived.get("fcfDeteriorationCoverage", 0) >= 7, "FCF deterioration coverage below 7/10")
    require(derived.get("hyperscalerCapexCoverage") == 4, "hyperscaler CapEx coverage must be 4/4")
    require(0 <= derived.get("fcfDeteriorationBreadthPct", -1) <= 100, "invalid FCF deterioration breadth")

    by_ticker = {company["ticker"]: company for company in companies}
    require(by_ticker["7203.T"].get("valuationFcf") == 2_492_282_000_000, "Toyota audited valuation FCF changed")
    require(by_ticker["7267.T"].get("valuationFcf") == 685_867_000_000, "Honda audited valuation FCF changed")
    require("非金融" in by_ticker["7203.T"].get("valuationFcfBasis", ""), "Toyota non-financial basis missing")
    require("非金融" in by_ticker["7267.T"].get("valuationFcfBasis", ""), "Honda non-financial basis missing")
    require(by_ticker["9984.T"].get("valuationFcf", 0) <= 0, "SoftBank should not silently receive a positive common DCF input")

    toyota = by_ticker["7203.T"]
    toyota_base = dcf_value(
        toyota["valuationFcf"], toyota["assumptions"]["baseGrowthPct"],
        toyota["assumptions"]["discountRatePct"], toyota["assumptions"]["terminalGrowthPct"],
    )
    toyota_ratio = toyota_base / toyota["marketCap"]
    require(0.80 <= toyota_ratio <= 1.10, f"Toyota base DCF ratio is implausibly far from audited range: {toyota_ratio:.3f}")

    honda = by_ticker["7267.T"]
    honda_base = dcf_value(
        honda["valuationFcf"], honda["assumptions"]["baseGrowthPct"],
        honda["assumptions"]["discountRatePct"], honda["assumptions"]["terminalGrowthPct"],
    )
    honda_ratio = honda_base / honda["marketCap"]
    require(honda_ratio >= 1.0, f"Honda audited FCF no longer supports the current market cap: {honda_ratio:.3f}")

    reference = data["market"]["nikkeiValuationReference"]
    require(reference.get("date") == "2026-07-17", "Nikkei reference date changed without audit")
    require(reference.get("price") == 64141.12, "Nikkei reference close changed without audit")
    require(reference.get("indexPe") == 22.99 and reference.get("indexPb") == 2.71, "Nikkei official PE/PB changed without audit")

    episodes = data["market"].get("historicalEpisodes") or []
    require(len(episodes) == 6, "historical episode count must be 6")
    for episode in episodes:
        require(episode["troughDate"] >= episode["peakDate"], f"{episode['id']}: trough precedes peak")
        calculated = (1 - episode["trough"] / episode["peak"]) * 100
        require(abs(calculated - episode["drawdownPct"]) < 1e-8, f"{episode['id']}: drawdown identity failed")

    require("highYieldOas" in data.get("macro", {}), "FRED high-yield OAS is missing")

    app_source = APP_FILE.read_text(encoding="utf-8")
    index_source = INDEX_FILE.read_text(encoding="utf-8")
    referenced_ids = set(re.findall(r'byId\("([^"]+)"\)', app_source))
    html_id_list = re.findall(r'\bid="([^"]+)"', index_source)
    html_ids = set(html_id_list)
    require(len(html_id_list) == len(html_ids), "index.html contains duplicate element ids")
    missing_ids = sorted(referenced_ids - html_ids)
    require(not missing_ids, f"app.js references missing HTML ids: {missing_ids}")
    require("Method v3.4" in index_source, "public method label is missing")
    require("評価への脆弱性は別枠20点" in index_source, "valuation/collapse score separation is missing")

    print(
        "Data and logic audit passed: schema, formulas, coverage, YoY dates, baskets, "
        "automaker DCF overrides, Nikkei reference, history, and UI contracts."
    )


if __name__ == "__main__":
    main()
