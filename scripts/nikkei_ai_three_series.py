#!/usr/bin/env python3
"""Build the dedicated Nikkei/AI-overheat three-series comparison package.

The current repository does not contain the historical Nikkei constituent,
price-adjustment-factor, divisor, and peer-price inputs required to calculate
a non-official exclusion index honestly. The generator therefore fails closed:
until both user-specified targets and the required historical input package are
available, synthetic series remain null. This prevents the page from presenting
an uncomputed counterfactual as if it were a three-series comparison.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "nikkei-ai-overheat-config.json"
OUTPUT_PATH = ROOT / "data" / "nikkei-ai-three-series.json"
JST = ZoneInfo("Asia/Tokyo")
OFFICIAL_DAILY_URL = (
    "https://indexes.nikkei.co.jp/nkave/historical/"
    "nikkei_stock_average_daily_en.csv"
)
OFFICIAL_MONTHLY_URL = (
    "https://indexes.nikkei.co.jp/nkave/historical/"
    "nikkei_stock_average_monthly_en.csv"
)
OFFICIAL_DAILY_PAGE_URL = (
    "https://indexes.nikkei.co.jp/en/nkave/archives/data?list=daily"
)
YAHOO_NIKKEI_HISTORY_URL = "https://finance.yahoo.com/quote/%5EN225/history"
USER_AGENT = "mxe050-ai-bubble-monitor/1.0 (https://github.com/mxe050)"


class ConfigurationError(ValueError):
    """Configuration is inconsistent or would create an undisclosed selection."""


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_number(value: Any) -> float | None:
    return finite(re.sub(r"[^0-9.+-]", "", str(value or "")))


def pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old in (None, 0):
        return None
    return (new / old - 1.0) * 100.0


def request(url: str, *, timeout: int = 30) -> bytes:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/csv,application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.8",
    }
    request_object = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request_object, timeout=timeout) as response:
        return response.read()


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return validate_config(payload)


def validate_config(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ConfigurationError("configuration must be an object")
    required = {
        "method_version",
        "lookback_years",
        "normalization_method",
        "normalization_buffer",
        "exclusion_mode",
        "bubble_suspect",
        "explicit_keep",
    }
    missing = required - set(payload)
    if missing:
        raise ConfigurationError("missing configuration keys: " + ", ".join(sorted(missing)))
    if payload["method_version"] != "1.0":
        raise ConfigurationError("unsupported method_version")
    lookback_years = payload["lookback_years"]
    if isinstance(lookback_years, bool) or not isinstance(lookback_years, int) or lookback_years != 10:
        raise ConfigurationError("lookback_years must be the integer 10")
    if payload["normalization_method"] != "same-sector-peer-price-path":
        raise ConfigurationError("unsupported normalization method")
    raw_buffer = payload["normalization_buffer"]
    if isinstance(raw_buffer, bool) or not isinstance(raw_buffer, (int, float)):
        raise ConfigurationError("normalization_buffer must be a finite number")
    buffer = finite(raw_buffer)
    if buffer is None or buffer <= 0:
        raise ConfigurationError("normalization_buffer must be positive")
    if payload["exclusion_mode"] not in {
        "retrospective-fixed-list",
        "effective-date",
    }:
        raise ConfigurationError("unsupported exclusion_mode")
    for name in ("bubble_suspect", "explicit_keep"):
        if not isinstance(payload[name], list):
            raise ConfigurationError(f"{name} must be a list")
    bubble_codes: set[str] = set()
    keep_codes: set[str] = set()
    for name, bucket, target in (
        ("bubble_suspect", payload["bubble_suspect"], bubble_codes),
        ("explicit_keep", payload["explicit_keep"], keep_codes),
    ):
        for index, row in enumerate(bucket):
            if not isinstance(row, dict):
                raise ConfigurationError(f"{name}[{index}] must be an object")
            raw_code = row.get("code")
            if not isinstance(raw_code, str):
                raise ConfigurationError(f"{name}[{index}].code must be a 4-digit string")
            code = raw_code.strip()
            if not re.fullmatch(r"\d{4}", code):
                raise ConfigurationError(f"{name}[{index}].code must be a 4-digit code")
            if code in target:
                raise ConfigurationError(f"{name} contains duplicate code {code}")
            target.add(code)
            if not str(row.get("name") or "").strip():
                raise ConfigurationError(f"{name}[{index}].name is required")
            if name == "bubble_suspect" and not str(row.get("reason") or "").strip():
                raise ConfigurationError(
                    f"{name}[{index}].reason is required for an exclusion target"
                )
            effective_from = row.get("effective_from")
            if effective_from not in (None, ""):
                if not isinstance(effective_from, str):
                    raise ConfigurationError(f"{name}[{index}].effective_from must be YYYY-MM-DD")
                try:
                    date.fromisoformat(effective_from)
                except ValueError as exc:
                    raise ConfigurationError(
                        f"{name}[{index}].effective_from must be YYYY-MM-DD"
                    ) from exc
            elif name == "bubble_suspect" and payload["exclusion_mode"] == "effective-date":
                raise ConfigurationError(
                    f"{name}[{index}].effective_from is required for effective-date mode"
                )
    overlap = bubble_codes & keep_codes
    if overlap:
        raise ConfigurationError(
            "explicit_keep and bubble_suspect overlap: " + ", ".join(sorted(overlap))
        )
    if "7203" not in keep_codes:
        raise ConfigurationError("7203 must remain in explicit_keep")
    return {
        **payload,
        "lookback_years": 10,
        "normalization_buffer": buffer,
    }


def fetch_official_csv(url: str) -> list[dict[str, Any]]:
    text = request(url).decode("cp932", errors="replace")
    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(text)):
        raw_date = str(
            row.get("Date of Data") or row.get("\ufeffDate of Data") or ""
        ).strip()
        try:
            observed = datetime.strptime(raw_date, "%Y/%m/%d").date()
        except ValueError:
            continue
        close = parse_number(row.get("Close"))
        if close is not None and close > 0:
            rows.append({"date": observed, "close": close})
    rows.sort(key=lambda row: row["date"])
    if len(rows) < 2:
        raise RuntimeError(f"official Nikkei CSV has too few rows: {url}")
    return rows


def fetch_yahoo_daily() -> list[dict[str, Any]]:
    encoded = urllib.parse.quote("^N225", safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
        "?range=10y&interval=1d&events=div%2Csplits"
    )
    payload = json.loads(request(url).decode("utf-8"))
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    rows: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        close = finite(closes[index]) if index < len(closes) else None
        if close is None:
            continue
        observed = datetime.fromtimestamp(int(timestamp), timezone.utc).astimezone(JST).date()
        rows.append({"date": observed, "close": close})
    rows.sort(key=lambda row: row["date"])
    if len(rows) < 1000:
        raise RuntimeError("Yahoo raw Nikkei close history is shorter than 10 years")
    return rows


def beginning_of_lookback(end_date: date, years: int) -> date:
    try:
        return end_date.replace(year=end_date.year - years)
    except ValueError:
        return end_date.replace(year=end_date.year - years, day=28)


def weekly_sample(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[tuple[int, int], dict[str, Any]] = {}
    for row in sorted(rows, key=lambda value: value["date"]):
        iso_year, iso_week, _ = row["date"].isocalendar()
        selected[(iso_year, iso_week)] = row
    return [selected[key] for key in sorted(selected)]


def normalize_price(actual: float, cap: float | None) -> float:
    """Never lift a price: only remove the part above a peer-derived cap."""

    return actual if cap is None else min(actual, cap)


def json_is_finite(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, list):
        return all(json_is_finite(item) for item in value)
    if isinstance(value, dict):
        return all(json_is_finite(item) for item in value.values())
    return False


def compare_monthly_sources(
    merged: dict[date, float],
    official_monthly: list[dict[str, Any]],
    start_date: date,
) -> dict[str, Any]:
    errors: list[float] = []
    missing_months: list[str] = []
    month_end: dict[tuple[int, int], tuple[date, float]] = {}
    for observed, close in sorted(merged.items()):
        month_end[(observed.year, observed.month)] = (observed, close)
    for row in official_monthly:
        observed = row["date"]
        if observed < start_date:
            continue
        # The official monthly CSV labels a month with its first calendar day,
        # while its Close is that month's final trading-session close.
        matched = month_end.get((observed.year, observed.month))
        if matched is None:
            missing_months.append(observed.isoformat())
            continue
        _matched_date, current = matched
        errors.append(abs(current - row["close"]))
    return {
        "matched_months": len(errors),
        "missing_months": missing_months,
        "max_abs_error_jpy": max(errors) if errors else None,
        "within_0_02_jpy": bool(errors) and max(errors) <= 0.02,
        "matching_method": "official-month-label-to-last-trading-close",
    }


def make_target_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in config["bubble_suspect"]:
        rows.append({
            "code": str(target["code"]),
            "name": str(target["name"]),
            "effective_from": target.get("effective_from"),
            "reason": str(target.get("reason") or "ユーザー指定"),
            "evidence_note": str(target.get("evidence_note") or ""),
            "peer_method": "未確認",
            "peer_count": None,
            "current_nikkei_weight_pct": None,
            "actual_return_pct": None,
            "peer_path_return_pct": None,
            "removed_excess_return_percentage_points": None,
            "data_status": "歴史的構成銘柄・PAF・比較群の日次データ未接続",
        })
    return rows


def build_payload(
    config: dict[str, Any],
    *,
    yahoo_rows: list[dict[str, Any]],
    official_daily: list[dict[str, Any]],
    official_monthly: list[dict[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(JST)
    official_daily_map = {row["date"]: row["close"] for row in official_daily}
    official_monthly_map = {row["date"]: row["close"] for row in official_monthly}
    end_date = max(official_daily_map)
    start_floor = beginning_of_lookback(end_date, int(config["lookback_years"]))

    merged = {
        row["date"]: row["close"]
        for row in yahoo_rows
        if start_floor <= row["date"] <= end_date
    }
    # The official daily file is authoritative where it is available, including
    # the current final session that can lag in Yahoo's 1-day chart response.
    for observed, close in official_daily_map.items():
        if start_floor <= observed <= end_date:
            merged[observed] = close
    ordered = [
        {"date": observed, "close": close}
        for observed, close in sorted(merged.items())
        if close is not None
    ]
    if len(ordered) < 1000:
        raise RuntimeError("combined Nikkei history is insufficient for a 10-year comparison")
    start_date = ordered[0]["date"]
    monthly_quality = compare_monthly_sources(merged, official_monthly, start_date)
    if monthly_quality["matched_months"] < 100:
        raise RuntimeError("10-year Yahoo/official monthly cross-check is incomplete")

    targets = make_target_rows(config)
    targets_configured = bool(targets)
    chart_rows: list[dict[str, Any]] = []
    base_close = ordered[0]["close"]
    display_rows = weekly_sample(ordered)
    if not display_rows or display_rows[0]["date"] != ordered[0]["date"]:
        display_rows.insert(0, ordered[0])
    for row in display_rows:
        actual = 100.0 * row["close"] / base_close
        # Do not manufacture an adjustment path. A null means the required
        # counterfactual inputs are not available, not that its effect is zero.
        normalized = None
        excluded = None
        actual_minus_normalized = None
        normalized_minus_excluded = None
        chart_rows.append({
            "date": row["date"].isoformat(),
            "nikkei_actual": round(actual, 6),
            "ai_overheat_normalized": (
                round(normalized, 6) if normalized is not None else None
            ),
            "ai_overheat_excluded": round(excluded, 6) if excluded is not None else None,
            "nikkei_close": round(row["close"], 2),
            "actual_minus_normalized": (
                round(actual_minus_normalized, 6)
                if actual_minus_normalized is not None
                else None
            ),
            "normalized_minus_excluded": (
                round(normalized_minus_excluded, 6)
                if normalized_minus_excluded is not None
                else None
            ),
        })
    if not chart_rows:
        raise RuntimeError("no display rows were created")

    actual_return = chart_rows[-1]["nikkei_actual"] - 100.0
    normalized_return = (
        chart_rows[-1]["ai_overheat_normalized"] - 100.0
        if chart_rows[-1]["ai_overheat_normalized"] is not None
        else None
    )
    excluded_return = (
        chart_rows[-1]["ai_overheat_excluded"] - 100.0
        if chart_rows[-1]["ai_overheat_excluded"] is not None
        else None
    )
    missing_items = [
        "時点別の日経平均構成銘柄",
        "時点別の価格調整係数（PAF）・除数",
        "対象銘柄ごとの日次価格と同業比較群",
    ]
    if targets_configured:
        warnings = [
            "ユーザー指定対象はありますが、歴史的構成・PAF・日次比較群が未接続のため、"
            "標準化・除外試算は計算していません。"
        ]
        method_label = "対象設定済み・必要な履歴データ未接続のため比較未算出"
        comparison_status = "comparison-uncomputed-missing-historical-inputs"
    else:
        missing_items.insert(0, "ユーザー指定のAIバブル疑義銘柄")
        warnings = [
            "AIバブル疑義銘柄が未設定です。AI関連という理由だけでは自動的に除外していません。",
            "対象未設定のため、標準化試算・除外試算は計算していません。実績と同値の線を重ねて比較済みのように表示しません。",
            "歴史的構成銘柄・PAF・除数を取得できないため、対象を追加しても不足データのまま合成系列を作りません。",
        ]
        method_label = "対象銘柄未設定のため、反実仮想の比較は未算出"
        comparison_status = "actual-only-comparison-uncomputed-no-targets"
    payload = {
        "meta": {
            "title": "日経平均・AI過熱寄与標準化・AI過熱銘柄除外の10年比較",
            "generated_at": now.astimezone(JST).replace(microsecond=0).isoformat(),
            "market_date": end_date.isoformat(),
            "start_date": start_date.isoformat(),
            "end_date": chart_rows[-1]["date"],
            "base_value": 100,
            "calculation_frequency": "daily",
            "display_frequency": "weekly",
            "dividends_included": False,
            "price_field": "Close（配当調整済みAdj Closeは使用しない）",
            "normalization_method": config["normalization_method"],
            "normalization_buffer": config["normalization_buffer"],
            "exclusion_mode": config["exclusion_mode"],
            "synthetic_series_are_official": False,
            "method_label": method_label,
            "comparison_status": comparison_status,
            "official_daily_available_from": min(official_daily_map).isoformat(),
            "official_monthly_available_from": min(official_monthly_map).isoformat(),
        },
        "summary": {
            "actual_return_pct": round(actual_return, 6),
            "normalized_return_pct": round(normalized_return, 6) if normalized_return is not None else None,
            "excluded_return_pct": round(excluded_return, 6) if excluded_return is not None else None,
            "ai_excess_contribution_percentage_points": (
                round(actual_return - normalized_return, 6)
                if normalized_return is not None
                else None
            ),
            "retained_normal_contribution_percentage_points": (
                round(normalized_return - excluded_return, 6)
                if normalized_return is not None and excluded_return is not None
                else None
            ),
            "bubble_suspect_count": len(targets),
            "current_combined_weight_pct": None,
            "peak_combined_weight_pct": None,
        },
        "quality": {
            "constituent_coverage_pct": None,
            "price_adjustment_coverage_pct": None,
            "daily_return_error_median_bps": None,
            "daily_return_error_p95_bps": None,
            "cumulative_endpoint_error_pct": None,
            "hindsight_bias": bool(targets_configured and config["exclusion_mode"] == "retrospective-fixed-list"),
            "survivorship_bias": False,
            "missing_items": missing_items,
            "monthly_crosscheck": monthly_quality,
            "data_state": comparison_status,
        },
        "bubble_suspect": targets,
        "explicit_keep": config["explicit_keep"],
        "series": chart_rows,
        "warnings": warnings,
        "sources": [
            {
                "label": "日経公式・日次終値",
                "url": OFFICIAL_DAILY_PAGE_URL,
                "used_for": "2023年以降の公式日次終値と直近日の上書き",
            },
            {
                "label": "日経公式・月次終値CSV",
                "url": OFFICIAL_MONTHLY_URL,
                "used_for": "10年履歴の月次クロスチェック",
            },
            {
                "label": "Yahoo Finance ^N225",
                "url": YAHOO_NIKKEI_HISTORY_URL,
                "used_for": "10年の日付付きClose（Adj Closeは不使用）",
            },
            {
                "label": "対象銘柄設定",
                "url": "https://github.com/mxe050/ai-bubble-collapse-monitor/blob/main/config/nikkei-ai-overheat-stocks.json",
                "used_for": "ユーザー指定対象とexplicit_keep",
            },
        ],
    }
    if not json_is_finite(payload):
        raise RuntimeError("payload contains NaN or Infinity")
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        temporary_path = Path(handle.name)
    temporary_path.replace(path)


def write_nikkei_ai_three_series(
    config_path: Path = CONFIG_PATH,
    output_path: Path = OUTPUT_PATH,
) -> dict[str, Any]:
    from nikkei_ai_public_proxy import write_nikkei_ai_three_series as write_public_proxy
    return write_public_proxy(config_path=config_path, output_path=output_path)
    config = load_config(config_path)
    payload = build_payload(
        config,
        yahoo_rows=fetch_yahoo_daily(),
        official_daily=fetch_official_csv(OFFICIAL_DAILY_URL),
        official_monthly=fetch_official_csv(OFFICIAL_MONTHLY_URL),
    )
    atomic_write_json(output_path, payload)
    return payload


def main() -> int:
    try:
        payload = write_nikkei_ai_three_series()
    except Exception as exc:
        print(f"Nikkei AI three-series generation failed: {exc}", file=sys.stderr)
        return 1
    print(
        "Wrote "
        f"{OUTPUT_PATH} with {len(payload['series'])} weekly rows through "
        f"{payload['meta']['market_date']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
