#!/usr/bin/env python3
"""Build the public data package for the AI bubble monitor.

The script intentionally runs outside the browser. Market-data providers and the SEC
either restrict CORS or require identifying headers, so a scheduled GitHub Action is a
more reliable and auditable place to collect the inputs than visitors' browsers.
"""

from __future__ import annotations

import csv
import io
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "latest.json"
USER_AGENT = "mxe050-ai-bubble-monitor/1.0 (https://github.com/mxe050)"
JST = timezone(timedelta(hours=9))
NOW = datetime.now(timezone.utc)


COMPANIES: dict[str, dict[str, Any]] = {
    "NVDA": {
        "name": "NVIDIA",
        "group": "AI accelerator",
        "ir": "https://investor.nvidia.com/financial-info/quarterly-results/default.aspx",
        "discount": 0.105,
        "terminal": 0.030,
        "growth": {"bear": 0.08, "base": 0.14, "bull": 0.20},
    },
    "AVGO": {
        "name": "Broadcom",
        "group": "AI networking / ASIC",
        "ir": "https://investors.broadcom.com/financial-information/quarterly-results",
        "discount": 0.095,
        "terminal": 0.030,
        "growth": {"bear": 0.06, "base": 0.11, "bull": 0.16},
    },
    "AMD": {
        "name": "AMD",
        "group": "AI accelerator / CPU",
        "ir": "https://ir.amd.com/financial-information/quarterly-results",
        "discount": 0.105,
        "terminal": 0.030,
        "growth": {"bear": 0.05, "base": 0.11, "bull": 0.18},
    },
    "MU": {
        "name": "Micron",
        "group": "Memory / HBM",
        "ir": "https://investors.micron.com/quarterly-results",
        "discount": 0.110,
        "terminal": 0.025,
        "growth": {"bear": 0.00, "base": 0.07, "bull": 0.13},
    },
    "ARM": {
        "name": "Arm Holdings",
        "group": "CPU architecture",
        "ir": "https://investors.arm.com/financials/quarterly-results",
        "discount": 0.110,
        "terminal": 0.030,
        "growth": {"bear": 0.08, "base": 0.16, "bull": 0.24},
    },
    "MRVL": {
        "name": "Marvell Technology",
        "group": "AI networking / custom silicon",
        "ir": "https://investor.marvell.com/quarterly-results",
        "discount": 0.110,
        "terminal": 0.030,
        "growth": {"bear": 0.04, "base": 0.10, "bull": 0.16},
    },
    "MSFT": {
        "name": "Microsoft",
        "group": "Hyperscaler / software",
        "ir": "https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q3/press-release-webcast",
        "discount": 0.085,
        "terminal": 0.030,
        "growth": {"bear": 0.05, "base": 0.09, "bull": 0.13},
    },
    "GOOGL": {
        "name": "Alphabet",
        "group": "Hyperscaler / advertising",
        "ir": "https://abc.xyz/investor/",
        "discount": 0.090,
        "terminal": 0.030,
        "growth": {"bear": 0.04, "base": 0.08, "bull": 0.12},
    },
    "AMZN": {
        "name": "Amazon",
        "group": "Hyperscaler / commerce",
        "ir": "https://ir.aboutamazon.com/quarterly-results/default.aspx",
        "discount": 0.095,
        "terminal": 0.030,
        "growth": {"bear": 0.05, "base": 0.10, "bull": 0.15},
    },
    "META": {
        "name": "Meta Platforms",
        "group": "Hyperscaler / advertising",
        "ir": "https://investor.atmeta.com/investor-events/",
        "discount": 0.090,
        "terminal": 0.030,
        "growth": {"bear": 0.03, "base": 0.08, "bull": 0.12},
    },
}

PRICE_SYMBOLS = {"SOX": "^SOX", "NASDAQ": "^IXIC", **{k: k for k in COMPANIES}}
HYPERSCALERS = {"MSFT", "GOOGL", "AMZN", "META"}

FUNDAMENTAL_TYPES = [
    "trailingTotalRevenue",
    "trailingOperatingIncome",
    "trailingFreeCashFlow",
    "trailingCapitalExpenditure",
    "trailingMarketCap",
    "trailingPeRatio",
    "quarterlyCashCashEquivalentsAndShortTermInvestments",
    "quarterlyCashAndCashEquivalents",
    "quarterlyTotalDebt",
    "quarterlyDilutedAverageShares",
]


@dataclass
class SourceStatus:
    name: str
    url: str
    ok: bool
    retrieved_at: str
    note: str = ""


def request(url: str, *, timeout: int = 35, attempts: int = 3) -> bytes:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/csv,text/plain,*/*",
    }
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Unable to retrieve {url}: {last_error}")


def get_json(url: str) -> dict[str, Any]:
    return json.loads(request(url).decode("utf-8"))


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old in (None, 0):
        return None
    return (new / old - 1.0) * 100.0


def median(values: Iterable[float | None]) -> float | None:
    usable = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return statistics.median(usable) if usable else None


def moving_average(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < window:
        return out
    total = sum(values[:window])
    out[window - 1] = total / window
    for index in range(window, len(values)):
        total += values[index] - values[index - window]
        out[index] = total / window
    return out


def fetch_price_series(symbol: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=5y&interval=1d&events=div%2Csplits"
    payload = get_json(url)
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    quote = result["indicators"]["quote"][0]
    closes = quote.get("close", [])
    points: list[dict[str, Any]] = []
    for timestamp, close in zip(timestamps, closes):
        value = finite(close)
        if value is None:
            continue
        date = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
        points.append({"date": date, "close": value})
    if len(points) < 210:
        raise RuntimeError(f"Insufficient price history for {symbol}")

    values = [row["close"] for row in points]
    sma200 = moving_average(values, 200)
    last = values[-1]
    three_year = points[-756:] if len(points) >= 756 else points
    peak_row = max(three_year, key=lambda row: row["close"])
    below_days = 0
    for value, average in reversed(list(zip(values, sma200))):
        if average is not None and value < average:
            below_days += 1
        else:
            break
    latest_sma = sma200[-1]
    return {
        "symbol": symbol,
        "date": points[-1]["date"],
        "close": last,
        "change1dPct": pct_change(last, values[-2]) if len(values) > 1 else None,
        "change5dPct": pct_change(last, values[-6]) if len(values) > 5 else None,
        "peak3y": peak_row["close"],
        "peak3yDate": peak_row["date"],
        "drawdown3yPct": (1.0 - last / peak_row["close"]) * 100.0,
        "sma200": latest_sma,
        "belowSma200": bool(latest_sma is not None and last < latest_sma),
        "weeksBelowSma200": below_days / 5.0,
        "history": points,
        "sourceUrl": f"https://finance.yahoo.com/quote/{urllib.parse.quote(symbol)}",
    }


def parse_timeseries_result(result: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    types = result.get("meta", {}).get("type", [])
    key = types[0] if types else None
    if not key:
        return None, []
    rows = result.get(key) or []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        raw = finite((row.get("reportedValue") or {}).get("raw"))
        if raw is None:
            continue
        normalized.append({
            "date": row.get("asOfDate"),
            "periodType": row.get("periodType"),
            "currency": row.get("currencyCode"),
            "value": raw,
        })
    normalized.sort(key=lambda row: row.get("date") or "")
    return key, normalized


def fetch_fundamentals(symbol: str) -> dict[str, list[dict[str, Any]]]:
    period1 = int((NOW - timedelta(days=365 * 6)).timestamp())
    period2 = int((NOW + timedelta(days=3)).timestamp())
    query = urllib.parse.urlencode({
        "symbol": symbol,
        "type": ",".join(FUNDAMENTAL_TYPES),
        "merge": "false",
        "period1": period1,
        "period2": period2,
    }, safe=",")
    url = f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}?{query}"
    payload = get_json(url)
    series: dict[str, list[dict[str, Any]]] = {}
    for result in payload.get("timeseries", {}).get("result", []):
        key, rows = parse_timeseries_result(result)
        if key:
            series[key] = rows
    return series


def latest(series: dict[str, list[dict[str, Any]]], key: str) -> float | None:
    rows = series.get(key) or []
    return rows[-1]["value"] if rows else None


def latest_date(series: dict[str, list[dict[str, Any]]], key: str) -> str | None:
    rows = series.get(key) or []
    return rows[-1].get("date") if rows else None


def growth(series: dict[str, list[dict[str, Any]]], key: str) -> float | None:
    rows = series.get(key) or []
    return pct_change(rows[-1]["value"], rows[-2]["value"]) if len(rows) >= 2 else None


def first_available(series: dict[str, list[dict[str, Any]]], keys: list[str]) -> float | None:
    for key in keys:
        value = latest(series, key)
        if value is not None:
            return value
    return None


def build_company(symbol: str, price: dict[str, Any]) -> dict[str, Any]:
    profile = COMPANIES[symbol]
    data = fetch_fundamentals(symbol)
    revenue = latest(data, "trailingTotalRevenue")
    operating_income = latest(data, "trailingOperatingIncome")
    fcf = latest(data, "trailingFreeCashFlow")
    capex = latest(data, "trailingCapitalExpenditure")
    market_cap = latest(data, "trailingMarketCap")
    cash = first_available(data, [
        "quarterlyCashCashEquivalentsAndShortTermInvestments",
        "quarterlyCashAndCashEquivalents",
    ])
    debt = latest(data, "quarterlyTotalDebt")
    shares = latest(data, "quarterlyDilutedAverageShares")
    if shares is None and market_cap and price.get("close"):
        shares = market_cap / price["close"]
    enterprise_value = None
    if market_cap is not None:
        enterprise_value = market_cap + (debt or 0.0) - (cash or 0.0)
    return {
        "ticker": symbol,
        "name": profile["name"],
        "group": profile["group"],
        "price": price["close"],
        "priceDate": price["date"],
        "change1dPct": price["change1dPct"],
        "change5dPct": price["change5dPct"],
        "drawdown3yPct": price["drawdown3yPct"],
        "belowSma200": price["belowSma200"],
        "weeksBelowSma200": price["weeksBelowSma200"],
        "marketCap": market_cap,
        "enterpriseValue": enterprise_value,
        "cash": cash,
        "debt": debt,
        "shares": shares,
        "ttmRevenue": revenue,
        "revenueGrowthYoYPct": growth(data, "trailingTotalRevenue"),
        "ttmOperatingIncome": operating_income,
        "operatingMarginPct": (operating_income / revenue * 100.0) if operating_income is not None and revenue else None,
        "ttmFreeCashFlow": fcf,
        "freeCashFlowGrowthYoYPct": growth(data, "trailingFreeCashFlow"),
        "freeCashFlowMarginPct": (fcf / revenue * 100.0) if fcf is not None and revenue else None,
        "freeCashFlowYieldPct": (fcf / market_cap * 100.0) if fcf is not None and market_cap else None,
        "ttmCapex": abs(capex) if capex is not None else None,
        "capexGrowthYoYPct": growth(data, "trailingCapitalExpenditure"),
        "trailingPe": latest(data, "trailingPeRatio"),
        "filingDate": latest_date(data, "trailingTotalRevenue"),
        "assumptions": {
            "discountRatePct": profile["discount"] * 100.0,
            "terminalGrowthPct": profile["terminal"] * 100.0,
            "bearGrowthPct": profile["growth"]["bear"] * 100.0,
            "baseGrowthPct": profile["growth"]["base"] * 100.0,
            "bullGrowthPct": profile["growth"]["bull"] * 100.0,
            "forecastYears": 10,
        },
        "irUrl": profile["ir"],
        "marketSourceUrl": price["sourceUrl"],
        "fundamentalsSourceUrl": f"https://finance.yahoo.com/quote/{symbol}/financials/",
    }


def fetch_fred(series_id: str) -> dict[str, Any]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={urllib.parse.quote(series_id)}"
    text = request(url).decode("utf-8-sig")
    rows: list[tuple[str, float]] = []
    for row in csv.DictReader(io.StringIO(text)):
        raw = finite(row.get(series_id))
        if raw is not None:
            rows.append((row["observation_date"], raw))
    if not rows:
        raise RuntimeError(f"No observations for FRED {series_id}")
    last_date, last_value = rows[-1]
    cutoff = datetime.fromisoformat(last_date).date() - timedelta(days=95)
    prior = next((value for date, value in reversed(rows) if datetime.fromisoformat(date).date() <= cutoff), rows[0][1])
    low_3m = min(value for date, value in rows if datetime.fromisoformat(date).date() >= cutoff)
    return {
        "seriesId": series_id,
        "date": last_date,
        "valuePct": last_value,
        "change3mPctPoints": last_value - prior,
        "riseFrom3mLowPctPoints": last_value - low_3m,
        "sourceUrl": f"https://fred.stlouisfed.org/series/{series_id}",
    }


def sampled_chart(price_data: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    start = (NOW.date() - timedelta(days=365 * 3)).isoformat()
    symbols = [s for s in COMPANIES if s != "ARM"]
    maps = {
        symbol: {row["date"]: row["close"] for row in price_data[symbol]["history"] if row["date"] >= start}
        for symbol in symbols
    }
    sox_map = {row["date"]: row["close"] for row in price_data["SOX"]["history"] if row["date"] >= start}
    dates = sorted(set(sox_map).intersection(*(set(values) for values in maps.values())))
    if not dates:
        return []
    base_date = dates[0]
    base_sox = sox_map[base_date]
    bases = {symbol: maps[symbol][base_date] for symbol in symbols}
    output: list[dict[str, Any]] = []
    for index, date in enumerate(dates):
        if index % 5 != 0 and index != len(dates) - 1:
            continue
        basket = statistics.mean(maps[symbol][date] / bases[symbol] * 100.0 for symbol in symbols)
        output.append({
            "date": date,
            "sox": sox_map[date] / base_sox * 100.0,
            "aiBasket": basket,
        })
    return output


def strip_history(price_data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    compact: dict[str, dict[str, Any]] = {}
    for symbol, data in price_data.items():
        compact[symbol] = {key: value for key, value in data.items() if key != "history"}
    return compact


def main() -> None:
    statuses: list[SourceStatus] = []
    errors: list[str] = []
    prices: dict[str, dict[str, Any]] = {}
    companies: list[dict[str, Any]] = []

    for label, symbol in PRICE_SYMBOLS.items():
        try:
            prices[label] = fetch_price_series(symbol)
            statuses.append(SourceStatus("Yahoo Finance chart", prices[label]["sourceUrl"], True, NOW.isoformat(), label))
        except Exception as exc:  # keep other sources usable if one ticker fails
            errors.append(f"Price {label}: {exc}")
            statuses.append(SourceStatus("Yahoo Finance chart", f"https://finance.yahoo.com/quote/{symbol}", False, NOW.isoformat(), str(exc)))

    for symbol in COMPANIES:
        if symbol not in prices:
            continue
        try:
            companies.append(build_company(symbol, prices[symbol]))
            statuses.append(SourceStatus("Yahoo Finance fundamentals", f"https://finance.yahoo.com/quote/{symbol}/financials/", True, NOW.isoformat(), symbol))
        except Exception as exc:
            errors.append(f"Fundamentals {symbol}: {exc}")
            statuses.append(SourceStatus("Yahoo Finance fundamentals", f"https://finance.yahoo.com/quote/{symbol}/financials/", False, NOW.isoformat(), str(exc)))

    macro: dict[str, Any] = {}
    for key, series in {"highYieldOas": "BAMLH0A0HYM2", "real10yYield": "DFII10"}.items():
        try:
            macro[key] = fetch_fred(series)
            statuses.append(SourceStatus("FRED", macro[key]["sourceUrl"], True, NOW.isoformat(), series))
        except Exception as exc:
            errors.append(f"FRED {series}: {exc}")
            statuses.append(SourceStatus("FRED", f"https://fred.stlouisfed.org/series/{series}", False, NOW.isoformat(), str(exc)))

    company_drawdowns = [company.get("drawdown3yPct") for company in companies]
    below_count = sum(1 for company in companies if company.get("belowSma200"))
    hyperscaler_capex = [
        company.get("capexGrowthYoYPct") for company in companies if company["ticker"] in HYPERSCALERS
    ]
    payload = {
        "schemaVersion": 2,
        "generatedAtUtc": NOW.isoformat(),
        "generatedAtJst": NOW.astimezone(JST).isoformat(),
        "marketDate": prices.get("SOX", {}).get("date"),
        "dataQuality": {
            "successfulRequests": sum(1 for status in statuses if status.ok),
            "failedRequests": sum(1 for status in statuses if not status.ok),
            "companyCoverage": len(companies),
            "expectedCompanies": len(COMPANIES),
            "warnings": errors,
        },
        "market": {
            "series": strip_history(prices),
            "aiBasket": {
                "constituents": [company["ticker"] for company in companies],
                "medianDrawdown3yPct": median(company_drawdowns),
                "breadthBelowSma200Pct": (below_count / len(companies) * 100.0) if companies else None,
                "medianChange1dPct": median(company.get("change1dPct") for company in companies),
                "medianChange5dPct": median(company.get("change5dPct") for company in companies),
            },
            "normalizedChart": sampled_chart(prices) if "SOX" in prices and len(prices) >= 8 else [],
        },
        "macro": macro,
        "companies": companies,
        "derived": {
            "medianRevenueGrowthYoYPct": median(company.get("revenueGrowthYoYPct") for company in companies),
            "medianFreeCashFlowGrowthYoYPct": median(company.get("freeCashFlowGrowthYoYPct") for company in companies),
            "medianHyperscalerCapexGrowthYoYPct": median(hyperscaler_capex),
            "hyperscalersWithCapexCuts": sum(1 for value in hyperscaler_capex if value is not None and value <= -10.0),
        },
        "manualInputs": {
            "forwardEpsRevision3mPct": None,
            "companiesWithEpsCuts": None,
            "memoryOrGpuPriceDropPct": None,
            "majorProjectCancellations90d": None,
            "supplierInventoryGapPctPoints": None,
            "note": "These fields require a consistent paid consensus series, product-level pricing, or verified project announcements. Missing is not zero.",
        },
        "sourceStatus": [status.__dict__ for status in statuses],
        "methodVersion": "2.0.0",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT} with {len(companies)} companies and {len(errors)} warnings")


if __name__ == "__main__":
    main()
