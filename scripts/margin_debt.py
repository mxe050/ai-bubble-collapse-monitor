#!/usr/bin/env python3
"""Build the updateable U.S. margin-debt-to-GDP data package.

The long chart joins an archived NYSE Fact Book series through 1996 with
FINRA's downloadable series from 1997 onward.  The source regimes are kept
explicit because the reporting population and account definitions changed.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "margin-debt-history.json"
LEGACY = ROOT / "data" / "margin-debt-legacy.json"
FINRA_XLSX_URL = "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx"
FINRA_PAGE_URL = "https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics"
GDP_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDP"
GDP_PAGE_URL = "https://fred.stlouisfed.org/series/GDP"
NYSE_ARCHIVE_URL = (
    "https://web.archive.org/web/20180402044551/"
    "http://www.nyxdata.com/nysedata/asp/factbook/"
    "viewer_edition.asp?category=8&key=50&mode=tables"
)


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


def month_shift(value: str, months: int) -> str:
    observed = datetime.strptime(value[:10], "%Y-%m-%d").date()
    serial = observed.year * 12 + observed.month - 1 + months
    return f"{serial // 12:04d}-{serial % 12 + 1:02d}-01"


def percentile_rank(values: list[float], target: float) -> float | None:
    usable = sorted(value for value in values if math.isfinite(value))
    if not usable:
        return None
    return sum(1 for value in usable if value <= target) / len(usable) * 100.0


def parse_finra_workbook(payload: bytes) -> list[dict[str, Any]]:
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(payload)) as workbook:
        root = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
    output: list[dict[str, Any]] = []
    for row in root.findall(".//m:sheetData/m:row", namespace):
        cells: dict[str, str] = {}
        for cell in row.findall("m:c", namespace):
            reference = cell.attrib.get("r", "")
            match = re.match(r"([A-Z]+)", reference)
            if not match:
                continue
            column = match.group(1)
            if cell.attrib.get("t") == "inlineStr":
                value = "".join(node.text or "" for node in cell.findall(".//m:t", namespace))
            else:
                node = cell.find("m:v", namespace)
                value = node.text if node is not None and node.text is not None else ""
            cells[column] = value.strip()
        if not re.fullmatch(r"\d{4}-\d{2}", cells.get("A", "")):
            continue
        debt = finite(cells.get("B"))
        if debt is None:
            continue
        observation = cells["A"] + "-01"
        output.append({
            "date": observation,
            "marginDebtUsdMillions": int(round(debt)),
            "sourceRegime": "finra-all-firms" if observation >= "2010-02-01" else "finra-transition",
        })
    output.sort(key=lambda row: row["date"])
    if not output or output[-1]["date"] < "2020-01-01":
        raise RuntimeError("FINRA workbook did not contain a current monthly series")
    return output


def parse_gdp_csv(payload: bytes) -> list[dict[str, Any]]:
    text = payload.decode("utf-8-sig")
    output: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(text)):
        value = finite(row.get("GDP"))
        observed = row.get("observation_date")
        if value is None or not observed:
            continue
        output.append({"date": observed, "nominalGdpUsdBillions": value})
    if not output:
        raise RuntimeError("FRED GDP series was empty")
    return output


def load_legacy() -> list[dict[str, Any]]:
    payload = json.loads(LEGACY.read_text(encoding="utf-8"))
    rows = payload.get("series") or []
    output = [
        {
            "date": row["date"],
            "marginDebtUsdMillions": int(row["marginDebtUsdMillions"]),
            "sourceRegime": "nyse-member-firms",
        }
        for row in rows
        if row.get("date", "") <= "1996-12-01"
    ]
    if not output or output[0]["date"] != "1959-01-01":
        raise RuntimeError("Legacy NYSE margin-debt cache is missing or incomplete")
    return output


def aligned_gdp(gdp_rows: list[dict[str, Any]], observation: str) -> dict[str, Any] | None:
    observed = datetime.strptime(observation, "%Y-%m-%d").date()
    quarter_month = ((observed.month - 1) // 3) * 3 + 1
    quarter_start = date(observed.year, quarter_month, 1).isoformat()
    eligible = [row for row in gdp_rows if row["date"] <= quarter_start]
    return eligible[-1] if eligible else None


def price_change_through_month(price_series: dict[str, Any] | None, month: str) -> dict[str, Any]:
    history = list((price_series or {}).get("history") or [])
    observed = datetime.strptime(month, "%Y-%m-%d").date()
    next_month = date(observed.year + (1 if observed.month == 12 else 0), 1 if observed.month == 12 else observed.month + 1, 1)
    month_end = next_month - timedelta(days=1)
    current_rows = [row for row in history if row.get("date", "") <= month_end.isoformat() and finite(row.get("close")) is not None]
    if not current_rows:
        return {"date": None, "change12mPct": None}
    current = current_rows[-1]
    prior_cutoff = month_end - timedelta(days=365)
    prior_rows = [row for row in current_rows if row.get("date", "") <= prior_cutoff.isoformat()]
    prior = prior_rows[-1] if prior_rows else None
    return {
        "date": current.get("date"),
        "change12mPct": pct_change(finite(current.get("close")), finite((prior or {}).get("close"))),
    }


def build_margin_debt_history(
    request_fn: Callable[..., bytes],
    sp500_series: dict[str, Any] | None,
) -> dict[str, Any]:
    finra_rows = parse_finra_workbook(request_fn(FINRA_XLSX_URL, timeout=60))
    gdp_rows = parse_gdp_csv(request_fn(GDP_CSV_URL, timeout=45))
    combined = load_legacy() + [row for row in finra_rows if row["date"] >= "1997-01-01"]
    combined.sort(key=lambda row: row["date"])
    debt_by_date = {row["date"]: row["marginDebtUsdMillions"] for row in combined}

    series: list[dict[str, Any]] = []
    for row in combined:
        gdp = aligned_gdp(gdp_rows, row["date"])
        if not gdp:
            continue
        ratio = row["marginDebtUsdMillions"] / (gdp["nominalGdpUsdBillions"] * 1000.0) * 100.0
        prior_debt = debt_by_date.get(month_shift(row["date"], -12))
        series.append({
            **row,
            "nominalGdpDate": gdp["date"],
            "nominalGdpUsdBillions": round(gdp["nominalGdpUsdBillions"], 3),
            "marginDebtToGdpPct": round(ratio, 4),
            "marginDebtChange12mPct": round(pct_change(row["marginDebtUsdMillions"], prior_debt), 3) if prior_debt else None,
        })
    if not series:
        raise RuntimeError("Margin-debt/GDP series could not be built")

    latest = series[-1]
    debt_1m = debt_by_date.get(month_shift(latest["date"], -1))
    debt_3m = debt_by_date.get(month_shift(latest["date"], -3))
    comparable_ratios = [
        row["marginDebtToGdpPct"] for row in series if row["date"] >= "2010-02-01"
    ]
    prior_comparable = [
        row["marginDebtToGdpPct"] for row in series
        if "2010-02-01" <= row["date"] < latest["date"]
    ]
    sp500 = price_change_through_month(sp500_series, latest["date"])
    latest_yoy = finite(latest.get("marginDebtChange12mPct"))
    sp500_yoy = finite(sp500.get("change12mPct"))

    event_dates = [
        ("1968-06-01", "1968年6月"),
        ("1972-12-01", "1972年12月"),
        ("1987-08-01", "1987年8月"),
        ("2000-03-01", "ITバブル・2000年3月"),
        ("2007-07-01", "金融危機前・2007年7月"),
        ("2018-01-01", "2018年1月"),
        ("2021-08-01", "2021年8月"),
        (latest["date"], latest["date"][:7].replace("-", "年") + "月"),
    ]
    series_by_date = {row["date"]: row for row in series}
    events = [
        {
            "date": event_date,
            "label": label,
            "marginDebtToGdpPct": series_by_date[event_date]["marginDebtToGdpPct"],
            "marginDebtUsdMillions": series_by_date[event_date]["marginDebtUsdMillions"],
        }
        for event_date, label in event_dates
        if event_date in series_by_date
    ]

    latest_payload = {
        "date": latest["date"],
        "marginDebtUsdMillions": latest["marginDebtUsdMillions"],
        "marginDebtToGdpPct": latest["marginDebtToGdpPct"],
        "marginDebtChange1mPct": round(pct_change(latest["marginDebtUsdMillions"], debt_1m), 3) if debt_1m else None,
        "marginDebtChange3mPct": round(pct_change(latest["marginDebtUsdMillions"], debt_3m), 3) if debt_3m else None,
        "marginDebtChange12mPct": latest_yoy,
        "ratioPercentileSince2010Pct": round(percentile_rank(comparable_ratios, latest["marginDebtToGdpPct"]), 2),
        "previousComparablePeakPct": round(max(prior_comparable), 4) if prior_comparable else None,
        "nominalGdpDate": latest["nominalGdpDate"],
        "nominalGdpUsdBillions": latest["nominalGdpUsdBillions"],
        "sp500Date": sp500.get("date"),
        "sp500Change12mPct": round(sp500_yoy, 3) if sp500_yoy is not None else None,
        "debtGrowthMinusSp500PctPoints": round(latest_yoy - sp500_yoy, 3) if latest_yoy is not None and sp500_yoy is not None else None,
        "gdpTimingNote": (
            f"信用買い残は{latest['date'][:7]}、分母は公表済みの名目GDP {latest['nominalGdpDate'][:7]}。"
            "GDP未公表の四半期は直前の公表値を使うため暫定比率です。"
        ),
    }

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "title": "U.S. Margin Debt / Nominal GDP",
        "definition": "顧客の証券信用取引口座の借方残高を、米国名目GDPの年率換算値で割った比率。",
        "latest": latest_payload,
        "series": series,
        "events": events,
        "sourceRegimes": [
            {
                "start": "1959-01-01",
                "end": "1996-12-01",
                "label": "NYSE Fact Book・NYSE会員会社",
                "importantLimit": "1983年のRegulation T改訂前後で口座区分が変わり、長期系列は完全に同質ではありません。",
            },
            {
                "start": "1997-01-01",
                "end": "2010-01-01",
                "label": "FINRA配布系列・移行期間",
                "importantLimit": "FINRAの長期配布系列を使用。2010年2月の集計範囲変更より前後を同一母集団とみなしません。",
            },
            {
                "start": "2010-02-01",
                "end": latest["date"],
                "label": "FINRA全会員会社集計",
                "importantLimit": "月次報告方法の変更でも値が動くことがあります。最新順位はこの比較可能期間内で計算します。",
            },
        ],
        "interpretation": {
            "fuel": "比率の高さと信用買い残の増加は、下落時に強制売りへ転じ得る借入ポジションの多さを示します。高いだけでは売りが始まった証拠ではありません。",
            "trigger": "AI顧客の設備投資減速、需要鈍化、投資回収の悪化が価格下落の引き金候補です。半導体株の反発だけでは底を確認しません。",
            "unwind": "信用買い残の急減がVIX・HY OAS・市場の広がり悪化と重なると、単なる評価正常化より強制売り連鎖を疑います。月次統計なので確認は遅れます。",
        },
        "koreaStressCase": {
            "period": "2026-06",
            "forcedLiquidationsKrwTrillions": 1.1228,
            "changeFromPriorMonthPct": 58.6,
            "circuitBreakers": 3,
            "vkospiIntradayHigh": 97.78,
            "meaning": "高い集中とレバレッジのある市場では、下落が追証・強制決済を通じて増幅し得る実例。米国や日本が同じ経路をたどる証明ではありません。",
            "sourceUrl": "https://news.sbs.co.kr/english/endPagePrintPopup.do?news_id=N1008637238",
        },
        "sources": [
            {"label": "FINRA Margin Statistics", "url": FINRA_PAGE_URL},
            {"label": "FINRA downloadable workbook", "url": FINRA_XLSX_URL},
            {"label": "FRED / BEA nominal GDP", "url": GDP_PAGE_URL},
            {"label": "Archived NYSE Fact Book", "url": NYSE_ARCHIVE_URL},
            {"label": "Hussman chart and interpretation", "url": "https://www.advisorperspectives.com/commentaries/2026/07/15/mountain-cliff-ocean"},
        ],
        "limits": [
            "比率は市場規模、家計資産、株式時価総額ではなくGDPで割った一つの尺度です。",
            "FINRA統計に現れないデリバティブ、証券担保融資、海外口座などの全レバレッジは測れません。",
            "信用買い残は株価上昇を追って増えることも多く、単独では暴落時期を予測しません。",
            "最新月の分母は同じ月のGDPではなく、その時点で利用できる直近四半期の年率名目GDPです。",
        ],
    }


def write_margin_debt_history(
    request_fn: Callable[..., bytes],
    sp500_series: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = build_margin_debt_history(request_fn, sp500_series)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    raise SystemExit("Run this module through scripts/update_data.py")
