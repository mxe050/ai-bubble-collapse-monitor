#!/usr/bin/env python3
"""Strict, network-free audit for ``data/live-intelligence.json``.

The producer intentionally mixes fast market observations, official releases,
news discovery, and explicitly limited social coverage.  This validator keeps
those evidence classes separate and independently rechecks the arithmetic and
state invariants that can be reconstructed from the saved package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import urllib.parse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "live-intelligence.json"
JST = timezone(timedelta(hours=9))
BRIEFING_ITEM_LIMIT = 16

TOPIC_LABELS = {
    "fx-rates": "為替・金利",
    "ai-bubble": "AIバブル",
    "japan-stocks": "日本株",
    "us-stocks": "米国株",
    "policy": "政策・政府",
}

EXPECTED_INSTRUMENTS = {
    "NIKKEI_CASH": {
        "symbol": "^N225",
        "label": "日経平均（現物）",
        "shortLabel": "日経現物",
        "group": "japan",
        "currency": "JPY",
        "role": "cash-reference",
    },
    "NIKKEI_FUTURES_YEN": {
        "symbol": "NIY=F",
        "label": "CME日経225先物（円建て）",
        "shortLabel": "CME日経・円",
        "group": "japan",
        "currency": "JPY",
        "role": "primary-futures",
    },
    "NIKKEI_FUTURES_USD": {
        "symbol": "NKD=F",
        "label": "CME日経225先物（ドル建て）",
        "shortLabel": "CME日経・ドル",
        "group": "japan",
        "currency": "USD",
        "role": "secondary-futures",
    },
    "SP500_FUTURES": {
        "symbol": "ES=F",
        "label": "E-mini S&P 500先物",
        "shortLabel": "S&P先物",
        "group": "us",
        "currency": "USD",
        "role": "risk-tone",
    },
    "NASDAQ100_FUTURES": {
        "symbol": "NQ=F",
        "label": "E-mini Nasdaq 100先物",
        "shortLabel": "Nasdaq先物",
        "group": "us",
        "currency": "USD",
        "role": "ai-risk-tone",
    },
    "DOW_FUTURES": {
        "symbol": "YM=F",
        "label": "E-mini Dow先物",
        "shortLabel": "Dow先物",
        "group": "us",
        "currency": "USD",
        "role": "risk-tone",
    },
    "RUSSELL2000_FUTURES": {
        "symbol": "RTY=F",
        "label": "E-mini Russell 2000先物",
        "shortLabel": "Russell先物",
        "group": "us",
        "currency": "USD",
        "role": "breadth-tone",
    },
    "USDJPY": {
        "symbol": "JPY=X",
        "label": "ドル円",
        "shortLabel": "USD/JPY",
        "group": "fx",
        "currency": "JPY",
        "role": "fx",
    },
    "VIX": {
        "symbol": "^VIX",
        "label": "VIX",
        "shortLabel": "VIX",
        "group": "risk",
        "currency": "INDEX",
        "role": "volatility",
    },
    "US10Y": {
        "symbol": "^TNX",
        "label": "米10年国債利回り",
        "shortLabel": "米10年金利",
        "group": "rates",
        "currency": "PCT",
        "role": "rates",
    },
}

BULL_TERMS = (
    "rally",
    "surge",
    "gain",
    "record high",
    "beat estimates",
    "strong growth",
    "soft landing",
    "rate cut",
    "easing",
    "bullish",
    "upside",
    "rebound",
    "optimistic",
    "profit growth",
    "収益化",
    "増益",
    "上昇",
    "反発",
    "強気",
    "追い風",
)
BEAR_TERMS = (
    "selloff",
    "plunge",
    "slump",
    "drop",
    "crash",
    "bubble",
    "recession",
    "warning",
    "weak",
    "downside",
    "bearish",
    "rate hike",
    "inflation",
    "tariff",
    "credit stress",
    "cash burn",
    "expenses",
    "cost burden",
    "spending burden",
    "valuation concern",
    "cash flow pressure",
    "圧迫",
    "警戒",
    "負担",
    "下落",
    "懸念",
    "弱気",
    "逆風",
)

SOURCE_STATUS_VALUES = {"ok", "limited", "not-configured", "failed"}
CHANNEL_STATUS_VALUES = {"ok", "limited", "not-configured", "failed"}
SOURCE_KINDS = {
    "official-us",
    "official-japan",
    "news",
    "news-wire",
    "x-api",
    "x-index",
    "linkedin",
    "bluesky",
    "truth-social",
    "truth-social-archive",
}
VERIFICATION_VALUES = {
    "primary",
    "reported",
    "reported-unconfirmed",
    "unverified",
    "public-indexed",
    "primary-statement",
    "archived-statement",
}
STANCE_VALUES = {"bullish", "bearish", "mixed", "neutral"}
CURATED_X_HANDLES = {
    "federalreserve",
    "ustreasury",
    "whitehouse",
    "potus",
    "realdonaldtrump",
    "elerianm",
    "lizannsonders",
    "jasonfurman",
    "claudia_sahm",
    "biancoresearch",
    "charliebilello",
}


class ValidationError(AssertionError):
    """Raised when the live package violates its published contract."""


def require(condition: Any, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def require_dict(value: Any, context: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{context} must be an object")
    return value


def require_list(value: Any, context: str) -> list[Any]:
    require(isinstance(value, list), f"{context} must be an array")
    return value


def require_string(value: Any, context: str, *, allow_empty: bool = False) -> str:
    require(isinstance(value, str), f"{context} must be a string")
    if not allow_empty:
        require(bool(value.strip()), f"{context} must not be empty")
    return value


def require_int(value: Any, context: str, *, low: int | None = None, high: int | None = None) -> int:
    require(isinstance(value, int) and not isinstance(value, bool), f"{context} must be an integer")
    if low is not None:
        require(value >= low, f"{context} must be >= {low}")
    if high is not None:
        require(value <= high, f"{context} must be <= {high}")
    return value


def number(value: Any, context: str, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    require(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)),
        f"{context} must be a finite number" + (" or null" if nullable else ""),
    )
    return float(value)


def require_keys(
    value: dict[str, Any],
    required: Iterable[str],
    context: str,
    *,
    optional: Iterable[str] = (),
) -> None:
    required_set = set(required)
    optional_set = set(optional)
    keys = set(value)
    missing = sorted(required_set - keys)
    extra = sorted(keys - required_set - optional_set)
    require(not missing, f"{context} is missing keys: {missing}")
    require(not extra, f"{context} has unexpected keys: {extra}")


def parse_timestamp(
    value: Any,
    context: str,
    *,
    expected_offset: timedelta | None = None,
) -> datetime:
    text = require_string(value, context)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{context} is not an ISO-8601 timestamp: {text}") from exc
    require(parsed.tzinfo is not None, f"{context} must include a UTC offset")
    if expected_offset is not None:
        require(parsed.utcoffset() == expected_offset, f"{context} has the wrong UTC offset")
    return parsed


def same_instant(left: datetime, right: datetime, *, seconds: float = 0.001) -> bool:
    return abs((left.astimezone(timezone.utc) - right.astimezone(timezone.utc)).total_seconds()) <= seconds


def close_enough(
    left: float | int | None,
    right: float | int | None,
    *,
    absolute: float = 1e-8,
    relative: float = 1e-8,
) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return math.isclose(float(left), float(right), abs_tol=absolute, rel_tol=relative)


def pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old in (None, 0):
        return None
    return (new / old - 1.0) * 100.0


def require_https_url(value: Any, context: str, *, hosts: set[str] | None = None) -> str:
    text = require_string(value, context)
    parsed = urllib.parse.urlparse(text)
    require(parsed.scheme == "https", f"{context} must use https")
    require(bool(parsed.hostname), f"{context} must contain a host")
    require(parsed.username is None and parsed.password is None, f"{context} must not contain credentials")
    require(not re.search(r"\s", text), f"{context} must not contain whitespace")
    if hosts is not None:
        host = (parsed.hostname or "").lower()
        require(
            any(host == allowed or host.endswith("." + allowed) for allowed in hosts),
            f"{context} has an unapproved host: {host}",
        )
    return text


def normalize_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    query = urllib.parse.parse_qs(parsed.query)
    for key in ("url", "u", "target"):
        candidate = query.get(key, [None])[0]
        if candidate and candidate.startswith(("http://", "https://")):
            return urllib.parse.unquote(candidate)
    return urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc.lower(), parsed.path, "", "", "")
    )


def contains_term(text: str, term: str) -> bool:
    """Mirror the producer's English word-boundary and Japanese substring rule."""

    lowered_term = term.lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9 .&/+_-]*", lowered_term):
        escaped = re.escape(lowered_term)
        optional_plural = r"(?:s|es)?" if re.fullmatch(r"[a-z]+", lowered_term) else ""
        return re.search(
            rf"(?<![a-z0-9]){escaped}{optional_plural}(?![a-z0-9])",
            text,
            re.I,
        ) is not None
    return lowered_term in text.lower()


def expected_item_id(url: str, title: str) -> str:
    digest = hashlib.sha1((normalize_url(url) + "\n" + title).encode("utf-8")).hexdigest()
    return "live-" + digest[:14]


def expected_stance(title: str, summary: str) -> str:
    lowered = (title + " " + summary).lower()
    bull = sum(1 for term in BULL_TERMS if contains_term(lowered, term))
    bear = sum(1 for term in BEAR_TERMS if contains_term(lowered, term))
    if bull and bear:
        return "mixed"
    if bull:
        return "bullish"
    if bear:
        return "bearish"
    return "neutral"


def validate_root_times(data: dict[str, Any]) -> tuple[datetime, datetime]:
    generated_utc = parse_timestamp(
        data.get("generatedAtUtc"), "generatedAtUtc", expected_offset=timedelta(0)
    )
    generated_jst = parse_timestamp(
        data.get("generatedAtJst"), "generatedAtJst", expected_offset=timedelta(hours=9)
    )
    require(same_instant(generated_utc, generated_jst), "generatedAtUtc/Jst describe different instants")
    now = datetime.now(timezone.utc)
    require(generated_utc <= now + timedelta(minutes=10), "live package is future-dated")
    require(now - generated_utc <= timedelta(hours=48), "live package is more than 48 hours old")
    if "fallbackAppliedAtUtc" in data:
        fallback_at = parse_timestamp(
            data["fallbackAppliedAtUtc"], "fallbackAppliedAtUtc", expected_offset=timedelta(0)
        )
        require(
            abs((fallback_at - generated_utc).total_seconds()) <= 1,
            "fallbackAppliedAtUtc must match package generation time",
        )
    return generated_utc, generated_jst


def validate_refresh_policy(data: dict[str, Any]) -> None:
    policy = require_dict(data.get("refreshPolicy"), "refreshPolicy")
    require_keys(
        policy,
        {"targetIntervalMinutes", "delivery", "buttonBehavior", "warning"},
        "refreshPolicy",
    )
    require_int(policy["targetIntervalMinutes"], "refreshPolicy.targetIntervalMinutes", low=1, high=60)
    for key in ("delivery", "buttonBehavior", "warning"):
        require_string(policy[key], f"refreshPolicy.{key}")
    require(
        "再読込" in policy["buttonBehavior"],
        "refreshPolicy.buttonBehavior must honestly describe snapshot reload",
    )


def validate_source_status(
    data: dict[str, Any], generated: datetime
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = require_list(data.get("sourceStatus"), "sourceStatus")
    require(rows, "sourceStatus must not be empty")
    identities: set[tuple[str, str]] = set()
    market_by_name: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(rows):
        context = f"sourceStatus[{index}]"
        row = require_dict(raw, context)
        require_keys(
            row,
            {"name", "kind", "status", "url", "retrievedAtUtc", "message"},
            context,
        )
        name = require_string(row["name"], f"{context}.name")
        kind = require_string(row["kind"], f"{context}.kind")
        status = require_string(row["status"], f"{context}.status")
        require(status in SOURCE_STATUS_VALUES, f"{context}.status is invalid: {status}")
        identity = (name, kind)
        require(identity not in identities, f"duplicate source status: {identity}")
        identities.add(identity)
        url = require_string(row["url"], f"{context}.url", allow_empty=True)
        if url:
            require_https_url(url, f"{context}.url")
        else:
            require(status == "failed", f"{context}.url may be empty only for a failed source")
        retrieved = parse_timestamp(
            row["retrievedAtUtc"], f"{context}.retrievedAtUtc", expected_offset=timedelta(0)
        )
        require(
            abs((retrieved - generated).total_seconds()) <= 2,
            f"{context}.retrievedAtUtc must match package generation",
        )
        message = require_string(row["message"], f"{context}.message")
        if status == "not-configured":
            require(
                re.search(r"未設定|未接続|APIキー", message),
                f"{context} must clearly say that the source is not configured",
            )
        if kind == "market-price":
            require(name not in market_by_name, f"duplicate market-price source: {name}")
            market_by_name[name] = row
    return rows, market_by_name


def validate_data_health(data: dict[str, Any], source_rows: list[dict[str, Any]]) -> None:
    health = require_dict(data.get("dataHealth"), "dataHealth")
    require_keys(
        health,
        {
            "status",
            "successfulSources",
            "failedSources",
            "limitedSources",
            "skippedSources",
            "carriedForwardItems",
            "message",
        },
        "dataHealth",
    )
    require(health["status"] in {"ok", "partial"}, "dataHealth.status must be ok or partial")
    successful = require_int(health["successfulSources"], "dataHealth.successfulSources", low=0)
    failed = require_int(health["failedSources"], "dataHealth.failedSources", low=0)
    limited = require_int(health["limitedSources"], "dataHealth.limitedSources", low=0)
    skipped = require_int(health["skippedSources"], "dataHealth.skippedSources", low=0)
    carried = require_int(health["carriedForwardItems"], "dataHealth.carriedForwardItems", low=0, high=BRIEFING_ITEM_LIMIT)
    expected_successful = sum(
        1 for row in source_rows if row["status"] in {"ok", "limited"}
    )
    expected_failed = sum(1 for row in source_rows if row["status"] == "failed")
    expected_limited = sum(1 for row in source_rows if row["status"] == "limited")
    expected_skipped = sum(1 for row in source_rows if row["status"] == "not-configured")
    require(successful == expected_successful, "dataHealth.successfulSources does not match sourceStatus")
    require(failed == expected_failed, "dataHealth.failedSources does not match sourceStatus")
    require(limited == expected_limited, "dataHealth.limitedSources does not match sourceStatus")
    require(skipped == expected_skipped, "dataHealth.skippedSources does not match sourceStatus")
    expected_state = "partial" if failed or limited or skipped or carried else "ok"
    require(health["status"] == expected_state, "dataHealth.status is inconsistent with failures/fallback")
    require_string(health["message"], "dataHealth.message")


def validate_move(
    value: Any,
    context: str,
    *,
    minutes: int | None,
    generated: datetime,
    spark_by_time: dict[str, float],
) -> None:
    move = require_dict(value, context)
    required = {"points", "pct", "startUtc", "endUtc"}
    if minutes is not None:
        required.add("minutes")
    require_keys(move, required, context)
    if minutes is not None:
        require_int(move["minutes"], f"{context}.minutes")
        require(move["minutes"] == minutes, f"{context}.minutes must be {minutes}")
    points = number(move["points"], f"{context}.points", nullable=True)
    percent = number(move["pct"], f"{context}.pct", nullable=True)
    timestamps = (move["startUtc"], move["endUtc"])
    if points is None or percent is None:
        require(points is None and percent is None, f"{context}.points/pct must both be null")
        require(timestamps == (None, None), f"{context} null move must have null timestamps")
        return
    start = parse_timestamp(
        move["startUtc"], f"{context}.startUtc", expected_offset=timedelta(0)
    )
    end = parse_timestamp(move["endUtc"], f"{context}.endUtc", expected_offset=timedelta(0))
    require(start <= end, f"{context} timestamps are reversed")
    if minutes is not None:
        require(
            end - start <= timedelta(minutes=minutes),
            f"{context} exceeds its {minutes}-minute window",
        )
    require(end <= generated + timedelta(minutes=10), f"{context}.endUtc is future-dated")
    require(generated - start <= timedelta(hours=31), f"{context} exceeds the 30-hour quote window")
    if minutes is None:
        require(points >= -1e-12, f"{context}.points must be nonnegative")
        require(percent >= -1e-12, f"{context}.pct must be nonnegative")
    elif points:
        require(
            math.copysign(1, points) == math.copysign(1, percent),
            f"{context}.points and pct must have the same sign",
        )
    start_text = move["startUtc"]
    end_text = move["endUtc"]
    if start_text in spark_by_time and end_text in spark_by_time:
        start_value = spark_by_time[start_text]
        end_value = spark_by_time[end_text]
        expected_points = (
            start_value - end_value if minutes is None else end_value - start_value
        )
        expected_pct = (
            (start_value - end_value) / start_value * 100
            if minutes is None
            else pct_change(end_value, start_value)
        )
        require(
            close_enough(points, expected_points, absolute=1e-7),
            f"{context}.points does not match sparkline values",
        )
        require(
            close_enough(percent, expected_pct, absolute=1e-7),
            f"{context}.pct does not match sparkline values",
        )


def validate_quote(
    key: str,
    raw: Any,
    generated: datetime,
) -> None:
    context = f"premarket.quotes.{key}"
    quote = require_dict(raw, context)
    require_keys(
        quote,
        {
            "key",
            "symbol",
            "label",
            "shortLabel",
            "group",
            "currency",
            "role",
            "value",
            "previousClose",
            "changePct",
            "changePoints",
            "sessionHigh",
            "sessionLow",
            "sessionRangePct",
            "quoteTimeUtc",
            "quoteTimeJst",
            "staleMinutes",
            "marketState",
            "exchangeName",
            "exchangeTimezone",
            "instrumentType",
            "currencyReported",
            "regularMarketVolume",
            "move5m",
            "move15m",
            "move30m",
            "peakToTrough",
            "sparkline",
            "sourceUrl",
        },
        context,
    )
    expected = EXPECTED_INSTRUMENTS[key]
    require(quote["key"] == key, f"{context}.key mismatch")
    for field, expected_value in expected.items():
        require(quote[field] == expected_value, f"{context}.{field} mismatch")
    current = number(quote["value"], f"{context}.value")
    previous = number(quote["previousClose"], f"{context}.previousClose", nullable=True)
    high = number(quote["sessionHigh"], f"{context}.sessionHigh")
    low = number(quote["sessionLow"], f"{context}.sessionLow")
    change = number(quote["changePct"], f"{context}.changePct", nullable=True)
    change_points = number(quote["changePoints"], f"{context}.changePoints", nullable=True)
    range_pct = number(quote["sessionRangePct"], f"{context}.sessionRangePct")
    require(current > 0 and high > 0 and low > 0, f"{context} prices must be positive")
    if previous is not None:
        require(previous > 0, f"{context}.previousClose must be positive")
    require(low <= current <= high, f"{context}.value must be inside sessionLow/sessionHigh")
    require(high >= low, f"{context}.sessionHigh must be >= sessionLow")
    require(
        close_enough(change, pct_change(current, previous)),
        f"{context}.changePct identity failed",
    )
    require(
        close_enough(change_points, current - previous if previous is not None else None),
        f"{context}.changePoints identity failed",
    )
    require(
        close_enough(range_pct, pct_change(high, low)),
        f"{context}.sessionRangePct identity failed",
    )
    quote_utc = parse_timestamp(
        quote["quoteTimeUtc"], f"{context}.quoteTimeUtc", expected_offset=timedelta(0)
    )
    quote_jst = parse_timestamp(
        quote["quoteTimeJst"], f"{context}.quoteTimeJst", expected_offset=timedelta(hours=9)
    )
    require(same_instant(quote_utc, quote_jst), f"{context} UTC/JST quote times differ")
    require(quote_utc <= generated + timedelta(minutes=10), f"{context} quote is future-dated")
    require(generated - quote_utc <= timedelta(days=7), f"{context} quote is older than seven days")
    stale = number(quote["staleMinutes"], f"{context}.staleMinutes")
    expected_stale = round(max(0.0, (generated - quote_utc).total_seconds() / 60.0), 1)
    require(close_enough(stale, expected_stale, absolute=0.11), f"{context}.staleMinutes mismatch")
    expected_market_state = "updating" if expected_stale <= 25 else "delayed-or-closed"
    require(
        quote["marketState"] == expected_market_state,
        f"{context}.marketState is inconsistent with staleMinutes",
    )
    for field in ("exchangeName", "exchangeTimezone", "instrumentType", "currencyReported"):
        require(
            quote[field] is None or isinstance(quote[field], str),
            f"{context}.{field} must be a string or null",
        )
    volume = number(quote["regularMarketVolume"], f"{context}.regularMarketVolume", nullable=True)
    if volume is not None:
        require(volume >= 0, f"{context}.regularMarketVolume must be nonnegative")
    require_https_url(
        quote["sourceUrl"], f"{context}.sourceUrl", hosts={"finance.yahoo.com"}
    )

    spark = require_list(quote["sparkline"], f"{context}.sparkline")
    require(1 <= len(spark) <= 96, f"{context}.sparkline must contain 1..96 points")
    spark_by_time: dict[str, float] = {}
    previous_time: datetime | None = None
    for index, raw_point in enumerate(spark):
        point_context = f"{context}.sparkline[{index}]"
        point = require_dict(raw_point, point_context)
        require_keys(point, {"timeUtc", "value"}, point_context)
        point_time = parse_timestamp(
            point["timeUtc"], f"{point_context}.timeUtc", expected_offset=timedelta(0)
        )
        point_value = number(point["value"], f"{point_context}.value")
        require(point_value > 0, f"{point_context}.value must be positive")
        if previous_time is not None:
            require(point_time > previous_time, f"{context}.sparkline times must be strictly increasing")
        previous_time = point_time
        require(point["timeUtc"] not in spark_by_time, f"{context}.sparkline has duplicate times")
        spark_by_time[point["timeUtc"]] = point_value
    require(
        same_instant(previous_time or quote_utc, quote_utc),
        f"{context}.sparkline must end at quoteTimeUtc",
    )
    require(
        close_enough(spark[-1]["value"], current),
        f"{context}.sparkline must end at the current value",
    )
    for minutes in (5, 15, 30):
        validate_move(
            quote[f"move{minutes}m"],
            f"{context}.move{minutes}m",
            minutes=minutes,
            generated=generated,
            spark_by_time=spark_by_time,
        )
    validate_move(
        quote["peakToTrough"],
        f"{context}.peakToTrough",
        minutes=None,
        generated=generated,
        spark_by_time=spark_by_time,
    )


def validate_premarket(
    data: dict[str, Any],
    generated_utc: datetime,
    generated_jst: datetime,
    market_status: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    premarket = require_dict(data.get("premarket"), "premarket")
    require_keys(
        premarket,
        {
            "checkedAtUtc",
            "checkedAtJst",
            "marketStateLabel",
            "cashReference",
            "primaryNikkeiFutureKey",
            "nikkeiFutureValue",
            "nikkeiCashReferenceValue",
            "nikkeiFutureCashGapPoints",
            "nikkeiFutureCashGapPct",
            "usFuturesAverageChangePct",
            "quotes",
            "strategyCues",
            "summary",
            "caution",
        },
        "premarket",
    )
    checked_utc = parse_timestamp(
        premarket["checkedAtUtc"], "premarket.checkedAtUtc", expected_offset=timedelta(0)
    )
    checked_jst = parse_timestamp(
        premarket["checkedAtJst"],
        "premarket.checkedAtJst",
        expected_offset=timedelta(hours=9),
    )
    require(same_instant(checked_utc, generated_utc), "premarket.checkedAtUtc mismatch")
    require(same_instant(checked_jst, generated_jst), "premarket.checkedAtJst mismatch")

    quotes = require_dict(premarket["quotes"], "premarket.quotes")
    unknown = sorted(set(quotes) - set(EXPECTED_INSTRUMENTS))
    require(not unknown, f"premarket.quotes has unknown instruments: {unknown}")
    for key, profile in EXPECTED_INSTRUMENTS.items():
        status = market_status.get(profile["label"])
        require(status is not None, f"missing market-price source status for {key}")
        if key in quotes:
            require(status["status"] == "ok", f"{key} quote exists but source status is not ok")
            validate_quote(key, quotes[key], generated_utc)
        else:
            require(status["status"] == "failed", f"{key} quote missing without failed source status")
    require(
        len(market_status) == len(EXPECTED_INSTRUMENTS),
        "market-price sourceStatus must have exactly one row per configured instrument",
    )

    cash = quotes.get("NIKKEI_CASH") or {}
    yen_future = quotes.get("NIKKEI_FUTURES_YEN") or {}
    dollar_future = quotes.get("NIKKEI_FUTURES_USD") or {}
    primary = yen_future or dollar_future
    expected_primary_key = (
        "NIKKEI_FUTURES_YEN"
        if yen_future
        else "NIKKEI_FUTURES_USD"
        if dollar_future
        else None
    )
    require(premarket["cashReference"] == cash, "premarket.cashReference must mirror NIKKEI_CASH")
    require(
        premarket["primaryNikkeiFutureKey"] == expected_primary_key,
        "premarket.primaryNikkeiFutureKey mismatch",
    )
    cash_value = float(cash["value"]) if cash else None
    future_value = float(primary["value"]) if primary else None
    gap_points = (
        future_value - cash_value
        if future_value is not None and cash_value is not None
        else None
    )
    gap_pct = pct_change(future_value, cash_value)
    require(close_enough(premarket["nikkeiFutureValue"], future_value), "nikkeiFutureValue mismatch")
    require(
        close_enough(premarket["nikkeiCashReferenceValue"], cash_value),
        "nikkeiCashReferenceValue mismatch",
    )
    require(
        close_enough(premarket["nikkeiFutureCashGapPoints"], gap_points),
        "nikkeiFutureCashGapPoints identity failed",
    )
    require(
        close_enough(premarket["nikkeiFutureCashGapPct"], gap_pct),
        "nikkeiFutureCashGapPct identity failed",
    )
    us_keys = ("SP500_FUTURES", "NASDAQ100_FUTURES", "DOW_FUTURES", "RUSSELL2000_FUTURES")
    us_changes = [
        float(quotes[key]["changePct"])
        for key in us_keys
        if key in quotes and quotes[key].get("changePct") is not None
    ]
    expected_us_average = sum(us_changes) / len(us_changes) if us_changes else None
    require(
        close_enough(premarket["usFuturesAverageChangePct"], expected_us_average),
        "usFuturesAverageChangePct identity failed",
    )
    active = sum(1 for quote in quotes.values() if quote["marketState"] == "updating")
    expected_market_label = (
        f"{active}/{len(quotes)}系列が直近25分以内に更新"
        if quotes
        else "先物・時間外データを取得できません"
    )
    require(
        premarket["marketStateLabel"] == expected_market_label,
        "premarket.marketStateLabel mismatch",
    )

    expected_cues: list[tuple[str, str]] = []
    if gap_pct is not None:
        if gap_pct >= 0.5:
            expected_cues.append(("positive", "日経先物は現物終値を上回る"))
        elif gap_pct <= -0.5:
            expected_cues.append(("negative", "日経先物は現物終値を下回る"))
        else:
            expected_cues.append(("neutral", "日経先物と現物終値の差は小さい"))
    if expected_us_average is not None:
        direction = (
            "強い"
            if expected_us_average >= 0.35
            else "弱い"
            if expected_us_average <= -0.35
            else "まちまち"
        )
        expected_cues.append(
            (
                "positive"
                if expected_us_average >= 0.35
                else "negative"
                if expected_us_average <= -0.35
                else "neutral",
                f"米国株先物は平均で{direction}",
            )
        )
    fx_change = (
        float(quotes["USDJPY"]["changePct"])
        if "USDJPY" in quotes and quotes["USDJPY"].get("changePct") is not None
        else None
    )
    if fx_change is not None and abs(fx_change) >= 0.75:
        expected_cues.append(
            ("negative" if fx_change < 0 else "mixed", "ドル円の変動が大きい")
        )
    vix = float(quotes["VIX"]["value"]) if "VIX" in quotes else None
    if vix is not None:
        expected_cues.append(
            (
                "negative" if vix >= 30 else "warning" if vix >= 20 else "neutral",
                f"VIXは{vix:.1f}",
            )
        )
    cues = require_list(premarket["strategyCues"], "premarket.strategyCues")
    require(len(cues) == len(expected_cues), "premarket.strategyCues count mismatch")
    for index, (raw, expected) in enumerate(zip(cues, expected_cues)):
        context = f"premarket.strategyCues[{index}]"
        cue = require_dict(raw, context)
        require_keys(cue, {"state", "title", "text"}, context)
        require(
            cue["state"] in {"positive", "negative", "neutral", "mixed", "warning"},
            f"{context}.state is invalid",
        )
        require((cue["state"], cue["title"]) == expected, f"{context} does not match quote logic")
        require_string(cue["text"], f"{context}.text")
    require_string(premarket["summary"], "premarket.summary")
    require_string(premarket["caution"], "premarket.caution")
    require("予想始値" in premarket["summary"], "premarket.summary must reject a predicted-open interpretation")
    require("遅延" in premarket["caution"], "premarket.caution must disclose possible quote delay")
    return quotes


def expected_intervention_event_window(
    shock: dict[str, Any],
) -> tuple[datetime | None, datetime | None]:
    candidates: list[tuple[tuple[float, float], datetime, datetime]] = []
    for key in ("move5m", "move15m", "move30m"):
        move = require_dict(shock[key], f"marketShock.{key}")
        if move.get("startUtc") is None or move.get("endUtc") is None:
            continue
        start = parse_timestamp(
            move["startUtc"], f"marketShock.{key}.startUtc", expected_offset=timedelta(0)
        )
        end = parse_timestamp(
            move["endUtc"], f"marketShock.{key}.endUtc", expected_offset=timedelta(0)
        )
        score = (
            abs(number(move.get("pct"), f"marketShock.{key}.pct", nullable=True) or 0.0),
            abs(number(move.get("points"), f"marketShock.{key}.points", nullable=True) or 0.0),
        )
        candidates.append((score, start, end))
    if candidates:
        _, start, end = max(candidates, key=lambda row: row[0])
        return start, end
    if shock.get("observedAtUtc") is None:
        return None, None
    observed = parse_timestamp(
        shock["observedAtUtc"], "marketShock.observedAtUtc", expected_offset=timedelta(0)
    )
    return observed - timedelta(minutes=30), observed


def validate_evidence(
    evidence: Any,
    count_value: Any,
    event_start: datetime | None,
    event_end: datetime | None,
    briefing_items: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    rows = require_list(evidence, "marketShock.reportedEvidence")
    require(len(rows) <= 6, "marketShock.reportedEvidence must be capped at six")
    count = require_int(
        count_value, "marketShock.reportedEvidenceCount", low=0
    )
    require(count >= len(rows), "reportedEvidenceCount cannot be smaller than stored evidence")
    if count <= 6:
        require(count == len(rows), "reportedEvidenceCount/list length mismatch")
    ids: set[str] = set()
    urls: set[str] = set()
    for index, raw in enumerate(rows):
        context = f"marketShock.reportedEvidence[{index}]"
        row = require_dict(raw, context)
        require_keys(
            row,
            {"id", "source", "title", "url", "publishedAtUtc", "claimStatus"},
            context,
        )
        evidence_id = require_string(row["id"], f"{context}.id")
        require(re.fullmatch(r"live-[0-9a-f]{14}", evidence_id), f"{context}.id is malformed")
        require(evidence_id not in ids, f"duplicate intervention evidence id: {evidence_id}")
        ids.add(evidence_id)
        title = require_string(row["title"], f"{context}.title")
        source = require_string(row["source"], f"{context}.source")
        url = require_https_url(row["url"], f"{context}.url")
        normalized_url = normalize_url(url)
        require(normalized_url not in urls, f"duplicate intervention evidence URL: {url}")
        urls.add(normalized_url)
        require(
            evidence_id == expected_item_id(url, title),
            f"{context}.id does not match title/URL identity",
        )
        published = parse_timestamp(
            row["publishedAtUtc"],
            f"{context}.publishedAtUtc",
            expected_offset=timedelta(0),
        )
        require(
            event_start is not None and event_end is not None,
            f"{context} exists without a measurable price-event window",
        )
        require(
            event_start - timedelta(hours=1) <= published <= event_end + timedelta(hours=24),
            f"{context} is not time-correlated with the measured price event",
        )
        require(
            re.search(r"\bintervention\b|介入", title, re.I),
            f"{context} does not contain an intervention claim",
        )
        require(
            row["claimStatus"] == "intervention-observation",
            f"{context}.claimStatus must remain an observation",
        )
        if evidence_id in briefing_items:
            item = briefing_items[evidence_id]
            require(item["sourceKind"] in {"news", "news-wire"}, f"{context} is not news evidence")
            require(
                item["verification"] in {"reported", "reported-unconfirmed"},
                f"{context} is not explicitly unconfirmed reporting",
            )
            for field in ("source", "title", "url", "publishedAtUtc"):
                require(row[field] == item[field], f"{context}.{field} differs from briefing item")
        require(source.strip(), f"{context}.source must not be empty")
    return rows, count


def validate_market_shock(
    data: dict[str, Any],
    generated: datetime,
    quotes: dict[str, dict[str, Any]],
    briefing_items: dict[str, dict[str, Any]],
) -> None:
    shock = require_dict(data.get("marketShock"), "marketShock")
    require_keys(
        shock,
        {
            "instrument",
            "severity",
            "severityLabel",
            "headline",
            "summary",
            "interventionStatus",
            "interventionLabel",
            "officiallyConfirmed",
            "assessmentRule",
            "observedAtUtc",
            "observedAtJst",
            "checkedAtUtc",
            "current",
            "previousClose",
            "changePct",
            "sessionHigh",
            "sessionLow",
            "sessionRangePct",
            "move5m",
            "move15m",
            "move30m",
            "peakToTrough",
            "sparkline",
            "priceSourceUrl",
            "officialVerificationUrl",
            "officialVerificationNote",
            "reportedEvidence",
            "reportedEvidenceCount",
        },
        "marketShock",
        optional={
            "eventId",
            "eventStartEstimateJst",
            "officialDisclosureSchedule",
        },
    )
    require(shock["instrument"] == "USD/JPY", "marketShock.instrument must be USD/JPY")
    checked = parse_timestamp(
        shock["checkedAtUtc"], "marketShock.checkedAtUtc", expected_offset=timedelta(0)
    )
    require(same_instant(checked, generated), "marketShock.checkedAtUtc mismatch")
    fx = quotes.get("USDJPY") or {}
    copied_fields = {
        "current": "value",
        "previousClose": "previousClose",
        "changePct": "changePct",
        "sessionHigh": "sessionHigh",
        "sessionLow": "sessionLow",
        "sessionRangePct": "sessionRangePct",
        "move5m": "move5m",
        "move15m": "move15m",
        "move30m": "move30m",
        "peakToTrough": "peakToTrough",
        "sparkline": "sparkline",
        "priceSourceUrl": "sourceUrl",
    }
    for shock_field, quote_field in copied_fields.items():
        expected = fx.get(quote_field)
        actual = shock.get(shock_field)
        if isinstance(expected, (int, float)) or isinstance(actual, (int, float)):
            require(close_enough(actual, expected), f"marketShock.{shock_field} differs from USDJPY")
        else:
            require(actual == expected, f"marketShock.{shock_field} differs from USDJPY")
    require(shock["observedAtUtc"] == fx.get("quoteTimeUtc"), "marketShock.observedAtUtc mismatch")
    require(shock["observedAtJst"] == fx.get("quoteTimeJst"), "marketShock.observedAtJst mismatch")
    if shock["observedAtUtc"] is not None:
        observed_utc = parse_timestamp(
            shock["observedAtUtc"],
            "marketShock.observedAtUtc",
            expected_offset=timedelta(0),
        )
        observed_jst = parse_timestamp(
            shock["observedAtJst"],
            "marketShock.observedAtJst",
            expected_offset=timedelta(hours=9),
        )
        require(same_instant(observed_utc, observed_jst), "marketShock observed times differ")

    day_change = number(shock["changePct"], "marketShock.changePct", nullable=True)
    range_pct = number(shock["sessionRangePct"], "marketShock.sessionRangePct", nullable=True)
    peak_pct = number(
        require_dict(shock["peakToTrough"], "marketShock.peakToTrough").get("pct"),
        "marketShock.peakToTrough.pct",
        nullable=True,
    )
    move30_pct = number(
        require_dict(shock["move30m"], "marketShock.move30m").get("pct"),
        "marketShock.move30m.pct",
        nullable=True,
    )
    peak_points = number(
        shock["peakToTrough"].get("points"),
        "marketShock.peakToTrough.points",
        nullable=True,
    )
    move30_points = number(
        shock["move30m"].get("points"), "marketShock.move30m.points", nullable=True
    )
    magnitude = max(
        abs(day_change or 0),
        abs(range_pct or 0),
        abs(peak_pct or 0),
        abs(move30_pct or 0),
    )
    if magnitude >= 2 or abs(peak_points or 0) >= 3:
        expected_severity = "critical"
    elif magnitude >= 1 or abs(move30_points or 0) >= 1.5:
        expected_severity = "warning"
    elif fx:
        expected_severity = "normal"
    else:
        expected_severity = "unknown"
    require(
        shock["severity"] in {"critical", "warning", "normal", "unknown"},
        "marketShock.severity is invalid",
    )
    require(shock["severity"] == expected_severity, "marketShock.severity formula failed")
    expected_label = {
        "critical": "重大な急変",
        "warning": "急変を監視",
        "normal": "通常範囲",
        "unknown": "取得不能",
    }[expected_severity]
    require(shock["severityLabel"] == expected_label, "marketShock.severityLabel mismatch")

    event_start, event_end = expected_intervention_event_window(shock)
    evidence_rows, evidence_count = validate_evidence(
        shock["reportedEvidence"],
        shock["reportedEvidenceCount"],
        event_start,
        event_end,
        briefing_items,
    )
    if expected_severity in {"critical", "warning"}:
        expected_intervention = (
            "reported-unconfirmed" if evidence_count else "price-shock-only"
        )
    elif expected_severity == "normal":
        expected_intervention = "no-shock-observed"
    else:
        expected_intervention = "unknown"
    require(
        shock["interventionStatus"] == expected_intervention,
        "marketShock.interventionStatus does not follow evidence state",
    )
    require(
        shock["officiallyConfirmed"] is False,
        "officiallyConfirmed must remain false without a first-party confirmation state",
    )
    require(
        shock["interventionStatus"] not in {"officially-confirmed", "confirmed"},
        "price/report evidence must not become official intervention confirmation",
    )
    require_string(shock["headline"], "marketShock.headline")
    require_string(shock["summary"], "marketShock.summary")
    require_string(shock["interventionLabel"], "marketShock.interventionLabel")
    require_string(shock["assessmentRule"], "marketShock.assessmentRule")
    require(
        "介入認定条件ではない" in shock["assessmentRule"],
        "marketShock.assessmentRule must separate price thresholds from confirmation",
    )
    if expected_intervention in {"reported-unconfirmed", "price-shock-only"}:
        combined = shock["headline"] + shock["summary"] + shock["interventionLabel"]
        require(
            "未確認" in combined or "確認なし" in combined,
            "unconfirmed intervention state must be labelled as unconfirmed",
        )
    require_https_url(
        shock["officialVerificationUrl"],
        "marketShock.officialVerificationUrl",
        hosts={"mof.go.jp"},
    )
    require_string(shock["officialVerificationNote"], "marketShock.officialVerificationNote")
    if fx:
        require_https_url(
            shock["priceSourceUrl"],
            "marketShock.priceSourceUrl",
            hosts={"finance.yahoo.com"},
        )
    else:
        require(shock["priceSourceUrl"] is None, "missing USDJPY quote must have no price URL")

    event_fields = {
        "eventId",
        "eventStartEstimateJst",
        "officialDisclosureSchedule",
    }
    present_event_fields = event_fields.intersection(shock)
    require(
        not present_event_fields or present_event_fields == event_fields,
        "marketShock event metadata must be all present or all absent",
    )
    july_event_start = datetime(2026, 7, 30, 13, 0, tzinfo=timezone.utc)
    july_event_end = datetime(2026, 7, 30, 15, 30, tzinfo=timezone.utc)
    should_have_july_metadata = (
        expected_severity in {"critical", "warning"}
        and event_start is not None
        and event_end is not None
        and event_start <= july_event_end
        and event_end >= july_event_start
    )
    require(
        bool(present_event_fields) == should_have_july_metadata,
        "July 30 event metadata does not match the measured event window",
    )

    if present_event_fields:
        require(shock["eventId"] == "usdjpy-2026-07-30-shock", "marketShock.eventId mismatch")
        metadata_event_start = parse_timestamp(
            shock["eventStartEstimateJst"],
            "marketShock.eventStartEstimateJst",
            expected_offset=timedelta(hours=9),
        )
        schedule = require_dict(
            shock["officialDisclosureSchedule"],
            "marketShock.officialDisclosureSchedule",
        )
        require_keys(
            schedule,
            {"immediateRelease", "nextMonthlyReleaseIncludingEventDate", "sourceUrl"},
            "marketShock.officialDisclosureSchedule",
        )
        immediate = require_dict(
            schedule["immediateRelease"],
            "marketShock.officialDisclosureSchedule.immediateRelease",
        )
        require_keys(
            immediate,
            {"atJst", "coversThrough", "coversThisEvent"},
            "marketShock.officialDisclosureSchedule.immediateRelease",
        )
        following = require_dict(
            schedule["nextMonthlyReleaseIncludingEventDate"],
            "marketShock.officialDisclosureSchedule.nextMonthlyReleaseIncludingEventDate",
        )
        require_keys(
            following,
            {"atJst", "expectedCoverageStart", "coversThisEventDate"},
            "marketShock.officialDisclosureSchedule.nextMonthlyReleaseIncludingEventDate",
        )
        immediate_at = parse_timestamp(
            immediate["atJst"],
            "marketShock.officialDisclosureSchedule.immediateRelease.atJst",
            expected_offset=timedelta(hours=9),
        )
        following_at = parse_timestamp(
            following["atJst"],
            "marketShock.officialDisclosureSchedule.nextMonthlyReleaseIncludingEventDate.atJst",
            expected_offset=timedelta(hours=9),
        )
        try:
            covers_through = date.fromisoformat(immediate["coversThrough"])
            coverage_start = date.fromisoformat(following["expectedCoverageStart"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("official disclosure coverage dates must be ISO dates") from exc
        require(immediate["coversThisEvent"] is False, "immediate release must not claim event coverage")
        require(
            following["coversThisEventDate"] is True,
            "next monthly release must identify that it covers the event date",
        )
        require(event_start is not None, "event metadata exists without a measured event start")
        require(
            same_instant(metadata_event_start, event_start),
            "eventStartEstimateJst differs from the measured short-move start",
        )
        require(covers_through < metadata_event_start.date(), "immediate release incorrectly covers event date")
        require(coverage_start <= metadata_event_start.date(), "next release starts after the event date")
        require(immediate_at < following_at, "official disclosure dates are reversed")
        require(
            schedule["sourceUrl"] == shock["officialVerificationUrl"],
            "official disclosure source differs from verification source",
        )
        require_https_url(
            schedule["sourceUrl"],
            "marketShock.officialDisclosureSchedule.sourceUrl",
            hosts={"mof.go.jp"},
        )
    require(
        not evidence_rows or expected_severity in {"critical", "warning"},
        "intervention evidence must not promote a non-shock state",
    )


def validate_item(
    raw: Any,
    index: int,
    generated: datetime,
    selected_topic_counts: Counter[str],
) -> dict[str, Any]:
    context = f"briefing.items[{index}]"
    item = require_dict(raw, context)
    require_keys(
        item,
        {
            "id",
            "title",
            "summary",
            "url",
            "source",
            "sourceKind",
            "verification",
            "publishedAtUtc",
            "retrievedAtUtc",
            "ageHours",
            "topicKey",
            "topic",
            "stance",
            "engagement",
            "engagementTotal",
            "priorityScore",
            "talkScore",
            "author",
            "identityNote",
        },
        context,
        optional={"carriedForward", "staleReason"},
    )
    item_id = require_string(item["id"], f"{context}.id")
    require(re.fullmatch(r"live-[0-9a-f]{14}", item_id), f"{context}.id is malformed")
    title = require_string(item["title"], f"{context}.title")
    require(len(title) <= 1000, f"{context}.title is unexpectedly long")
    summary = require_string(item["summary"], f"{context}.summary", allow_empty=True)
    url = require_https_url(item["url"], f"{context}.url")
    require(
        item_id == expected_item_id(url, title),
        f"{context}.id does not match normalized URL/title",
    )
    require_string(item["source"], f"{context}.source")
    source_kind = require_string(item["sourceKind"], f"{context}.sourceKind")
    require(source_kind in SOURCE_KINDS, f"{context}.sourceKind is invalid: {source_kind}")
    verification = require_string(item["verification"], f"{context}.verification")
    require(
        verification in VERIFICATION_VALUES,
        f"{context}.verification is invalid: {verification}",
    )
    if source_kind.startswith("official"):
        require(verification == "primary", f"{context} official item must be primary")
        allowed_hosts = (
            {"federalreserve.gov", "whitehouse.gov", "treasury.gov"}
            if source_kind == "official-us"
            else {"boj.or.jp", "mof.go.jp"}
        )
        require_https_url(url, f"{context}.url", hosts=allowed_hosts)
    elif source_kind in {"news", "news-wire"}:
        require(
            verification in {"reported", "reported-unconfirmed"},
            f"{context} news must remain reported evidence",
        )
    elif source_kind in {"x-index", "linkedin"}:
        require(
            verification in {"unverified", "public-indexed"},
            f"{context} indexed social item must disclose unverified/indexed status",
        )
    elif source_kind == "bluesky":
        require(verification == "unverified", f"{context} Bluesky item must be unverified")
    elif source_kind == "truth-social":
        require(
            verification == "primary-statement",
            f"{context} direct Truth Social item must be a primary statement, not a fact confirmation",
        )
    elif source_kind == "truth-social-archive":
        require(
            verification == "archived-statement",
            f"{context} archived Truth Social item must disclose archive status",
        )
    elif source_kind == "x-api":
        require_https_url(url, f"{context}.url", hosts={"x.com"})
        handle = item["source"].lstrip("@").lower()
        if verification == "primary-statement":
            require(
                handle in CURATED_X_HANDLES,
                f"{context} gives primary-statement status to an uncurated X handle",
            )
        else:
            require(verification == "unverified", f"{context} X item status is dishonest")
    if verification == "reported-unconfirmed":
        require(
            re.search(r"\bintervention\b|介入", title + " " + summary, re.I),
            f"{context} reported-unconfirmed item lacks the intervention context",
        )

    published = parse_timestamp(
        item["publishedAtUtc"], f"{context}.publishedAtUtc", expected_offset=timedelta(0)
    )
    retrieved = parse_timestamp(
        item["retrievedAtUtc"], f"{context}.retrievedAtUtc", expected_offset=timedelta(0)
    )
    require(published <= retrieved + timedelta(minutes=10), f"{context} is future-published")
    require(retrieved <= generated + timedelta(minutes=2), f"{context} retrieval is after generation")
    require(generated - published <= timedelta(days=7), f"{context} is older than seven days")
    expected_age = round(max(0.0, (retrieved - published).total_seconds() / 3600.0), 2)
    age = number(item["ageHours"], f"{context}.ageHours")
    require(close_enough(age, expected_age, absolute=0.011), f"{context}.ageHours mismatch")
    carried = item.get("carriedForward", False)
    require(isinstance(carried, bool), f"{context}.carriedForward must be boolean")
    if carried:
        require_string(item.get("staleReason"), f"{context}.staleReason")
    else:
        require("staleReason" not in item, f"{context}.staleReason requires carriedForward=true")
        require(
            abs((retrieved - generated).total_seconds()) <= 2,
            f"{context} current item retrieval must match generation",
        )

    topic_key = require_string(item["topicKey"], f"{context}.topicKey")
    require(topic_key in TOPIC_LABELS, f"{context}.topicKey is invalid: {topic_key}")
    require(item["topic"] == TOPIC_LABELS[topic_key], f"{context}.topic label mismatch")
    stance = require_string(item["stance"], f"{context}.stance")
    require(stance in STANCE_VALUES, f"{context}.stance is invalid")
    require(
        stance == expected_stance(title, summary),
        f"{context}.stance does not match the documented limited-vocabulary classifier",
    )
    engagement = require_dict(item["engagement"], f"{context}.engagement")
    engagement_total = 0
    for key, value in engagement.items():
        require_string(key, f"{context}.engagement key")
        engagement_total += require_int(
            value, f"{context}.engagement.{key}", low=0
        )
    require_int(item["engagementTotal"], f"{context}.engagementTotal", low=0)
    require(
        item["engagementTotal"] == engagement_total,
        f"{context}.engagementTotal identity failed",
    )
    require_int(item["priorityScore"], f"{context}.priorityScore", low=0, high=160)
    talk_score = require_int(item["talkScore"], f"{context}.talkScore", low=0, high=100)
    if not carried:
        recency_component = max(0, 28 - min(72, age) / 3)
        engagement_component = min(32, math.log10(engagement_total + 1) * 10)
        minimum_count = selected_topic_counts[topic_key]
        possible_counts = range(minimum_count, max(minimum_count, 6) + 1)
        possible_scores = {
            min(
                100,
                round(
                    18
                    + min(30, count * 5)
                    + engagement_component
                    + recency_component
                ),
            )
            for count in possible_counts
        }
        require(
            talk_score in possible_scores,
            f"{context}.talkScore cannot be produced by the documented formula",
        )
    require_string(item["author"], f"{context}.author", allow_empty=True)
    require_string(item["identityNote"], f"{context}.identityNote", allow_empty=True)
    return item


def validate_channels(
    briefing: dict[str, Any],
    source_rows: list[dict[str, Any]],
    generated: datetime,
    items: list[dict[str, Any]],
) -> None:
    channels = require_list(briefing["channels"], "briefing.channels")
    expected_kinds = {
        "official": ("official-us", "official-japan"),
        "news": ("news-discovery", "news", "news-wire"),
        "x": ("x-api", "x-index"),
        "linkedin": ("linkedin",),
        "other-social": ("bluesky", "truth-social", "truth-social-archive"),
    }
    require(len(channels) == len(expected_kinds), "briefing.channels count mismatch")
    channel_map: dict[str, dict[str, Any]] = {}
    source_by_kind: dict[str, list[dict[str, Any]]] = {}
    for row in source_rows:
        source_by_kind.setdefault(row["kind"], []).append(row)
    for index, raw in enumerate(channels):
        context = f"briefing.channels[{index}]"
        channel = require_dict(raw, context)
        require_keys(
            channel,
            {
                "key",
                "label",
                "status",
                "statusLabel",
                "directUrl",
                "checkedAtUtc",
                "limitation",
                "messages",
            },
            context,
        )
        key = require_string(channel["key"], f"{context}.key")
        require(key in expected_kinds, f"{context}.key is invalid: {key}")
        require(key not in channel_map, f"duplicate briefing channel: {key}")
        channel_map[key] = channel
        require_string(channel["label"], f"{context}.label")
        status = require_string(channel["status"], f"{context}.status")
        require(status in CHANNEL_STATUS_VALUES, f"{context}.status is invalid")
        expected_status_label = {
            "ok": "取得済み",
            "limited": "限定取得",
            "not-configured": "API未接続",
            "failed": "取得失敗",
        }[status]
        require(channel["statusLabel"] == expected_status_label, f"{context}.statusLabel mismatch")
        require_https_url(channel["directUrl"], f"{context}.directUrl")
        checked = parse_timestamp(
            channel["checkedAtUtc"],
            f"{context}.checkedAtUtc",
            expected_offset=timedelta(0),
        )
        require(same_instant(checked, generated), f"{context}.checkedAtUtc mismatch")
        require_string(channel["limitation"], f"{context}.limitation")
        messages = require_list(channel["messages"], f"{context}.messages")
        require(len(messages) <= 3, f"{context}.messages must be capped at three")
        for message_index, message in enumerate(messages):
            require_string(message, f"{context}.messages[{message_index}]")
        relevant_rows = [
            row
            for kind in expected_kinds[key]
            for row in source_by_kind.get(kind, [])
        ]
        states = {row["status"] for row in relevant_rows}
        if relevant_rows and states == {"ok"}:
            expected_status = "ok"
        elif states.intersection({"ok", "limited"}):
            expected_status = "limited"
        elif relevant_rows and states == {"not-configured"}:
            expected_status = "not-configured"
        else:
            expected_status = "failed"
        require(status == expected_status, f"{context}.status does not match sourceStatus")
    require(set(channel_map) == set(expected_kinds), "briefing.channels keys are incomplete")

    x_api_rows = [row for row in source_rows if row["kind"] == "x-api"]
    require(len(x_api_rows) == 1, "sourceStatus must contain exactly one x-api row")
    x_api = x_api_rows[0]
    x_channel = channel_map["x"]
    x_items = [item for item in items if item["sourceKind"] == "x-api"]
    if x_api["status"] == "not-configured":
        require(not x_items, "X API is not configured but x-api items were published")
        require(
            x_channel["status"] != "ok",
            "X API not-configured must not be presented as complete X coverage",
        )
        combined_messages = " ".join(x_channel["messages"] + [x_api["message"]])
        require(
            re.search(r"未設定|未接続|APIキー", combined_messages),
            "X not-configured state is not honestly disclosed in the channel",
        )


def validate_briefing(
    data: dict[str, Any],
    generated_utc: datetime,
    generated_jst: datetime,
    source_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    briefing = require_dict(data.get("briefing"), "briefing")
    require_keys(
        briefing,
        {
            "checkedAtUtc",
            "checkedAtJst",
            "summary",
            "lead",
            "items",
            "topicCounts",
            "topicLabels",
            "verificationCounts",
            "sourceKindCounts",
            "bullish",
            "bearish",
            "channels",
            "unverifiedCount",
            "readingRule",
        },
        "briefing",
    )
    checked_utc = parse_timestamp(
        briefing["checkedAtUtc"], "briefing.checkedAtUtc", expected_offset=timedelta(0)
    )
    checked_jst = parse_timestamp(
        briefing["checkedAtJst"],
        "briefing.checkedAtJst",
        expected_offset=timedelta(hours=9),
    )
    require(same_instant(checked_utc, generated_utc), "briefing.checkedAtUtc mismatch")
    require(same_instant(checked_jst, generated_jst), "briefing.checkedAtJst mismatch")
    require_string(briefing["summary"], "briefing.summary")
    require(
        "事実確認度" in briefing["summary"] and "相場方向" in briefing["summary"],
        "briefing.summary must distinguish talk score, verification, and direction",
    )
    require_string(briefing["readingRule"], "briefing.readingRule")
    require(
        "直接変換しません" in briefing["readingRule"],
        "briefing.readingRule must reject direct social-to-signal conversion",
    )
    require(briefing["topicLabels"] == TOPIC_LABELS, "briefing.topicLabels contract changed")

    raw_items = require_list(briefing["items"], "briefing.items")
    require(
        len(raw_items) <= BRIEFING_ITEM_LIMIT,
        f"briefing.items must be capped at {BRIEFING_ITEM_LIMIT}",
    )
    raw_topic_counts = Counter(
        raw.get("topicKey") for raw in raw_items if isinstance(raw, dict)
    )
    items = [
        validate_item(raw, index, generated_utc, raw_topic_counts)
        for index, raw in enumerate(raw_items)
    ]
    ids = [item["id"] for item in items]
    urls = [normalize_url(item["url"]) for item in items]
    title_keys = [
        re.sub(r"[^a-z0-9一-龥ぁ-んァ-ン]+", "", item["title"].lower())[:180]
        for item in items
    ]
    require(len(ids) == len(set(ids)), "briefing.items has duplicate ids")
    require(len(urls) == len(set(urls)), "briefing.items has duplicate normalized URLs")
    require(
        len([key for key in title_keys if key])
        == len(set(key for key in title_keys if key)),
        "briefing.items has duplicate normalized titles",
    )
    carried_count = sum(1 for item in items if item.get("carriedForward"))
    require(
        carried_count == data["dataHealth"]["carriedForwardItems"],
        "carriedForwardItems count mismatch",
    )

    topic_counts = dict(Counter(item["topicKey"] for item in items))
    verification_counts = dict(Counter(item["verification"] for item in items))
    source_kind_counts = dict(Counter(item["sourceKind"] for item in items))
    require(briefing["topicCounts"] == topic_counts, "briefing.topicCounts mismatch")
    require(
        briefing["verificationCounts"] == verification_counts,
        "briefing.verificationCounts mismatch",
    )
    require(
        briefing["sourceKindCounts"] == source_kind_counts,
        "briefing.sourceKindCounts mismatch",
    )
    require(
        briefing["unverifiedCount"]
        == sum(1 for item in items if item["verification"] == "unverified"),
        "briefing.unverifiedCount mismatch",
    )
    require_int(briefing["unverifiedCount"], "briefing.unverifiedCount", low=0)

    def expected_direction_rows(stance: str) -> list[dict[str, str]]:
        return [
            {
                "title": item["title"],
                "source": item["source"],
                "url": item["url"],
                "verification": item["verification"],
            }
            for item in items
            if item["stance"] == stance
            and item["topicKey"] in {"us-stocks", "japan-stocks", "ai-bubble"}
        ][:4]

    require(
        briefing["bullish"] == expected_direction_rows("bullish"),
        "briefing.bullish projection mismatch",
    )
    require(
        briefing["bearish"] == expected_direction_rows("bearish"),
        "briefing.bearish projection mismatch",
    )
    for group in ("bullish", "bearish"):
        for index, row in enumerate(require_list(briefing[group], f"briefing.{group}")):
            context = f"briefing.{group}[{index}]"
            require_dict(row, context)
            require_keys(row, {"title", "source", "url", "verification"}, context)
            require_https_url(row["url"], f"{context}.url")

    validate_channels(briefing, source_rows, generated_utc, items)
    lead = require_dict(briefing["lead"], "briefing.lead")
    require_keys(
        lead,
        {
            "id",
            "topicKey",
            "topic",
            "title",
            "summary",
            "verification",
            "interventionStatus",
            "interventionLabel",
            "talkScore",
            "sourceCounts",
            "primaryUrl",
            "officialUrl",
        },
        "briefing.lead",
    )
    shock = data["marketShock"]
    require(lead["id"] == "usd-jpy-shock", "briefing.lead.id mismatch")
    require(
        (lead["topicKey"], lead["topic"]) == ("fx-rates", TOPIC_LABELS["fx-rates"]),
        "briefing.lead topic mismatch",
    )
    for lead_field, shock_field in (
        ("title", "headline"),
        ("summary", "summary"),
        ("interventionStatus", "interventionStatus"),
        ("interventionLabel", "interventionLabel"),
        ("primaryUrl", "priceSourceUrl"),
        ("officialUrl", "officialVerificationUrl"),
    ):
        require(
            lead[lead_field] == shock[shock_field],
            f"briefing.lead.{lead_field} differs from marketShock",
        )
    require(
        lead["verification"] == "price-confirmed-official-unconfirmed",
        "briefing.lead must not imply official intervention confirmation",
    )
    lead_score = require_int(lead["talkScore"], "briefing.lead.talkScore", low=0, high=100)
    selected_intervention_scores = [
        item["talkScore"]
        for item in items
        if re.search(
            r"\bintervention\b|介入",
            item["title"] + " " + item["summary"],
            re.I,
        )
    ]
    require(
        lead_score >= max(selected_intervention_scores or [0]),
        "briefing.lead.talkScore is below a selected intervention item",
    )
    source_counts = require_dict(lead["sourceCounts"], "briefing.lead.sourceCounts")
    require_keys(source_counts, {"official", "news", "social"}, "briefing.lead.sourceCounts")
    for key in ("official", "news", "social"):
        require_int(source_counts[key], f"briefing.lead.sourceCounts.{key}", low=0)
    require(
        source_counts["news"] >= shock["reportedEvidenceCount"],
        "briefing.lead news count is below reported intervention evidence",
    )
    if lead["primaryUrl"] is not None:
        require_https_url(lead["primaryUrl"], "briefing.lead.primaryUrl")
    require_https_url(lead["officialUrl"], "briefing.lead.officialUrl", hosts={"mof.go.jp"})
    return {item["id"]: item for item in items}


def validate_methodology(data: dict[str, Any]) -> None:
    methodology = require_dict(data.get("methodology"), "methodology")
    require_keys(methodology, {"intervention", "talkScore", "stance"}, "methodology")
    for key in ("intervention", "talkScore", "stance"):
        require_string(methodology[key], f"methodology.{key}")
    require(
        "価格急変" in methodology["intervention"]
        and "officiallyConfirmed=false" in methodology["intervention"],
        "methodology.intervention must document the price/confirmation boundary",
    )
    require(
        "0–100" in methodology["talkScore"] and "危険確率でもない" in methodology["talkScore"],
        "methodology.talkScore must disclose its scale and limitation",
    )
    require(
        "限定語彙" in methodology["stance"] and "投資判断" in methodology["stance"],
        "methodology.stance must disclose its limited classifier",
    )


def run_price_only_intervention_regression() -> None:
    """Exercise the producer's pure state logic without any network access."""

    try:
        import live_intelligence as producer
    except ImportError as exc:
        raise ValidationError("unable to import scripts/live_intelligence.py") from exc

    now = datetime(2026, 7, 30, 14, 30, tzinfo=timezone.utc)
    quote = {
        "value": 157.0,
        "previousClose": 161.0,
        "changePct": pct_change(157.0, 161.0),
        "sessionHigh": 161.2,
        "sessionLow": 156.8,
        "sessionRangePct": pct_change(161.2, 156.8),
        "move5m": {
            "minutes": 5,
            "points": -1.8,
            "pct": -1.13,
            "startUtc": "2026-07-30T14:00:00+00:00",
            "endUtc": "2026-07-30T14:05:00+00:00",
        },
        "move15m": {
            "minutes": 15,
            "points": -2.5,
            "pct": -1.57,
            "startUtc": "2026-07-30T14:00:00+00:00",
            "endUtc": "2026-07-30T14:15:00+00:00",
        },
        "move30m": {
            "minutes": 30,
            "points": -4.0,
            "pct": -2.48,
            "startUtc": "2026-07-30T14:00:00+00:00",
            "endUtc": "2026-07-30T14:30:00+00:00",
        },
        "peakToTrough": {
            "points": 4.4,
            "pct": 2.73,
            "startUtc": "2026-07-30T13:55:00+00:00",
            "endUtc": "2026-07-30T14:30:00+00:00",
        },
        "sparkline": [],
        "quoteTimeUtc": now.isoformat(),
        "quoteTimeJst": now.astimezone(JST).isoformat(),
        "sourceUrl": "https://finance.yahoo.com/quote/JPY%3DX",
    }
    shock = producer.build_market_shock({"USDJPY": quote}, now)
    require(shock["severity"] == "critical", "regression fixture must trigger a critical shock")
    require(
        shock["interventionStatus"] == "price-shock-only",
        "price-only critical move was promoted beyond price-shock-only",
    )
    require(
        shock["officiallyConfirmed"] is False,
        "price-only critical move set officiallyConfirmed=true",
    )
    producer.update_intervention_assessment(shock, [])
    require(
        shock["interventionStatus"] == "price-shock-only"
        and shock["officiallyConfirmed"] is False,
        "empty evidence promoted a price-only shock",
    )

    social_item = {
        "id": "live-social-test",
        "title": "Possible intervention after the yen move",
        "summary": "Unverified social speculation",
        "url": "https://x.com/example/status/1",
        "source": "@example",
        "sourceKind": "x-api",
        "verification": "unverified",
        "publishedAtUtc": now.isoformat(),
    }
    producer.update_intervention_assessment(shock, [social_item])
    require(
        shock["interventionStatus"] == "price-shock-only"
        and shock["officiallyConfirmed"] is False,
        "unverified social evidence promoted intervention confirmation",
    )

    news_item = {
        "id": "live-news-test",
        "title": "Traders suspect intervention after yen jump",
        "summary": "No official confirmation was available.",
        "url": "https://example.com/intervention-report",
        "source": "Example News",
        "sourceKind": "news",
        "verification": "reported-unconfirmed",
        "publishedAtUtc": now.isoformat(),
    }
    producer.update_intervention_assessment(shock, [news_item])
    require(
        shock["interventionStatus"] == "reported-unconfirmed",
        "credible reporting did not produce reported-unconfirmed",
    )
    require(
        shock["officiallyConfirmed"] is False,
        "news reporting incorrectly became official intervention confirmation",
    )

    later_now = datetime(2026, 8, 5, 14, 30, tzinfo=timezone.utc)
    later_quote = json.loads(json.dumps(quote))
    later_quote["quoteTimeUtc"] = later_now.isoformat()
    later_quote["quoteTimeJst"] = later_now.astimezone(JST).isoformat()
    later_quote["move5m"]["startUtc"] = "2026-08-05T14:00:00+00:00"
    later_quote["move5m"]["endUtc"] = "2026-08-05T14:05:00+00:00"
    later_quote["move15m"]["startUtc"] = "2026-08-05T14:00:00+00:00"
    later_quote["move15m"]["endUtc"] = "2026-08-05T14:15:00+00:00"
    later_quote["move30m"]["startUtc"] = "2026-08-05T14:00:00+00:00"
    later_quote["move30m"]["endUtc"] = "2026-08-05T14:30:00+00:00"
    later_quote["peakToTrough"]["startUtc"] = "2026-08-05T13:55:00+00:00"
    later_quote["peakToTrough"]["endUtc"] = "2026-08-05T14:30:00+00:00"
    later_shock = producer.build_market_shock({"USDJPY": later_quote}, later_now)
    producer.update_intervention_assessment(later_shock, [news_item])
    require(
        later_shock["interventionStatus"] == "price-shock-only",
        "a later USDJPY shock reused the July 30 intervention report",
    )
    require(
        later_shock["reportedEvidenceCount"] == 0,
        "stale intervention reporting was retained for a later shock",
    )
    require(
        "eventId" not in later_shock
        and "eventStartEstimateJst" not in later_shock
        and "officialDisclosureSchedule" not in later_shock,
        "July 30 event metadata leaked into a later USDJPY shock",
    )


def validate(path: Path) -> dict[str, Any]:
    require(path.exists(), f"live data file does not exist: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON in {path}: {exc}") from exc
    data = require_dict(data, "root")
    require_keys(
        data,
        {
            "schemaVersion",
            "generatedAtUtc",
            "generatedAtJst",
            "refreshPolicy",
            "dataHealth",
            "marketShock",
            "premarket",
            "briefing",
            "sourceStatus",
            "methodology",
        },
        "root",
        optional={"fallbackAppliedAtUtc"},
    )
    require(data["schemaVersion"] == 1, "live schemaVersion must be 1")
    generated_utc, generated_jst = validate_root_times(data)
    validate_refresh_policy(data)
    source_rows, market_status = validate_source_status(data, generated_utc)
    validate_data_health(data, source_rows)
    validate_methodology(data)
    briefing_items = validate_briefing(
        data, generated_utc, generated_jst, source_rows
    )
    quotes = validate_premarket(
        data, generated_utc, generated_jst, market_status
    )
    validate_market_shock(
        data, generated_utc, quotes, briefing_items
    )
    run_price_only_intervention_regression()
    return data


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT,
        help="live-intelligence JSON path (default: data/live-intelligence.json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        data = validate(args.path.resolve())
    except (OSError, ValidationError) as exc:
        print(f"Live data validation failed: {exc}", file=sys.stderr)
        return 1
    print(
        "Live data validation passed: "
        f"schema {data['schemaVersion']}, "
        f"{len((data.get('premarket') or {}).get('quotes') or {})} quotes, "
        f"{len((data.get('briefing') or {}).get('items') or [])} briefing items, "
        f"intervention={data['marketShock']['interventionStatus']} "
        f"(officiallyConfirmed={str(data['marketShock']['officiallyConfirmed']).lower()})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
