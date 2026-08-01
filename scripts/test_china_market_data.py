#!/usr/bin/env python3
"""Network-free regression tests for the public CSI 300 daily-close inputs."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from china_market_data import (
    csi300_daily_url,
    csi300_day_is_final,
    csi300_freshness,
    csi300_session_close_utc,
    expected_csi300_completed_weekday,
    parse_csi300_daily_payload,
)
from tencent_csi300 import (
    parse_tencent_csi300_daily_payload,
    tencent_csi300_daily_url,
)
from validate_live_data import (
    CSI300_PUBLIC_SOURCE_HOSTS,
    ValidationError,
    quote_source_hosts,
    require_https_url,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_eastmoney_parser() -> list[dict[str, object]]:
    payload = {
        "data": {
            "klines": [
                "malformed",
                "2026-07-30,4540.00,4549.72,4560.00,4530.00,0,0,0,0,0,0",
                "2026-07-31,4550.00,4588.20,4600.00,4540.00,0,0,0,0,0,0",
                "2026-07-31,4550.00,4588.20,4600.00,4540.00,0,0,0,0,0,0",
            ]
        }
    }
    rows = parse_csi300_daily_payload(json.dumps(payload))
    require(
        [row["date"] for row in rows] == ["2026-07-30", "2026-07-31"],
        "Eastmoney rows were not sorted and deduplicated",
    )
    require(rows[-1]["close"] == 4588.20, "Eastmoney close parsing changed")
    require(
        rows[-1]["low"] <= rows[-1]["close"] <= rows[-1]["high"],
        "Eastmoney OHLC range changed",
    )
    return rows


def test_tencent_parser() -> list[dict[str, object]]:
    payload = {
        "data": {
            "sh000300": {
                "day": [
                    ["2026-07-31", "4550.00", "4588.20", "4600.00", "4540.00"],
                    ["broken"],
                    ["2026-07-30", "4540.00", "4549.72", "4560.00", "4530.00"],
                ]
            }
        }
    }
    rows = parse_tencent_csi300_daily_payload(json.dumps(payload).encode("utf-8"))
    require(
        [row["date"] for row in rows] == ["2026-07-30", "2026-07-31"],
        "Tencent rows were not sorted",
    )
    require(rows[-1]["close"] == 4588.20, "Tencent close parsing changed")
    require(
        rows[-1]["low"] <= rows[-1]["close"] <= rows[-1]["high"],
        "Tencent OHLC range changed",
    )
    return rows


def test_cross_source_fixture_agreement() -> None:
    eastmoney = test_eastmoney_parser()
    tencent = test_tencent_parser()
    require(
        eastmoney[-1]["date"] == tencent[-1]["date"],
        "fixture sources no longer share a close date",
    )
    east_close = float(eastmoney[-1]["close"])
    tencent_close = float(tencent[-1]["close"])
    close_gap_pct = abs(east_close / tencent_close - 1.0) * 100.0
    require(
        close_gap_pct <= 0.25,
        "fixture sources exceed the CSI 300 reconciliation threshold",
    )


def test_freshness_boundaries() -> None:
    now = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    require(
        expected_csi300_completed_weekday(now) == date(2026, 7, 31),
        "completed weekday boundary changed",
    )
    current = csi300_freshness(date(2026, 7, 31), now)
    require(
        current["freshnessStatus"] == "current"
        and current["freshnessDelayedWeekdays"] == 0,
        "current CSI 300 close was not recognised",
    )
    stale = csi300_freshness(date(2026, 7, 17), now)
    require(
        stale["freshnessStatus"] == "stale"
        and stale["freshnessDelayedWeekdays"] == 10,
        "stale CSI 300 close was not flagged",
    )
    close_utc = csi300_session_close_utc(date(2026, 7, 31))
    require(
        close_utc == datetime(2026, 7, 31, 7, 0, tzinfo=timezone.utc),
        "Shanghai close timestamp changed",
    )
    require(
        not csi300_day_is_final(date(2026, 7, 31), close_utc + timedelta(minutes=19)),
        "daily close finalised too early",
    )
    require(
        csi300_day_is_final(date(2026, 7, 31), close_utc + timedelta(minutes=20)),
        "daily close did not finalise at grace boundary",
    )


def test_public_urls_and_hosts() -> None:
    east_url = csi300_daily_url(date(2026, 7, 1), date(2026, 7, 31))
    require(
        "push2his.eastmoney.com" in east_url and "secid=1.000300" in east_url,
        "Eastmoney request URL changed",
    )
    tencent_url = tencent_csi300_daily_url(30)
    require(
        "web.ifzq.gtimg.cn" in tencent_url and "sh000300" in tencent_url,
        "Tencent request URL changed",
    )
    require(
        quote_source_hosts("CSI300_CASH") == CSI300_PUBLIC_SOURCE_HOSTS,
        "CSI 300 allowed source hosts changed",
    )
    for url in (
        "https://gu.qq.com/sh000300",
        "https://web.ifzq.gtimg.cn/appstock/app/kline/kline",
        "https://quote.eastmoney.com/center/hszs.html#zixuan_000300",
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
    ):
        require_https_url(
            url,
            "CSI 300 public source",
            hosts=quote_source_hosts("CSI300_CASH"),
        )
    try:
        require_https_url(
            "https://finance.yahoo.com/quote/000300.SS",
            "CSI 300 public source",
            hosts=quote_source_hosts("CSI300_CASH"),
        )
    except ValidationError:
        pass
    else:
        raise AssertionError(
            "Yahoo was incorrectly accepted as a CSI 300 public fallback source"
        )


def main() -> int:
    test_cross_source_fixture_agreement()
    test_freshness_boundaries()
    test_public_urls_and_hosts()
    print("CSI 300 public data regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
