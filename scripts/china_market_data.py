#!/usr/bin/env python3
"""Small, auditable helpers for the CSI 300 public day-end fallback.

Yahoo Finance is the primary historical provider elsewhere in the monitor.
The CSI 300 feed has occasionally stopped advancing for many calendar days,
so this module provides a separately labelled public day-end source.  It does
not infer prices: callers either receive parsed published OHLC rows or fail.
"""

from __future__ import annotations

import json
import math
import urllib.parse
from datetime import date, datetime, time as clock_time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


CSI300_EASTMONEY_DAILY_ENDPOINT = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
CSI300_EASTMONEY_PUBLIC_URL = (
    "https://quote.eastmoney.com/center/hszs.html#zixuan_000300"
)
CSI300_EASTMONEY_SOURCE_LABEL = "Eastmoney 公開CSI 300日足"
SHANGHAI = ZoneInfo("Asia/Shanghai")
CSI300_CLOSE_TIME = clock_time(15, 0)
CSI300_FINALIZATION_GRACE = timedelta(minutes=20)


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (current / previous - 1.0) * 100.0


def csi300_daily_url(start: date, end: date) -> str:
    """Return the documented query shape used by Eastmoney's public chart."""

    query = urllib.parse.urlencode(
        {
            "secid": "1.000300",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "0",
            "beg": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
        }
    )
    return CSI300_EASTMONEY_DAILY_ENDPOINT + "?" + query


def parse_csi300_daily_payload(raw: bytes | str) -> list[dict[str, Any]]:
    """Parse published CSI 300 daily OHLC rows without using adjusted prices."""

    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    payload = json.loads(text)
    data = payload.get("data") if isinstance(payload, dict) else None
    klines = data.get("klines") if isinstance(data, dict) else None
    if not isinstance(klines, list):
        raise ValueError("CSI 300 day-end response has no kline list")

    rows_by_date: dict[str, dict[str, Any]] = {}
    for row in klines:
        fields = str(row or "").split(",")
        if len(fields) < 5:
            continue
        try:
            trading_date = date.fromisoformat(fields[0]).isoformat()
        except ValueError:
            continue
        opening = finite(fields[1])
        closing = finite(fields[2])
        high = finite(fields[3])
        low = finite(fields[4])
        if (
            opening is None
            or closing is None
            or high is None
            or low is None
            or min(opening, closing, high, low) <= 0
            or high < low
        ):
            continue
        rows_by_date[trading_date] = {
            "date": trading_date,
            "open": opening,
            "close": closing,
            "high": high,
            "low": low,
        }
    rows = [rows_by_date[key] for key in sorted(rows_by_date)]
    if len(rows) < 2:
        raise ValueError("CSI 300 day-end response has too few valid rows")
    return rows


def csi300_session_close_utc(trading_date: date) -> datetime:
    return datetime.combine(trading_date, CSI300_CLOSE_TIME, tzinfo=SHANGHAI).astimezone(
        timezone.utc
    )


def csi300_day_is_final(trading_date: date, now: datetime) -> bool:
    return now.astimezone(timezone.utc) >= (
        csi300_session_close_utc(trading_date) + CSI300_FINALIZATION_GRACE
    )


def expected_csi300_completed_weekday(now: datetime) -> date:
    """Return the latest ordinary weekday that should have a completed close.

    China exchange holidays are intentionally *not* guessed.  If a source is
    older than this weekday, the caller marks it as stale/holiday-unverified
    rather than presenting it as a current close.
    """

    local = now.astimezone(SHANGHAI)
    candidate = local.date()
    if local.timetz().replace(tzinfo=None) < (
        datetime.combine(candidate, CSI300_CLOSE_TIME) + CSI300_FINALIZATION_GRACE
    ).time():
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def weekday_gap(start_date: date, end_date: date) -> int:
    """Count ordinary weekdays after start_date through end_date, inclusive."""

    if end_date <= start_date:
        return 0
    count = 0
    cursor = start_date + timedelta(days=1)
    while cursor <= end_date:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count

def csi300_freshness(latest_date: date, now: datetime) -> dict[str, Any]:
    """Return a safety-first freshness contract for a completed CSI 300 close."""

    expected_date = expected_csi300_completed_weekday(now)
    delayed_weekdays = weekday_gap(latest_date, expected_date)
    if delayed_weekdays == 0:
        return {
            "freshnessStatus": "current",
            "freshnessExpectedSessionDate": expected_date.isoformat(),
            "freshnessDelayedWeekdays": 0,
            "freshnessNote": "直近の平日取引日までのCSI 300確定日足を取得。",
        }
    return {
        "freshnessStatus": "stale",
        "freshnessExpectedSessionDate": expected_date.isoformat(),
        "freshnessDelayedWeekdays": delayed_weekdays,
        "freshnessNote": (
            f"最終日足 {latest_date.isoformat()} は直近平日 {expected_date.isoformat()} より"
            f"{delayed_weekdays}営業日分古い。中国市場の休場または取得失敗を確認中のため、"
            "前日比・上昇下落の判定には使わない。"
        ),
    }
