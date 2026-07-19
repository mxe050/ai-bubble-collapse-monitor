#!/usr/bin/env python3
"""Build the six-series S&P 500 / Nikkei 225 comparison package.

The browser receives only validated monthly observations. Point-in-time
valuation history is optional and is never synthesized when a licensed data
provider is not configured.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import urllib.parse
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "global-market-value-comparison.json"
MONEY_HISTORY = ROOT / "data" / "money-strategist-history.json"
CACHE_DIR = ROOT / "data" / "cache" / "global-comparison"
VALUATION_DIR = ROOT / "data" / "valuation"
JST = timezone(timedelta(hours=9))
MINIMUM_VALUATION_COVERAGE = 0.80

YAHOO_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    "?period1=473385600&period2={period2}&interval=1mo&events=history"
    "&includeAdjustedClose=true"
)
BOJ_FX_URL = (
    "https://www.stat-search.boj.or.jp/api/v1/getDataCode"
    "?format=json&lang=en&db=FM08&startDate=198501&endDate={end_date}&code=FXERM06"
)
JAPAN_CPI_URL = (
    "https://www.e-stat.go.jp/en/stat-search/file-download"
    "?fileKind=1&statInfId=000032103842"
)


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def month_key(value: str | date | datetime) -> str:
    if isinstance(value, str):
        return value[:7]
    return f"{value.year:04d}-{value.month:02d}"


def month_date(key: str) -> str:
    return f"{key}-01"


def month_end(key: str) -> date:
    year, month = (int(part) for part in key.split("-"))
    return date(year, month, monthrange(year, month)[1])


def decimal_year(key: str) -> float:
    year, month = (int(part) for part in key.split("-"))
    return round(year + (month - 1) / 12.0, 6)


def rounded(value: float | None, digits: int = 6) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


@dataclass
class CachedResponse:
    body: bytes
    cache_state: str
    fetched_at: str | None
    warning: str | None = None


class CachedFetcher:
    def __init__(self, request_fn: Callable[..., bytes], *, ttl_seconds: int = 7200) -> None:
        self.request_fn = request_fn
        self.ttl_seconds = ttl_seconds
        self.entries: list[dict[str, Any]] = []
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def get(self, url: str, cache_name: str) -> CachedResponse:
        path = CACHE_DIR / cache_name
        now = datetime.now(timezone.utc)
        if path.exists():
            age = now.timestamp() - path.stat().st_mtime
            if age <= self.ttl_seconds:
                response = CachedResponse(
                    path.read_bytes(), "fresh-cache",
                    datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                )
                self._record(cache_name, url, response)
                return response
        try:
            body = self.request_fn(url, timeout=40, attempts=3)
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_bytes(body)
            temp.replace(path)
            response = CachedResponse(body, "network", now.isoformat())
        except Exception as exc:
            if not path.exists():
                raise
            response = CachedResponse(
                path.read_bytes(), "stale-fallback",
                datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                f"{cache_name}: live update failed; retained the last successful cache ({exc})",
            )
        self._record(cache_name, url, response)
        return response

    def _record(self, cache_name: str, url: str, response: CachedResponse) -> None:
        self.entries.append({
            "cacheKey": cache_name,
            "sourceUrl": url,
            "state": response.cache_state,
            "fetchedAtUtc": response.fetched_at,
            "warning": response.warning,
        })


class MarketIndexProvider:
    """Monthly observed market closes from the existing Yahoo adapter family."""

    def __init__(self, fetcher: CachedFetcher) -> None:
        self.fetcher = fetcher

    def monthly_closes(self, symbol: str, cache_name: str) -> tuple[dict[str, float], dict[str, Any]]:
        encoded = urllib.parse.quote(symbol, safe="")
        period2 = int((datetime.now(timezone.utc) + timedelta(days=3)).timestamp())
        url = YAHOO_URL.format(symbol=encoded, period2=period2)
        response = self.fetcher.get(url, cache_name)
        payload = json.loads(response.body.decode("utf-8"))
        result = payload["chart"]["result"][0]
        meta = result.get("meta") or {}
        timezone_name = meta.get("exchangeTimezoneName") or "UTC"
        try:
            exchange_timezone = ZoneInfo(timezone_name)
        except Exception:
            exchange_timezone = timezone.utc
        timestamps = result.get("timestamp") or []
        closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        monthly: dict[str, float] = {}
        for timestamp, raw_close in zip(timestamps, closes):
            close = finite(raw_close)
            if close is None or close <= 0:
                continue
            observed = datetime.fromtimestamp(int(timestamp), timezone.utc).astimezone(exchange_timezone)
            key = month_key(observed)
            if key >= "1985-01":
                monthly[key] = close
        if len(monthly) < 450:
            raise RuntimeError(f"Insufficient monthly history for {symbol}: {len(monthly)}")
        return monthly, {
            "provider": "Yahoo Finance chart API",
            "symbol": symbol,
            "sourceUrl": f"https://finance.yahoo.com/quote/{encoded}/history/",
            "exchangeTimezone": timezone_name,
            "frequency": "Monthly; provider month-end close",
            "latestMonth": max(monthly),
            "cacheState": response.cache_state,
        }


class ExchangeRateProvider:
    """Official BOJ end-of-month JPY per USD series."""

    def __init__(self, fetcher: CachedFetcher) -> None:
        self.fetcher = fetcher

    def monthly_jpy_per_usd(self) -> tuple[dict[str, float], dict[str, Any]]:
        end_date = datetime.now(JST).strftime("%Y%m")
        url = BOJ_FX_URL.format(end_date=end_date)
        response = self.fetcher.get(url, "boj-fxerm06.json")
        payload = json.loads(response.body.decode("utf-8"))
        result = (payload.get("RESULTSET") or [None])[0]
        if not result:
            raise RuntimeError(f"BOJ FX API returned no result: {payload.get('MESSAGE')}")
        unit = str(result.get("UNIT") or "")
        if "Yen per U.S. Dollar" not in unit:
            raise RuntimeError(f"Unexpected FX direction/unit: {unit}")
        values = result.get("VALUES") or {}
        monthly: dict[str, float] = {}
        for raw_date, raw_value in zip(values.get("SURVEY_DATES") or [], values.get("VALUES") or []):
            value = finite(raw_value)
            text = str(raw_date)
            if value is None or value <= 0 or len(text) != 6:
                continue
            key = f"{text[:4]}-{text[4:]}"
            if key >= "1985-01":
                monthly[key] = value
        if len(monthly) < 450:
            raise RuntimeError(f"Insufficient BOJ FX history: {len(monthly)}")
        return monthly, {
            "provider": "Bank of Japan Time-Series Data Search API",
            "seriesId": result.get("SERIES_CODE"),
            "name": result.get("NAME_OF_TIME_SERIES"),
            "unit": unit,
            "direction": "JPY_PER_USD",
            "sourceUrl": "https://www.stat-search.boj.or.jp/ssi/mtshtml/fm08_m_1_en.html",
            "latestMonth": max(monthly),
            "lastSourceUpdate": result.get("LAST_UPDATE"),
            "cacheState": response.cache_state,
        }


class CPIProvider:
    """US CPI-U from the existing package and official Japan all-items CPI."""

    def __init__(self, fetcher: CachedFetcher) -> None:
        self.fetcher = fetcher

    def us_monthly(self) -> tuple[dict[str, float], dict[str, Any]]:
        package = json.loads(MONEY_HISTORY.read_text(encoding="utf-8"))
        inflation = package.get("inflation") or {}
        monthly: dict[str, float] = {}
        for row in inflation.get("history") or []:
            value = finite(row.get("value"))
            if value is not None and value > 0:
                monthly[month_key(str(row.get("date") or ""))] = value
        if len(monthly) < 450:
            raise RuntimeError(f"Insufficient US CPI history: {len(monthly)}")
        return monthly, {
            "provider": "FRED / U.S. Bureau of Labor Statistics",
            "seriesId": inflation.get("seriesId") or "CPIAUCNS",
            "name": inflation.get("name") or "CPI-U All Items",
            "unit": inflation.get("units") or "Index 1982-1984=100",
            "frequency": inflation.get("frequency") or "Monthly, not seasonally adjusted",
            "sourceUrl": inflation.get("sourceUrl") or "https://fred.stlouisfed.org/series/CPIAUCNS",
            "sourceAgencyUrl": inflation.get("sourceAgencyUrl") or "https://www.bls.gov/cpi/",
            "latestMonth": max(monthly),
        }

    def japan_monthly(self) -> tuple[dict[str, float], dict[str, Any]]:
        response = self.fetcher.get(JAPAN_CPI_URL, "japan-cpi-all-items.csv")
        text: str | None = None
        encoding_used = ""
        for encoding in ("cp932", "utf-8-sig", "utf-8"):
            try:
                text = response.body.decode(encoding)
                encoding_used = encoding
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise RuntimeError("Unable to decode Japan CPI CSV")
        monthly: dict[str, float] = {}
        for row in csv.reader(io.StringIO(text)):
            if len(row) < 2:
                continue
            raw_date = row[0].strip()
            value = finite(row[1].replace(",", "").strip())
            if len(raw_date) != 6 or not raw_date.isdigit() or value is None or value <= 0:
                continue
            key = f"{raw_date[:4]}-{raw_date[4:]}"
            if key >= "1985-01":
                monthly[key] = value
        if len(monthly) < 450:
            raise RuntimeError(f"Insufficient Japan CPI history: {len(monthly)}")
        return monthly, {
            "provider": "Statistics Bureau of Japan / e-Stat",
            "seriesId": "2020-base CPI, All items, Japan, monthly",
            "name": "Consumer Price Index, All items, Japan",
            "unit": "Index 2020=100",
            "frequency": "Monthly",
            "sourceUrl": "https://www.stat.go.jp/english/data/cpi/",
            "downloadUrl": JAPAN_CPI_URL,
            "latestMonth": max(monthly),
            "encoding": encoding_used,
            "cacheState": response.cache_state,
        }


class ConstituentsProvider:
    """Adapter boundary for licensed point-in-time index membership history."""

    def metadata(self, index_id: str) -> dict[str, Any]:
        return {
            "index": index_id,
            "status": "not-configured",
            "required": "Historical membership, effective dates, weights and corporate actions",
        }


class FundamentalsProvider:
    """Adapter boundary for point-in-time financial statement histories."""

    def metadata(self, index_id: str) -> dict[str, Any]:
        return {
            "index": index_id,
            "status": "not-configured",
            "required": "Report availability dates, forecasts, debt, cash and diluted shares",
        }


class ValuationProvider:
    """Load optional licensed point-in-time valuation observations."""

    def __init__(self, index_id: str, total_companies: int) -> None:
        self.index_id = index_id
        self.total_companies = total_companies
        self.path = VALUATION_DIR / f"{index_id}-point-in-time.json"

    def observations(self) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
        if not self.path.exists():
            return [], self._unavailable("Point-in-time constituent fundamentals are not configured"), []
        warnings: list[str] = []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schemaVersion") != 1 or payload.get("index") != self.index_id:
            raise ValueError(f"Invalid valuation provider schema: {self.path.name}")
        accepted: list[dict[str, Any]] = []
        for row_number, source in enumerate(payload.get("observations") or [], start=1):
            try:
                observed_date = date.fromisoformat(str(source["date"])[:10])
                report_available = date.fromisoformat(str(source["reportAvailableDate"])[:10])
                value = finite(source.get("theoreticalIndex"))
                coverage = finite(source.get("coverageRatio"))
                available = int(source.get("availableCompanies"))
                total = int(source.get("totalCompanies"))
                wacc = finite(source.get("weightedWaccPct"))
                growth = finite(source.get("weightedPerpetualGrowthPct"))
                if report_available > observed_date:
                    raise ValueError("reportAvailableDate is after valuation date")
                if value is None or value <= 0:
                    raise ValueError("theoreticalIndex must be positive")
                if coverage is None or not 0 <= coverage <= 1:
                    raise ValueError("coverageRatio must be 0..1")
                if available < 0 or total <= 0 or available > total:
                    raise ValueError("company counts are invalid")
                if wacc is not None and growth is not None and wacc <= growth:
                    raise ValueError("WACC must exceed perpetual growth")
                accepted.append({
                    "date": observed_date.isoformat(),
                    "month": month_key(observed_date),
                    "theoreticalIndex": value,
                    "coverageRatio": coverage,
                    "availableCompanies": available,
                    "totalCompanies": total,
                    "weightedWaccPct": wacc,
                    "weightedPerpetualGrowthPct": growth,
                    "financialAsOfDate": source.get("financialAsOfDate"),
                    "reportAvailableDate": report_available.isoformat(),
                    "source": source.get("source") or payload.get("source"),
                    "models": source.get("models") or payload.get("models") or [],
                })
            except Exception as exc:
                warnings.append(f"{self.index_id} valuation row {row_number}: {exc}")
        accepted.sort(key=lambda row: row["date"])
        valid = [row for row in accepted if row["coverageRatio"] >= MINIMUM_VALUATION_COVERAGE]
        latest = valid[-1] if valid else (accepted[-1] if accepted else None)
        status = {
            "index": self.index_id,
            "status": "available" if valid else "insufficient-coverage",
            "reason": None if valid else "No observation reaches the required 80% index-weight coverage",
            "minimumCoverageRatio": MINIMUM_VALUATION_COVERAGE,
            "availableCompanies": latest.get("availableCompanies") if latest else 0,
            "totalCompanies": latest.get("totalCompanies") if latest else self.total_companies,
            "coverageRatio": latest.get("coverageRatio") if latest else 0.0,
            "financialAsOfDate": latest.get("financialAsOfDate") if latest else None,
            "reportAvailableDate": latest.get("reportAvailableDate") if latest else None,
            "updatedAt": payload.get("updatedAt"),
            "source": latest.get("source") if latest else payload.get("source"),
            "models": latest.get("models") if latest else payload.get("models") or [],
            "providerFile": str(self.path.relative_to(ROOT)).replace("\\", "/"),
        }
        return accepted, status, warnings

    def _unavailable(self, reason: str) -> dict[str, Any]:
        return {
            "index": self.index_id,
            "status": "unavailable",
            "reason": reason,
            "minimumCoverageRatio": MINIMUM_VALUATION_COVERAGE,
            "availableCompanies": 0,
            "totalCompanies": self.total_companies,
            "coverageRatio": 0.0,
            "financialAsOfDate": None,
            "reportAvailableDate": None,
            "updatedAt": None,
            "source": None,
            "models": [],
            "providerFile": str(self.path.relative_to(ROOT)).replace("\\", "/"),
        }


def latest_as_of(observations: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    target = month_end(key)
    eligible = [row for row in observations if date.fromisoformat(row["date"]) <= target]
    return eligible[-1] if eligible else None


def normalize_rows(rows: list[dict[str, Any]], raw_key: str, normalized_key: str) -> str | None:
    base_row = next((row for row in rows if finite(row.get(raw_key)) not in (None, 0)), None)
    if not base_row:
        for row in rows:
            row[normalized_key] = None
        return None
    base_value = float(base_row[raw_key])
    for row in rows:
        value = finite(row.get(raw_key))
        row[normalized_key] = rounded(value / base_value * 100.0) if value is not None else None
    return base_row["date"]


def _series_definitions() -> list[dict[str, Any]]:
    return [
        {
            "id": "sp500Nominal",
            "name": "S&P 500・名目指数",
            "shortName": "S&P 500・名目",
            "normalizedField": "sp500NominalNormalized",
            "rawField": "sp500Nominal",
            "market": "S&P 500",
            "color": "#155EEF",
            "lineStyle": "solid",
            "defaultVisible": True,
            "isTheoretical": False,
        },
        {
            "id": "sp500Real",
            "name": "S&P 500・米国CPI調整後実質指数",
            "shortName": "S&P 500・実質",
            "normalizedField": "sp500RealNormalized",
            "rawField": "sp500Real",
            "market": "S&P 500",
            "color": "#2563EB",
            "lineStyle": "dashed",
            "defaultVisible": True,
            "isTheoretical": False,
        },
        {
            "id": "sp500TheoreticalReal",
            "name": "S&P 500構成企業・実質理論価値指数",
            "shortName": "S&P 500・実質理論価値",
            "normalizedField": "sp500TheoreticalRealNormalized",
            "rawField": "sp500TheoreticalReal",
            "market": "S&P 500",
            "color": "#0B4EA2",
            "lineStyle": "dash-dot-diamond",
            "defaultVisible": True,
            "isTheoretical": True,
        },
        {
            "id": "nikkeiUsd",
            "name": "日経平均・ドル換算指数",
            "shortName": "日経平均・USD",
            "normalizedField": "nikkeiUsdNormalized",
            "rawField": "nikkeiUsd",
            "market": "Nikkei 225",
            "color": "#D92D20",
            "lineStyle": "solid",
            "defaultVisible": True,
            "isTheoretical": False,
        },
        {
            "id": "nikkeiRealUsd",
            "name": "日経平均・日本CPI調整後／ドル換算指数",
            "shortName": "日経平均・実質USD",
            "normalizedField": "nikkeiRealUsdNormalized",
            "rawField": "nikkeiRealUsd",
            "market": "Nikkei 225",
            "color": "#EF4444",
            "lineStyle": "dashed",
            "defaultVisible": True,
            "isTheoretical": False,
        },
        {
            "id": "nikkeiTheoreticalUsd",
            "name": "日経平均構成企業・理論価値指数／ドル換算",
            "shortName": "日経平均・理論価値USD",
            "normalizedField": "nikkeiTheoreticalUsdNormalized",
            "rawField": "nikkeiTheoreticalUsd",
            "market": "Nikkei 225",
            "color": "#9F1239",
            "lineStyle": "dash-dot-diamond",
            "defaultVisible": True,
            "isTheoretical": True,
        },
    ]


def build_global_comparison(request_fn: Callable[..., bytes]) -> dict[str, Any]:
    fetcher = CachedFetcher(request_fn)
    market_provider = MarketIndexProvider(fetcher)
    fx_provider = ExchangeRateProvider(fetcher)
    cpi_provider = CPIProvider(fetcher)
    constituents_provider = ConstituentsProvider()
    fundamentals_provider = FundamentalsProvider()
    errors: list[str] = []

    sp500, sp_source = market_provider.monthly_closes("^GSPC", "yahoo-sp500-monthly.json")
    nikkei, nikkei_source = market_provider.monthly_closes("^N225", "yahoo-nikkei225-monthly.json")
    fx, fx_source = fx_provider.monthly_jpy_per_usd()
    us_cpi, us_cpi_source = cpi_provider.us_monthly()
    japan_cpi, japan_cpi_source = cpi_provider.japan_monthly()

    sp_valuations, sp_coverage, sp_warnings = ValuationProvider("sp500", 500).observations()
    nikkei_valuations, nikkei_coverage, nikkei_warnings = ValuationProvider("nikkei225", 225).observations()
    errors.extend(sp_warnings)
    errors.extend(nikkei_warnings)
    errors.extend(entry["warning"] for entry in fetcher.entries if entry.get("warning"))

    usable_months = sorted(
        set(sp500) & set(nikkei) & set(fx) & set(us_cpi) & set(japan_cpi)
    )
    usable_months = [key for key in usable_months if key >= "1985-01"]
    if len(usable_months) < 450:
        raise RuntimeError(f"Only {len(usable_months)} complete monthly observations are available")

    us_cpi_reference_month = max(us_cpi)
    japan_cpi_reference_month = max(japan_cpi)
    us_cpi_reference = us_cpi[us_cpi_reference_month]
    japan_cpi_reference = japan_cpi[japan_cpi_reference_month]
    if us_cpi_reference <= 0 or japan_cpi_reference <= 0:
        raise ValueError("CPI reference values must be positive")

    rows: list[dict[str, Any]] = []
    for key in usable_months:
        sp_value = sp500[key]
        nikkei_jpy = nikkei[key]
        fx_value = fx[key]
        us_cpi_value = us_cpi[key]
        japan_cpi_value = japan_cpi[key]
        if min(sp_value, nikkei_jpy, fx_value, us_cpi_value, japan_cpi_value) <= 0:
            raise ValueError(f"Non-positive source value in {key}")

        sp_real = sp_value * us_cpi_reference / us_cpi_value
        nikkei_usd = nikkei_jpy / fx_value
        nikkei_real_jpy = nikkei_jpy * japan_cpi_reference / japan_cpi_value
        nikkei_real_usd = nikkei_real_jpy / fx_value

        sp_observation = latest_as_of(sp_valuations, key)
        sp_theoretical_nominal = None
        sp_theoretical_real = None
        if sp_observation and sp_observation["coverageRatio"] >= MINIMUM_VALUATION_COVERAGE:
            sp_theoretical_nominal = sp_observation["theoreticalIndex"]
            sp_theoretical_real = sp_theoretical_nominal * us_cpi_reference / us_cpi_value

        nikkei_observation = latest_as_of(nikkei_valuations, key)
        nikkei_theoretical_jpy = None
        nikkei_theoretical_usd = None
        if nikkei_observation and nikkei_observation["coverageRatio"] >= MINIMUM_VALUATION_COVERAGE:
            nikkei_theoretical_jpy = nikkei_observation["theoreticalIndex"]
            nikkei_theoretical_usd = nikkei_theoretical_jpy / fx_value

        rows.append({
            "date": month_date(key),
            "x": decimal_year(key),
            "sp500Nominal": rounded(sp_value, 4),
            "usCpi": rounded(us_cpi_value, 4),
            "sp500Real": rounded(sp_real),
            "sp500TheoreticalNominal": rounded(sp_theoretical_nominal),
            "sp500TheoreticalReal": rounded(sp_theoretical_real),
            "sp500ValuationCoverage": rounded(sp_observation["coverageRatio"] if sp_observation else None, 4),
            "sp500ValuationAvailableCompanies": sp_observation["availableCompanies"] if sp_observation else None,
            "sp500ValuationTotalCompanies": sp_observation["totalCompanies"] if sp_observation else 500,
            "sp500ValuationFinancialAsOfDate": sp_observation["financialAsOfDate"] if sp_observation else None,
            "sp500WeightedWaccPct": rounded(sp_observation["weightedWaccPct"] if sp_observation else None, 4),
            "sp500WeightedPerpetualGrowthPct": rounded(sp_observation["weightedPerpetualGrowthPct"] if sp_observation else None, 4),
            "nikkeiJpy": rounded(nikkei_jpy, 4),
            "usdjpyJpyPerUsd": rounded(fx_value, 4),
            "nikkeiUsd": rounded(nikkei_usd),
            "japanCpi": rounded(japan_cpi_value, 4),
            "nikkeiRealJpy": rounded(nikkei_real_jpy),
            "nikkeiRealUsd": rounded(nikkei_real_usd),
            "nikkeiTheoreticalJpy": rounded(nikkei_theoretical_jpy),
            "nikkeiTheoreticalUsd": rounded(nikkei_theoretical_usd),
            "nikkeiValuationCoverage": rounded(nikkei_observation["coverageRatio"] if nikkei_observation else None, 4),
            "nikkeiValuationAvailableCompanies": nikkei_observation["availableCompanies"] if nikkei_observation else None,
            "nikkeiValuationTotalCompanies": nikkei_observation["totalCompanies"] if nikkei_observation else 225,
            "nikkeiValuationFinancialAsOfDate": nikkei_observation["financialAsOfDate"] if nikkei_observation else None,
            "nikkeiWeightedWaccPct": rounded(nikkei_observation["weightedWaccPct"] if nikkei_observation else None, 4),
            "nikkeiWeightedPerpetualGrowthPct": rounded(nikkei_observation["weightedPerpetualGrowthPct"] if nikkei_observation else None, 4),
        })

    series_base_dates = {
        "sp500Nominal": normalize_rows(rows, "sp500Nominal", "sp500NominalNormalized"),
        "sp500Real": normalize_rows(rows, "sp500Real", "sp500RealNormalized"),
        "sp500TheoreticalReal": normalize_rows(rows, "sp500TheoreticalReal", "sp500TheoreticalRealNormalized"),
        "nikkeiUsd": normalize_rows(rows, "nikkeiUsd", "nikkeiUsdNormalized"),
        "nikkeiRealUsd": normalize_rows(rows, "nikkeiRealUsd", "nikkeiRealUsdNormalized"),
        "nikkeiTheoreticalUsd": normalize_rows(rows, "nikkeiTheoreticalUsd", "nikkeiTheoreticalUsdNormalized"),
    }

    generated = datetime.now(timezone.utc)
    payload = {
        "schemaVersion": 1,
        "generatedAtUtc": generated.isoformat(),
        "generatedAtJst": generated.astimezone(JST).isoformat(),
        "title": "S&P 500・日経平均の市場価格と理論価値を比較する統合チャート",
        "frequency": "monthly",
        "baseDate": rows[0]["date"],
        "seriesBaseDates": series_base_dates,
        "latestCommonMonth": rows[-1]["date"],
        "observationCount": len(rows),
        "axis": {"type": "linear", "min": 0, "secondAxis": False},
        "exchangeRate": {
            "direction": "JPY_PER_USD",
            "definition": "1米ドル当たりの日本円",
            "unit": fx_source["unit"],
            "seriesId": fx_source["seriesId"],
        },
        "cpiReferences": {
            "us": {"month": month_date(us_cpi_reference_month), "value": us_cpi_reference, "seriesId": us_cpi_source["seriesId"]},
            "japan": {"month": month_date(japan_cpi_reference_month), "value": japan_cpi_reference, "seriesId": japan_cpi_source["seriesId"]},
        },
        "seriesDefinitions": _series_definitions(),
        "points": rows,
        "valuationCoverage": {
            "sp500": sp_coverage,
            "nikkei225": nikkei_coverage,
        },
        "providerAdapters": {
            "MarketIndexProvider": [sp_source, nikkei_source],
            "ExchangeRateProvider": fx_source,
            "CPIProvider": [us_cpi_source, japan_cpi_source],
            "ConstituentsProvider": [constituents_provider.metadata("sp500"), constituents_provider.metadata("nikkei225")],
            "FundamentalsProvider": [fundamentals_provider.metadata("sp500"), fundamentals_provider.metadata("nikkei225")],
            "ValuationProvider": [sp_coverage, nikkei_coverage],
        },
        "crises": [
            {"id": "japan-bubble", "label": "バブル崩壊", "startDate": "1990-01-01", "endDate": "1992-08-31", "color": "rgba(245, 158, 11, 0.12)", "description": "日本の資産価格バブル崩壊を示す代表期間"},
            {"id": "dotcom", "label": "ITバブル崩壊", "startDate": "2000-03-01", "endDate": "2002-10-31", "color": "rgba(220, 38, 38, 0.10)", "description": "IT株のピーク後から主要株価指数の底までの代表期間"},
            {"id": "gfc", "label": "リーマンショック", "startDate": "2008-09-01", "endDate": "2009-03-31", "color": "rgba(124, 58, 237, 0.10)", "description": "世界金融危機が急性化した代表期間"},
            {"id": "covid", "label": "コロナショック", "startDate": "2020-02-01", "endDate": "2020-04-30", "color": "rgba(13, 148, 136, 0.10)", "description": "新型コロナ流行初期の急落を示す代表期間"},
        ],
        "formulas": {
            "normalization": "calculated_value_t / calculated_value_base_date * 100",
            "sp500Real": "sp500_nominal_t * us_cpi_reference / us_cpi_t",
            "nikkeiUsd": "nikkei_jpy_t / JPY_PER_USD_t",
            "nikkeiRealUsd": "nikkei_jpy_t * japan_cpi_reference / japan_cpi_t / JPY_PER_USD_t",
            "sp500TheoreticalReal": "sp500_theoretical_nominal_t * us_cpi_reference / us_cpi_t",
            "nikkeiTheoreticalUsd": "nikkei_theoretical_jpy_t / JPY_PER_USD_t",
        },
        "sources": [sp_source, nikkei_source, fx_source, us_cpi_source, japan_cpi_source],
        "cache": {
            "ttlSeconds": fetcher.ttl_seconds,
            "entries": fetcher.entries,
            "fallbackRule": "Keep the previous successful raw cache when a live request fails",
        },
        "errors": errors,
        "limitations": [
            "Point-in-time theoretical values remain missing until licensed constituent and financial histories reach at least 80% index-weight coverage.",
            "Missing companies are never assigned a value of zero, and current fundamentals are never backfilled into past dates.",
            "Monthly observations are joined by calendar month; no future observation or long-gap linear interpolation is used.",
        ],
    }
    return payload


def write_global_comparison(request_fn: Callable[..., bytes]) -> dict[str, Any]:
    previous = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
    try:
        payload = build_global_comparison(request_fn)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
    except Exception:
        if previous is not None:
            OUTPUT.write_text(previous, encoding="utf-8")
        raise


if __name__ == "__main__":
    from update_data import request

    result = write_global_comparison(request)
    print(f"Wrote {OUTPUT} with {len(result['points'])} monthly observations")
