#!/usr/bin/env python3
"""Tencent Finance public CSI 300 day-end parser used as a labelled fallback."""

from __future__ import annotations

import json
import math
import urllib.parse
from datetime import date
from typing import Any


TENCENT_CSI300_DAILY_ENDPOINT = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
TENCENT_CSI300_PUBLIC_URL = "https://gu.qq.com/sh000300"
TENCENT_CSI300_SOURCE_LABEL = "Tencent Finance 公開CSI 300日足"


def tencent_csi300_daily_url(limit: int = 1000) -> str:
    query = urllib.parse.urlencode({"param": f"sh000300,day,,,{int(limit)}"})
    return TENCENT_CSI300_DAILY_ENDPOINT + "?" + query


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def parse_tencent_csi300_daily_payload(raw: bytes | str) -> list[dict[str, Any]]:
    """Parse raw, unadjusted published daily OHLC rows."""

    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    payload = json.loads(text)
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = data.get("sh000300", {}).get("day") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Tencent CSI 300 day-end response has no day list")
    parsed: list[dict[str, Any]] = []
    for raw_row in rows:
        if not isinstance(raw_row, list) or len(raw_row) < 5:
            continue
        try:
            trading_date = date.fromisoformat(str(raw_row[0])).isoformat()
            opening, closing, high, low = (finite(raw_row[index]) for index in range(1, 5))
        except ValueError:
            continue
        if (
            opening is None or closing is None or high is None or low is None
            or min(opening, closing, high, low) <= 0 or high < low
        ):
            continue
        parsed.append({
            "date": trading_date,
            "open": opening,
            "close": closing,
            "high": high,
            "low": low,
        })
    parsed.sort(key=lambda row: row["date"])
    if len(parsed) < 2:
        raise ValueError("Tencent CSI 300 day-end response has too few valid rows")
    return parsed
