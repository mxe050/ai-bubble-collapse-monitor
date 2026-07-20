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
import re
import statistics
import urllib.parse
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "global-market-value-comparison.json"
MONEY_HISTORY = ROOT / "data" / "money-strategist-history.json"
CACHE_DIR = ROOT / "data" / "cache" / "global-comparison"
VALUATION_DIR = ROOT / "data" / "valuation"
NIKKEI_PER_HISTORY = CACHE_DIR / "nikkei-per-index-weight-history.json"
JST = timezone(timedelta(hours=9))
MINIMUM_VALUATION_COVERAGE = 0.80
MODEL_ERP_PCT = 4.50
MODEL_CREDIT_SPREAD_BASELINE_PCT = 1.00
MODEL_MIN_CAP_RATE_PCT = 2.50
MODEL_REAL_GROWTH_PCT = {"sp500": 1.50, "nikkei225": 1.00}
MODEL_SENSITIVITY = {
    "low": {"erpAddPct": 1.00, "realGrowthAddPct": -0.50},
    "high": {"erpAddPct": -0.75, "realGrowthAddPct": 0.50},
}

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
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
SP_EARNINGS_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/spearn.html"
NIKKEI_PER_URL = (
    "https://indexes.nikkei.co.jp/en/nkave/statistics/dataload"
    "?list=per&year={year}&month={month}"
)
JGB_HISTORY_URL = (
    "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"
    "historical/jgbcme_all.csv"
)
HTML_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/138.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


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

    def get(
        self,
        url: str,
        cache_name: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> CachedResponse:
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
            body = self.request_fn(
                url,
                timeout=40,
                attempts=3,
                extra_headers=extra_headers,
            )
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


class TableRowsParser(HTMLParser):
    """Collect text cells from ordinary HTML tables without external packages."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif lowered == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def html_table_rows(body: bytes) -> list[list[str]]:
    parser = TableRowsParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    return parser.rows


def shift_month(key: str, offset: int) -> str:
    year, month = (int(part) for part in key.split("-"))
    serial = year * 12 + month - 1 + offset
    return f"{serial // 12:04d}-{serial % 12 + 1:02d}"


def month_keys(start: str, end: str) -> list[str]:
    keys: list[str] = []
    current = start
    while current <= end:
        keys.append(current)
        current = shift_month(current, 1)
    return keys


def value_as_of(series: dict[str, float], key: str, *, max_gap_months: int = 3) -> float | None:
    candidates = [candidate for candidate in series if candidate <= key]
    if not candidates:
        return None
    selected = max(candidates)
    gap = (int(key[:4]) - int(selected[:4])) * 12 + int(key[5:7]) - int(selected[5:7])
    return series[selected] if gap <= max_gap_months else None


def trailing_cpi_growth_pct(cpi: dict[str, float], key: str, years: int = 10) -> float | None:
    current = cpi.get(key)
    previous = cpi.get(shift_month(key, -12 * years))
    if current is None or previous is None or min(current, previous) <= 0:
        return None
    return ((current / previous) ** (1.0 / years) - 1.0) * 100.0


class FredProvider:
    """Monthly public FRED observations used only as model inputs."""

    def __init__(self, fetcher: CachedFetcher) -> None:
        self.fetcher = fetcher

    def monthly(self, series_id: str, name: str) -> tuple[dict[str, float], dict[str, Any]]:
        url = FRED_CSV_URL.format(series_id=series_id)
        response = self.fetcher.get(url, f"fred-{series_id.lower()}.csv")
        text = response.body.decode("utf-8-sig")
        monthly: dict[str, float] = {}
        for row in csv.DictReader(io.StringIO(text)):
            raw_date = row.get("observation_date") or row.get("DATE") or row.get("date")
            value = finite(row.get(series_id))
            if raw_date and value is not None:
                monthly[month_key(raw_date)] = value
        if len(monthly) < 400:
            raise RuntimeError(f"Insufficient FRED history for {series_id}: {len(monthly)}")
        return monthly, {
            "provider": "FRED",
            "seriesId": series_id,
            "name": name,
            "unit": "Percent",
            "frequency": "Monthly",
            "sourceUrl": f"https://fred.stlouisfed.org/series/{series_id}",
            "latestMonth": max(monthly),
            "cacheState": response.cache_state,
        }


class JGBProvider:
    """Month-end Japanese government bond yield from the Ministry of Finance."""

    def __init__(self, fetcher: CachedFetcher) -> None:
        self.fetcher = fetcher

    def monthly(self) -> tuple[dict[str, float], dict[str, Any]]:
        response = self.fetcher.get(JGB_HISTORY_URL, "mof-jgb-history.csv")
        text = response.body.decode("utf-8-sig", errors="replace")
        lines = text.splitlines()
        if len(lines) < 3:
            raise RuntimeError("MOF JGB history is empty")
        monthly: dict[str, float] = {}
        nine_year_fallback = 0
        for row in csv.DictReader(lines[1:]):
            raw_date = (row.get("Date") or "").strip()
            if not raw_date:
                continue
            value = finite(row.get("10Y"))
            if value is None:
                value = finite(row.get("9Y"))
                if value is not None:
                    nine_year_fallback += 1
            if value is None:
                continue
            parsed = datetime.strptime(raw_date, "%Y/%m/%d").date()
            key = month_key(parsed)
            if key >= "1985-01":
                monthly[key] = value
        if len(monthly) < 470:
            raise RuntimeError(f"Insufficient MOF JGB history: {len(monthly)}")
        return monthly, {
            "provider": "Ministry of Finance Japan",
            "seriesId": "JGB-CM-10Y",
            "name": "10-year constant-maturity JGB yield",
            "unit": "Percent",
            "frequency": "Month-end observation",
            "sourceUrl": JGB_HISTORY_URL,
            "latestMonth": max(monthly),
            "fallback": "9-year yield is used only before the official 10-year series begins",
            "fallbackDailyRows": nine_year_fallback,
            "cacheState": response.cache_state,
        }


class SPEarningsProvider:
    """Annual S&P 500 index earnings history published by Aswath Damodaran."""

    def __init__(self, fetcher: CachedFetcher) -> None:
        self.fetcher = fetcher

    def annual(self) -> tuple[dict[int, float], dict[str, Any]]:
        response = self.fetcher.get(
            SP_EARNINGS_URL,
            "damodaran-sp-earnings.html",
            extra_headers=HTML_HEADERS,
        )
        earnings: dict[int, float] = {}
        for row in html_table_rows(response.body):
            if len(row) < 5 or not re.fullmatch(r"19\d{2}|20\d{2}", row[0]):
                continue
            value = finite(row[4].replace(",", ""))
            if value is not None and value > 0:
                earnings[int(row[0])] = value
        if len(earnings) < 60:
            raise RuntimeError(f"Insufficient S&P earnings history: {len(earnings)}")
        return earnings, {
            "provider": "Aswath Damodaran, NYU Stern",
            "seriesId": "SP500-ANNUAL-EARNINGS",
            "name": "S&P 500 earnings and dividends",
            "unit": "Index earnings per share",
            "frequency": "Annual; most recent year may include an estimate",
            "availabilityRule": "Year Y is first used from May of Y+1 to avoid historical look-ahead",
            "sourceUrl": SP_EARNINGS_URL,
            "latestYear": max(earnings),
            "cacheState": response.cache_state,
        }


class NikkeiPERProvider:
    """Official Nikkei 225 index-weight P/E history, cached month by month."""

    def __init__(self, fetcher: CachedFetcher) -> None:
        self.fetcher = fetcher

    def _fetch_month(self, key: str) -> dict[str, Any] | None:
        year, month = key.split("-")
        url = NIKKEI_PER_URL.format(year=year, month=int(month))
        body = self.fetcher.request_fn(
            url,
            timeout=40,
            attempts=3,
            extra_headers=HTML_HEADERS,
        )
        accepted: list[dict[str, Any]] = []
        for row in html_table_rows(body):
            if len(row) < 3 or not re.fullmatch(r"[A-Z][a-z]{2}/\d{2}/\d{4}", row[0]):
                continue
            market_cap_pe = finite(row[1].replace(",", ""))
            index_weight_pe = finite(row[2].replace(",", ""))
            if index_weight_pe is None or index_weight_pe <= 0:
                continue
            observed = datetime.strptime(row[0], "%b/%d/%Y").date()
            accepted.append({
                "date": observed.isoformat(),
                "marketCapPe": market_cap_pe,
                "indexWeightPe": index_weight_pe,
            })
        return accepted[-1] if accepted else None

    def history(self) -> tuple[dict[str, dict[str, Any]], dict[str, Any], list[str]]:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        stored: dict[str, dict[str, Any]] = {}
        if NIKKEI_PER_HISTORY.exists():
            try:
                payload = json.loads(NIKKEI_PER_HISTORY.read_text(encoding="utf-8"))
                stored = {
                    str(key): value for key, value in (payload.get("months") or {}).items()
                    if isinstance(value, dict) and finite(value.get("indexWeightPe")) not in (None, 0)
                }
            except Exception:
                stored = {}

        final_month = month_key(datetime.now(JST))
        expected = month_keys("2004-09", final_month)
        requested = [key for key in expected if key not in stored]
        requested.extend(key for key in expected[-2:] if key not in requested)
        warnings: list[str] = []
        fetched = 0
        if requested:
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_map = {executor.submit(self._fetch_month, key): key for key in requested}
                for future in as_completed(future_map):
                    key = future_map[future]
                    try:
                        observation = future.result()
                        if observation:
                            stored[key] = observation
                            fetched += 1
                    except Exception as exc:
                        warnings.append(f"Nikkei P/E {key}: {exc}")

        if stored:
            ordered = {key: stored[key] for key in sorted(stored)}
            NIKKEI_PER_HISTORY.write_text(json.dumps({
                "schemaVersion": 1,
                "updatedAtUtc": datetime.now(timezone.utc).isoformat(),
                "sourceUrl": NIKKEI_PER_URL.replace("{year}", "YYYY").replace("{month}", "M"),
                "months": ordered,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            stored = ordered
        if len(stored) < 180:
            warnings.append(
                f"Nikkei official P/E history has only {len(stored)} months; the theoretical series may be unavailable"
            )
        latest_key = max(stored) if stored else None
        return stored, {
            "provider": "Nikkei Inc.",
            "seriesId": "NIKKEI225-PE-INDEX-WEIGHT-BASIS",
            "name": "Nikkei 225 P/E, index-weight basis",
            "unit": "Times",
            "frequency": "Daily source; final valid observation in each month",
            "sourceUrl": "https://indexes.nikkei.co.jp/en/nkave/archives/data?list=per",
            "methodologyUrl": "https://indexes.nikkei.co.jp/nkave/archives/file/users_guide_en.pdf",
            "latestMonth": latest_key,
            "latestObservationDate": stored[latest_key]["date"] if latest_key else None,
            "historyMonths": len(stored),
            "refreshedMonths": fetched,
            "usageNote": "Nikkei retains intellectual-property rights; this private tool stores derived analytical values for personal research.",
        }, warnings


def annual_real_earnings_power(
    annual_earnings: dict[int, float],
    cpi: dict[str, float],
    key: str,
) -> tuple[float | None, int | None, float | None]:
    current_cpi = cpi.get(key)
    if current_cpi is None:
        return None, None, None
    eligible = [
        year for year in annual_earnings
        if f"{year + 1:04d}-05" <= key and f"{year:04d}-12" in cpi
    ]
    if len(eligible) < 5:
        return None, None, None
    selected = sorted(eligible)[-5:]
    adjusted = [
        annual_earnings[year] * current_cpi / cpi[f"{year:04d}-12"]
        for year in selected
    ]
    return statistics.median(adjusted), selected[-1], adjusted[-1]


def monthly_real_earnings_power(
    monthly_earnings: dict[str, float],
    cpi: dict[str, float],
    key: str,
) -> tuple[float | None, float | None, str | None]:
    current_cpi = cpi.get(key)
    eligible = [candidate for candidate in monthly_earnings if candidate <= key and candidate in cpi]
    if current_cpi is None or len(eligible) < 24:
        return None, None, None
    selected = sorted(eligible)[-60:]
    adjusted = [monthly_earnings[candidate] * current_cpi / cpi[candidate] for candidate in selected]
    return statistics.median(adjusted), adjusted[-1], selected[-1]


def capitalized_earnings_model(
    earnings_power: float | None,
    risk_free_pct: float | None,
    inflation_pct: float | None,
    credit_spread_pct: float | None,
    *,
    market: str,
) -> dict[str, float | bool] | None:
    if earnings_power is None or risk_free_pct is None or inflation_pct is None:
        return None
    spread = credit_spread_pct if credit_spread_pct is not None else MODEL_CREDIT_SPREAD_BASELINE_PCT
    stress_pct = max(0.0, spread - MODEL_CREDIT_SPREAD_BASELINE_PCT)
    real_growth_pct = MODEL_REAL_GROWTH_PCT[market]

    def scenario(erp_add_pct: float, real_growth_add_pct: float) -> tuple[float, float, float, bool]:
        growth_cap = 5.0 if market == "sp500" else 4.0
        nominal_growth_pct = min(growth_cap, max(-0.5, inflation_pct + real_growth_pct + real_growth_add_pct))
        discount_pct = risk_free_pct + MODEL_ERP_PCT + erp_add_pct + stress_pct
        raw_cap_rate_pct = discount_pct - nominal_growth_pct
        cap_rate_pct = max(MODEL_MIN_CAP_RATE_PCT, raw_cap_rate_pct)
        fair_pe = 100.0 / cap_rate_pct
        return earnings_power * fair_pe, fair_pe, nominal_growth_pct, raw_cap_rate_pct < MODEL_MIN_CAP_RATE_PCT

    central, fair_pe, nominal_growth_pct, floored = scenario(0.0, 0.0)
    low, low_pe, _, low_floored = scenario(
        MODEL_SENSITIVITY["low"]["erpAddPct"],
        MODEL_SENSITIVITY["low"]["realGrowthAddPct"],
    )
    high, high_pe, _, high_floored = scenario(
        MODEL_SENSITIVITY["high"]["erpAddPct"],
        MODEL_SENSITIVITY["high"]["realGrowthAddPct"],
    )
    return {
        "central": central,
        "low": min(low, central, high),
        "high": max(low, central, high),
        "fairPe": fair_pe,
        "lowFairPe": min(low_pe, fair_pe, high_pe),
        "highFairPe": max(low_pe, fair_pe, high_pe),
        "riskFreePct": risk_free_pct,
        "erpPct": MODEL_ERP_PCT,
        "creditSpreadPct": spread,
        "creditStressPct": stress_pct,
        "inflationTrendPct": inflation_pct,
        "nominalGrowthPct": nominal_growth_pct,
        "capRateFloored": floored or low_floored or high_floored,
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


def normalize_against_anchor(
    rows: list[dict[str, Any]],
    raw_key: str,
    anchor_key: str,
    normalized_key: str,
) -> str | None:
    base_row = next((row for row in rows if finite(row.get(anchor_key)) not in (None, 0)), None)
    if not base_row:
        for row in rows:
            row[normalized_key] = None
        return None
    base_value = float(base_row[anchor_key])
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
            "color": "#0057B8",
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
            "color": "#008B8B",
            "lineStyle": "dashed",
            "defaultVisible": True,
            "isTheoretical": False,
        },
        {
            "id": "sp500TheoreticalReal",
            "name": "S&P 500・実質推計理論価値（利益還元）",
            "shortName": "S&P 500・推計理論価値",
            "normalizedField": "sp500TheoreticalRealNormalized",
            "rawField": "sp500TheoreticalReal",
            "normalizationAnchorField": "sp500Real",
            "market": "S&P 500",
            "color": "#6D28D9",
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
            "color": "#D83B2D",
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
            "color": "#C66A00",
            "lineStyle": "dashed",
            "defaultVisible": True,
            "isTheoretical": False,
        },
        {
            "id": "nikkeiTheoreticalUsd",
            "name": "日経平均・推計理論価値（利益還元）／ドル換算",
            "shortName": "日経平均・推計理論価値USD",
            "normalizedField": "nikkeiTheoreticalUsdNormalized",
            "rawField": "nikkeiTheoreticalUsd",
            "normalizationAnchorField": "nikkeiUsd",
            "market": "Nikkei 225",
            "color": "#B0005A",
            "lineStyle": "dash-dot-diamond",
            "defaultVisible": True,
            "isTheoretical": True,
        },
    ]


def _build_global_comparison_legacy(request_fn: Callable[..., bytes]) -> dict[str, Any]:
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


def build_global_comparison(request_fn: Callable[..., bytes]) -> dict[str, Any]:
    """Build observed series plus a transparent top-down theoretical-value proxy."""
    fetcher = CachedFetcher(request_fn)
    market_provider = MarketIndexProvider(fetcher)
    fx_provider = ExchangeRateProvider(fetcher)
    cpi_provider = CPIProvider(fetcher)
    fred_provider = FredProvider(fetcher)
    errors: list[str] = []

    sp500, sp_source = market_provider.monthly_closes("^GSPC", "yahoo-sp500-monthly.json")
    nikkei, nikkei_source = market_provider.monthly_closes("^N225", "yahoo-nikkei225-monthly.json")
    fx, fx_source = fx_provider.monthly_jpy_per_usd()
    us_cpi, us_cpi_source = cpi_provider.us_monthly()
    japan_cpi, japan_cpi_source = cpi_provider.japan_monthly()
    gs10, gs10_source = fred_provider.monthly("GS10", "10-Year Treasury Constant Maturity Rate")
    aaa, aaa_source = fred_provider.monthly("AAA", "Moody's Seasoned Aaa Corporate Bond Yield")
    baa, baa_source = fred_provider.monthly("BAA", "Moody's Seasoned Baa Corporate Bond Yield")
    jgb10, jgb_source = JGBProvider(fetcher).monthly()
    sp_annual_earnings, sp_earnings_source = SPEarningsProvider(fetcher).annual()
    nikkei_per_history, nikkei_per_source, nikkei_per_warnings = NikkeiPERProvider(fetcher).history()
    if nikkei_per_warnings:
        errors.extend(nikkei_per_warnings[:8])
        if len(nikkei_per_warnings) > 8:
            errors.append(f"Nikkei P/E: {len(nikkei_per_warnings) - 8} additional month errors omitted")

    _, sp_coverage, sp_warnings = ValuationProvider("sp500", 500).observations()
    _, nikkei_coverage, nikkei_warnings = ValuationProvider("nikkei225", 225).observations()
    errors.extend(sp_warnings)
    errors.extend(nikkei_warnings)

    usable_months = sorted(set(sp500) & set(nikkei) & set(fx) & set(us_cpi) & set(japan_cpi))
    usable_months = [key for key in usable_months if key >= "1985-01"]
    if len(usable_months) < 450:
        raise RuntimeError(f"Only {len(usable_months)} complete monthly observations are available")

    us_cpi_reference_month = max(us_cpi)
    japan_cpi_reference_month = max(japan_cpi)
    us_cpi_reference = us_cpi[us_cpi_reference_month]
    japan_cpi_reference = japan_cpi[japan_cpi_reference_month]
    if us_cpi_reference <= 0 or japan_cpi_reference <= 0:
        raise ValueError("CPI reference values must be positive")

    nikkei_index_pe: dict[str, float] = {}
    nikkei_index_eps: dict[str, float] = {}
    nikkei_pe_dates: dict[str, str] = {}
    for key, observation in nikkei_per_history.items():
        pe = finite(observation.get("indexWeightPe"))
        close = nikkei.get(key)
        if pe is None or close is None or min(pe, close) <= 0:
            continue
        nikkei_index_pe[key] = pe
        nikkei_index_eps[key] = close / pe
        nikkei_pe_dates[key] = str(observation.get("date") or month_date(key))

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

        baa_value = value_as_of(baa, key)
        aaa_value = value_as_of(aaa, key)
        credit_spread = baa_value - aaa_value if baa_value is not None and aaa_value is not None else None

        sp_earnings_power, sp_earnings_year, sp_latest_earnings = annual_real_earnings_power(
            sp_annual_earnings, us_cpi, key
        )
        sp_model = capitalized_earnings_model(
            sp_earnings_power,
            value_as_of(gs10, key),
            trailing_cpi_growth_pct(us_cpi, key),
            credit_spread,
            market="sp500",
        )
        sp_theoretical_nominal = sp_model["central"] if sp_model else None
        sp_theoretical_latest_earnings = (
            sp_latest_earnings * sp_model["fairPe"]
            if sp_latest_earnings is not None and sp_model else None
        )
        sp_theoretical_low = sp_model["low"] if sp_model else None
        sp_theoretical_high = sp_model["high"] if sp_model else None
        sp_theoretical_real = (
            sp_theoretical_nominal * us_cpi_reference / us_cpi_value
            if sp_theoretical_nominal is not None else None
        )

        nikkei_earnings_power, nikkei_latest_earnings, nikkei_latest_earnings_date = monthly_real_earnings_power(
            nikkei_index_eps, japan_cpi, key
        )
        nikkei_model = capitalized_earnings_model(
            nikkei_earnings_power,
            value_as_of(jgb10, key),
            trailing_cpi_growth_pct(japan_cpi, key),
            credit_spread,
            market="nikkei225",
        )
        nikkei_theoretical_jpy = nikkei_model["central"] if nikkei_model else None
        nikkei_theoretical_latest_earnings = (
            nikkei_latest_earnings * nikkei_model["fairPe"]
            if nikkei_latest_earnings is not None and nikkei_model else None
        )
        nikkei_theoretical_low = nikkei_model["low"] if nikkei_model else None
        nikkei_theoretical_high = nikkei_model["high"] if nikkei_model else None
        nikkei_theoretical_usd = (
            nikkei_theoretical_jpy / fx_value if nikkei_theoretical_jpy is not None else None
        )

        rows.append({
            "date": month_date(key),
            "x": decimal_year(key),
            "sp500Nominal": rounded(sp_value, 4),
            "usCpi": rounded(us_cpi_value, 4),
            "sp500Real": rounded(sp_real),
            "sp500EarningsPower": rounded(sp_earnings_power),
            "sp500EarningsAvailableThroughYear": sp_earnings_year,
            "sp500TheoreticalNominal": rounded(sp_theoretical_nominal),
            "sp500TheoreticalLow": rounded(sp_theoretical_low),
            "sp500LatestEarnings": rounded(sp_latest_earnings),
            "sp500TheoreticalAtLatestEarnings": rounded(sp_theoretical_latest_earnings),
            "sp500TheoreticalHigh": rounded(sp_theoretical_high),
            "sp500TheoreticalReal": rounded(sp_theoretical_real),
            "sp500FairPe": rounded(sp_model["fairPe"] if sp_model else None, 6),
            "sp500RiskFreePct": rounded(sp_model["riskFreePct"] if sp_model else None, 4),
            "sp500ErpPct": rounded(sp_model["erpPct"] if sp_model else None, 4),
            "sp500CreditSpreadPct": rounded(sp_model["creditSpreadPct"] if sp_model else None, 4),
            "sp500CreditStressPct": rounded(sp_model["creditStressPct"] if sp_model else None, 4),
            "sp500InflationTrendPct": rounded(sp_model["inflationTrendPct"] if sp_model else None, 4),
            "sp500NominalGrowthPct": rounded(sp_model["nominalGrowthPct"] if sp_model else None, 4),
            "sp500MarketPremiumPct": rounded(
                (sp_value / sp_theoretical_nominal - 1.0) * 100.0
                if sp_theoretical_nominal not in (None, 0) else None, 4,
            ),
            "sp500CapRateFloored": bool(sp_model["capRateFloored"]) if sp_model else None,
            "nikkeiJpy": rounded(nikkei_jpy, 4),
            "usdjpyJpyPerUsd": rounded(fx_value, 4),
            "nikkeiUsd": rounded(nikkei_usd),
            "japanCpi": rounded(japan_cpi_value, 4),
            "nikkeiRealJpy": rounded(nikkei_real_jpy),
            "nikkeiRealUsd": rounded(nikkei_real_usd),
            "nikkeiIndexWeightPe": rounded(nikkei_index_pe.get(key), 4),
            "nikkeiIndexEps": rounded(nikkei_index_eps.get(key)),
            "nikkeiPeObservationDate": nikkei_pe_dates.get(key),
            "nikkeiEarningsPower": rounded(nikkei_earnings_power),
            "nikkeiTheoreticalJpy": rounded(nikkei_theoretical_jpy),
            "nikkeiTheoreticalLowJpy": rounded(nikkei_theoretical_low),
            "nikkeiTheoreticalHighJpy": rounded(nikkei_theoretical_high),
            "nikkeiLatestEarnings": rounded(nikkei_latest_earnings),
            "nikkeiLatestEarningsDate": month_date(nikkei_latest_earnings_date) if nikkei_latest_earnings_date else None,
            "nikkeiTheoreticalAtLatestEarningsJpy": rounded(nikkei_theoretical_latest_earnings),
            "nikkeiTheoreticalUsd": rounded(nikkei_theoretical_usd),
            "nikkeiFairPe": rounded(nikkei_model["fairPe"] if nikkei_model else None, 6),
            "nikkeiRiskFreePct": rounded(nikkei_model["riskFreePct"] if nikkei_model else None, 4),
            "nikkeiErpPct": rounded(nikkei_model["erpPct"] if nikkei_model else None, 4),
            "nikkeiCreditSpreadPct": rounded(nikkei_model["creditSpreadPct"] if nikkei_model else None, 4),
            "nikkeiCreditStressPct": rounded(nikkei_model["creditStressPct"] if nikkei_model else None, 4),
            "nikkeiInflationTrendPct": rounded(nikkei_model["inflationTrendPct"] if nikkei_model else None, 4),
            "nikkeiNominalGrowthPct": rounded(nikkei_model["nominalGrowthPct"] if nikkei_model else None, 4),
            "nikkeiMarketPremiumPct": rounded(
                (nikkei_jpy / nikkei_theoretical_jpy - 1.0) * 100.0
                if nikkei_theoretical_jpy not in (None, 0) else None, 4,
            ),
            "nikkeiCapRateFloored": bool(nikkei_model["capRateFloored"]) if nikkei_model else None,
        })

    series_base_dates = {
        "sp500Nominal": normalize_rows(rows, "sp500Nominal", "sp500NominalNormalized"),
        "sp500Real": normalize_rows(rows, "sp500Real", "sp500RealNormalized"),
        "sp500TheoreticalReal": normalize_against_anchor(
            rows, "sp500TheoreticalReal", "sp500Real", "sp500TheoreticalRealNormalized"
        ),
        "nikkeiUsd": normalize_rows(rows, "nikkeiUsd", "nikkeiUsdNormalized"),
        "nikkeiRealUsd": normalize_rows(rows, "nikkeiRealUsd", "nikkeiRealUsdNormalized"),
        "nikkeiTheoreticalUsd": normalize_against_anchor(
            rows, "nikkeiTheoreticalUsd", "nikkeiUsd", "nikkeiTheoreticalUsdNormalized"
        ),
    }

    def model_metadata(market: str) -> dict[str, Any]:
        if market == "sp500":
            field, market_field, low_field, high_field = (
                "sp500TheoreticalNominal", "sp500Nominal", "sp500TheoreticalLow", "sp500TheoreticalHigh"
            )
            earnings_field, fair_pe_field, premium_field = (
                "sp500EarningsPower", "sp500FairPe", "sp500MarketPremiumPct"
            )
            input_date_field = "sp500EarningsAvailableThroughYear"
            latest_earnings_field = "sp500LatestEarnings"
            latest_earnings_value_field = "sp500TheoreticalAtLatestEarnings"
            latest_earnings_date_field = "sp500EarningsAvailableThroughYear"
        else:
            field, market_field, low_field, high_field = (
                "nikkeiTheoreticalJpy", "nikkeiJpy", "nikkeiTheoreticalLowJpy", "nikkeiTheoreticalHighJpy"
            )
            earnings_field, fair_pe_field, premium_field = (
                "nikkeiEarningsPower", "nikkeiFairPe", "nikkeiMarketPremiumPct"
            )
            input_date_field = "nikkeiPeObservationDate"
            latest_earnings_field = "nikkeiLatestEarnings"
            latest_earnings_value_field = "nikkeiTheoreticalAtLatestEarningsJpy"
            latest_earnings_date_field = "nikkeiLatestEarningsDate"
        available = [row for row in rows if row.get(field) is not None]
        latest = available[-1] if available else None
        return {
            "status": "available" if latest else "unavailable",
            "methodId": "capitalized-normalized-earnings-v1",
            "methodLabel": "5年平準化EPSの利益還元モデル",
            "startDate": available[0]["date"] if available else None,
            "latestDate": latest["date"] if latest else None,
            "latestInputDate": latest.get(input_date_field) if latest else None,
            "latest": {
                "market": latest.get(market_field) if latest else None,
                "central": latest.get(field) if latest else None,
                "low": latest.get(low_field) if latest else None,
                "high": latest.get(high_field) if latest else None,
                "earningsPower": latest.get(earnings_field) if latest else None,
                "fairPe": latest.get(fair_pe_field) if latest else None,
                "marketPremiumPct": latest.get(premium_field) if latest else None,
                "latestEarnings": latest.get(latest_earnings_field) if latest else None,
                "latestEarningsValue": latest.get(latest_earnings_value_field) if latest else None,
                "latestEarningsDate": latest.get(latest_earnings_date_field) if latest else None,
            },
            "assumptions": {
                "baseEquityRiskPremiumPct": MODEL_ERP_PCT,
                "realGrowthPct": MODEL_REAL_GROWTH_PCT[market],
                "creditStress": "max(0, Moody's Baa yield - Aaa yield - 1.00%)",
                "minimumCapitalizationRatePct": MODEL_MIN_CAP_RATE_PCT,
                "sensitivity": MODEL_SENSITIVITY,
            },
        }

    generated = datetime.now(timezone.utc)
    errors.extend(entry["warning"] for entry in fetcher.entries if entry.get("warning"))
    errors = list(dict.fromkeys(error for error in errors if error))
    sp_model_meta = model_metadata("sp500")
    nikkei_model_meta = model_metadata("nikkei225")
    payload = {
        "schemaVersion": 1,
        "generatedAtUtc": generated.isoformat(),
        "generatedAtJst": generated.astimezone(JST).isoformat(),
        "title": "S&P 500・日経平均の市場価格と推計理論価値を比較する統合チャート",
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
        "theoreticalModels": {"sp500": sp_model_meta, "nikkei225": nikkei_model_meta},
        "valuationCoverage": {"sp500": sp_coverage, "nikkei225": nikkei_coverage},
        "providerAdapters": {
            "MarketIndexProvider": [sp_source, nikkei_source],
            "ExchangeRateProvider": fx_source,
            "CPIProvider": [us_cpi_source, japan_cpi_source],
            "RateProvider": [gs10_source, aaa_source, baa_source, jgb_source],
            "EarningsProvider": [sp_earnings_source, nikkei_per_source],
            "ValuationProvider": [sp_coverage, nikkei_coverage],
        },
        "crises": [
            {"id": "japan-bubble", "label": "バブル崩壊", "startDate": "1990-01-01", "endDate": "1992-08-31", "color": "rgba(245, 158, 11, 0.12)", "description": "日本の資産価格バブル崩壊を示す代表期間"},
            {"id": "dotcom", "label": "ITバブル崩壊", "startDate": "2000-03-01", "endDate": "2002-10-31", "color": "rgba(220, 38, 38, 0.10)", "description": "IT株のピーク後から主要株価指数の底までの代表期間"},
            {"id": "gfc", "label": "リーマンショック", "startDate": "2008-09-01", "endDate": "2009-03-31", "color": "rgba(124, 58, 237, 0.10)", "description": "世界金融危機が急性化した代表期間"},
            {"id": "covid", "label": "コロナショック", "startDate": "2020-02-01", "endDate": "2020-04-30", "color": "rgba(13, 148, 136, 0.10)", "description": "新型コロナ流行初期の急落を示す代表期間"},
        ],
        "formulas": {
            "normalization": "series_value_t / corresponding_market_value_at_1985_base * 100",
            "sp500Real": "sp500_nominal_t * us_cpi_reference / us_cpi_t",
            "nikkeiUsd": "nikkei_jpy_t / JPY_PER_USD_t",
            "nikkeiRealUsd": "nikkei_jpy_t * japan_cpi_reference / japan_cpi_t / JPY_PER_USD_t",
            "latestEarningsReference": "latest CPI-restated EPS * central fair P/E (not a forecast)",
            "earningsPower": "median(last 5 available years or 60 months of EPS, restated to month-t CPI)",
            "capitalizationRate": "max(2.50%, risk_free_10y + 4.50% ERP + max(0, Baa-Aaa-1.00%) - nominal_growth)",
            "theoreticalNominal": "normalized_earnings_power / capitalization_rate",
            "sp500TheoreticalReal": "sp500_theoretical_nominal_t * us_cpi_reference / us_cpi_t",
            "nikkeiTheoreticalUsd": "nikkei_theoretical_jpy_t / JPY_PER_USD_t",
        },
        "sources": [
            sp_source, nikkei_source, fx_source, us_cpi_source, japan_cpi_source,
            gs10_source, aaa_source, baa_source, jgb_source, sp_earnings_source, nikkei_per_source,
        ],
        "cache": {
            "ttlSeconds": fetcher.ttl_seconds,
            "entries": fetcher.entries,
            "fallbackRule": "Keep the previous successful raw cache when a live request fails",
        },
        "errors": errors,
        "limitations": [
            "The latest-earnings reference applies the same fair P/E to the latest available EPS; it is not the central estimate or a profit forecast.",
            "This is a top-down capitalized-earnings proxy, not a licensed constituent-by-constituent DCF or an official index.",
            "The 4.50% equity-risk premium, real-growth rates, credit-stress adjustment and 2.50% capitalization-rate floor are model assumptions; the low-high range must be read with the center value.",
            "S&P annual earnings are first used from May of the following year. Nikkei EPS is derived from Nikkei's official index-weight P/E and the monthly index close.",
            "The chart lines compare changes and use the same market anchor within each market. Read the cards for the absolute fair-value gap.",
            "Exact historical constituent DCF remains unavailable until licensed point-in-time membership and fundamentals reach 80% index-weight coverage.",
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
