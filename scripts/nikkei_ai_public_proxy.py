#!/usr/bin/env python3
"""Public-data Nikkei AI-overheat contribution proxy.

The two synthetic paths are deliberately *not* Nikkei indices.  They use
published daily target weights when available and leave every other date
missing; nothing is filled with a zero return or the Nikkei actual path.
"""

from __future__ import annotations

import bisect
import csv
import html
import io
import json
import math
import re
import tempfile
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "nikkei-ai-overheat-config.json"
OUTPUT_PATH = ROOT / "data" / "nikkei-ai-three-series.json"
CACHE_PATH = ROOT / "data" / "nikkei-ai-public-proxy-cache.json"
JST = ZoneInfo("Asia/Tokyo")
USER_AGENT = "mxe050-ai-bubble-monitor/2.0 (https://github.com/mxe050)"
OFFICIAL_DAILY_URL = "https://indexes.nikkei.co.jp/nkave/historical/nikkei_stock_average_daily_en.csv"
OFFICIAL_MONTHLY_URL = "https://indexes.nikkei.co.jp/nkave/historical/nikkei_stock_average_monthly_en.csv"
OFFICIAL_DAILY_PAGE_URL = "https://indexes.nikkei.co.jp/en/nkave/archives/data?list=daily"
OFFICIAL_SUMMARY_URL = "https://indexes.nikkei.co.jp/en/nkave/archives/summary?dt={}&idx=nk225"
TOPIX_HISTORY_URL = "https://finance.yahoo.co.jp/quote/998405.T/history"

FALLBACK_AI = {
    "6857": ("アドバンテスト", "6857.T"),
    "8035": ("東京エレクトロン", "8035.T"),
    "9984": ("ソフトバンクグループ", "9984.T"),
    "6702": ("富士通", "6702.T"),
    "6861": ("キーエンス", "6861.T"),
    "6501": ("日立製作所", "6501.T"),
    "4063": ("信越化学工業", "4063.T"),
    "7741": ("HOYA", "7741.T"),
}
EXTRA = {"285A": ("キオクシアホールディングス", "285A.T")}

# Historical context is intentionally separate from the price/proxy calculation.
# Each item links to a primary source so readers can inspect the original record.
HISTORICAL_EVENTS = (
    {"date": "2016-11-08", "short_label": "米大統領選", "label": "米大統領選（トランプ氏勝利）", "category": "米政権・政策", "note": "米国の財政・通商・金利見通しを市場が見直す転機。", "source_label": "米国国立公文書館・2016年選挙結果", "source_url": "https://www.archives.gov/electoral-college/2016"},
    {"date": "2020-03-11", "short_label": "コロナ", "label": "WHOがCOVID-19をパンデミックと評価", "category": "世界経済", "note": "感染拡大が実体経済・金融市場に急速に波及した局面。", "source_label": "WHO・2020年3月11日会見", "source_url": "https://www.who.int/news-room/speeches/item/who-director-general-s-opening-remarks-at-the-media-briefing-on-covid-19---11-march-2020"},
    {"date": "2022-02-24", "short_label": "ウクライナ", "label": "ロシアによるウクライナへの軍事侵攻", "category": "地政学・資源", "note": "資源価格、インフレ、金融引締めの見通しが焦点化した局面。", "source_label": "国連安全保障理事会・報道資料", "source_url": "https://press.un.org/en/2022/sc14803.doc.htm"},
    {"date": "2022-11-30", "short_label": "ChatGPT", "label": "ChatGPTのresearch preview公開", "category": "生成AI", "note": "生成AIへの注目が企業投資・半導体需要の議論を広げた。", "source_label": "OpenAI・ChatGPT公開", "source_url": "https://openai.com/index/chatgpt/"},
    {"date": "2024-01-01", "short_label": "能登半島地震", "label": "令和6年能登半島地震", "category": "国内災害", "note": "国内の災害リスクを再認識する出来事。", "source_label": "気象庁・令和6年能登半島地震", "source_url": "https://www.jma.go.jp/jma/menu/20240101_noto_jishin.html"},
    {"date": "2024-03-19", "short_label": "日銀政策変更", "label": "日銀が金融政策枠組みを見直し", "category": "日本の金利", "note": "マイナス金利・YCCを含む金融政策の枠組みを見直した。", "source_label": "日本銀行・2024年3月19日公表文", "source_url": "https://www.boj.or.jp/en/mopo/mpmdeci/mpr_2024/k240319a.pdf"},
    {"date": "2024-11-05", "short_label": "米大統領選", "label": "米大統領選（トランプ氏勝利）", "category": "米政権・政策", "note": "次期米政権の政策・通商見通しを市場が再評価する局面。", "source_label": "米国国立公文書館・2024年選挙結果", "source_url": "https://www.archives.gov/electoral-college/2024"},
    {"date": "2025-01-20", "short_label": "トランプ政権", "label": "第2次トランプ政権が発足", "category": "米政権・政策", "note": "新政権の政策実行・対外経済方針を追う起点。", "source_label": "ホワイトハウス・就任演説", "source_url": "https://www.whitehouse.gov/remarks/2025/01/the-inaugural-address/"},
    {"date": "2025-04-02", "short_label": "相互関税", "label": "米国が相互関税の大統領令を公表", "category": "通商政策", "note": "通商政策が世界の供給網・企業収益見通しに影響し得る局面。", "source_label": "ホワイトハウス・大統領令", "source_url": "https://www.whitehouse.gov/presidential-actions/2025/04/regulating-imports-with-a-reciprocal-tariff-to-rectify-trade-practices-that-contribute-to-large-and-persistent-annual-united-states-goods-trade-deficits/"},
)


class ConfigurationError(ValueError):
    pass


def finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def parse_number(value: Any) -> float | None:
    return finite(re.sub(r"[^0-9.+-]", "", str(value or "")))


def pct_change(new: float | None, old: float | None) -> float | None:
    return None if new is None or old in (None, 0) else (new / old - 1) * 100


def normalize_price(actual: float, cap: float | None) -> float:
    """Kept for compatibility; public proxy does not use peer-price caps."""
    return actual if cap is None else min(actual, cap)


def years_before(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def request(url: str, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.8,ja;q=0.7",
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def code(value: Any, field: str) -> str:
    result = str(value or "").strip().upper()
    if not re.fullmatch(r"[0-9A-Z]{4}", result):
        raise ConfigurationError(f"{field} must be a four-character ticker code")
    return result


def code_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ConfigurationError(f"{field} must be a list")
    result = [code(item.get("code") if isinstance(item, dict) else item, f"{field}[{i}]")
              for i, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ConfigurationError(f"{field} contains duplicate codes")
    return result


def validate_config(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ConfigurationError("configuration must be an object")
    required = {
        "method_version", "mode", "lookback_years", "normalization_reference",
        "candidate_universe", "screen", "auto_use_screened_candidates",
        "explicit_keep", "manual_include", "manual_exclude",
    }
    if required - set(payload):
        raise ConfigurationError("configuration keys are incomplete")
    if str(payload["method_version"]) != "2.0":
        raise ConfigurationError("method_version must be 2.0")
    if payload["mode"] not in {"exact_reconstruction", "public_contribution_proxy"}:
        raise ConfigurationError("unsupported mode")
    if isinstance(payload["lookback_years"], bool) or payload["lookback_years"] != 10:
        raise ConfigurationError("lookback_years must be 10")
    if str(payload["normalization_reference"]).upper() != "TOPIX":
        raise ConfigurationError("normalization_reference must be TOPIX")
    universe = payload["candidate_universe"]
    if not isinstance(universe, dict) or not isinstance(universe.get("use_existing_japan_ai_linked"), bool):
        raise ConfigurationError("candidate_universe is invalid")
    screen = payload["screen"]
    keys = {
        "excess_return_vs_topix_36m_pp", "max_rolling_12m_return_pct",
        "peak_nikkei_weight_pct", "price_minus_business_growth_36m_pp",
    }
    if not isinstance(screen, dict):
        raise ConfigurationError("screen must be an object")
    normalized_screen = {}
    for key in keys:
        value = finite(screen.get(key))
        if value is None or value <= 0:
            raise ConfigurationError(f"screen.{key} must be positive")
        normalized_screen[key] = value
    minimum = screen.get("minimum_conditions")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or not 1 <= minimum <= 4:
        raise ConfigurationError("screen.minimum_conditions must be 1..4")
    normalized_screen["minimum_conditions"] = minimum
    keeps = []
    for i, item in enumerate(payload["explicit_keep"]):
        if not isinstance(item, dict):
            raise ConfigurationError(f"explicit_keep[{i}] must be an object")
        item_code = code(item.get("code"), f"explicit_keep[{i}].code")
        name, reason = str(item.get("name") or "").strip(), str(item.get("reason") or "").strip()
        if not name or not reason:
            raise ConfigurationError("explicit_keep requires name and reason")
        keeps.append({"code": item_code, "name": name, "reason": reason})
    if len({item["code"] for item in keeps}) != len(keeps) or "7203" not in {item["code"] for item in keeps}:
        raise ConfigurationError("Toyota 7203 must be unique explicit_keep")
    if not isinstance(payload["auto_use_screened_candidates"], bool):
        raise ConfigurationError("auto_use_screened_candidates must be boolean")
    return {
        **payload,
        "candidate_universe": {
            "use_existing_japan_ai_linked": universe["use_existing_japan_ai_linked"],
            "additional_codes": code_list(universe.get("additional_codes", []), "additional_codes"),
        },
        "screen": normalized_screen,
        "explicit_keep": keeps,
        "manual_include": code_list(payload["manual_include"], "manual_include"),
        "manual_exclude": code_list(payload["manual_exclude"], "manual_exclude"),
    }


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return validate_config(json.loads(path.read_text(encoding="utf-8")))


def fetch_official_csv(url: str) -> list[dict[str, Any]]:
    rows = []
    text = request(url, "text/csv,*/*").decode("cp932", errors="replace")
    for row in csv.DictReader(io.StringIO(text)):
        try:
            observed = datetime.strptime(str(row.get("Date of Data") or row.get("\ufeffDate of Data")), "%Y/%m/%d").date()
        except ValueError:
            continue
        close = parse_number(row.get("Close"))
        if close is not None and close > 0:
            rows.append({"date": observed, "close": close})
    return sorted(rows, key=lambda row: row["date"])


def fetch_yahoo_close(symbol: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=10y&interval=1d&events=div%2Csplits"
    result = json.loads(request(url, "application/json,*/*").decode("utf-8"))["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    rows = []
    for stamp, close in zip(result.get("timestamp") or [], quote.get("close") or []):
        close = finite(close)
        if close is not None and close > 0:
            rows.append({
                "date": datetime.fromtimestamp(stamp, timezone.utc).astimezone(JST).date(),
                "close": close,
            })
    splits = []
    for item in ((result.get("events") or {}).get("splits") or {}).values():
        if item.get("date") is not None:
            splits.append({
                "date": datetime.fromtimestamp(item["date"], timezone.utc).astimezone(JST).date().isoformat(),
                "ratio": str(item.get("splitRatio") or ""),
            })
    return {"rows": sorted(rows, key=lambda row: row["date"]), "split_events": splits,
            "source_url": f"https://finance.yahoo.com/quote/{encoded}/history"}


def text_only(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def parse_summary(text: str, observed: date) -> dict[str, Any]:
    table = re.search(r"Weight\(%\)</th>.*?<tbody>(.*?)</tbody>", text, re.S | re.I)
    weights = {}
    if table:
        for raw in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(1), re.S):
            cells = [text_only(item) for item in re.findall(r"<td[^>]*>(.*?)</td>", raw, re.S)]
            if len(cells) >= 2 and re.fullmatch(r"[0-9A-Z]{4}", cells[1].upper()):
                weight = parse_number(cells[-1])
                if weight is not None:
                    weights[cells[1].upper()] = weight / 100
    divisor = re.search(r"<th[^>]*>\s*Divisor\s*</th>\s*<td[^>]*class=\"value\"[^>]*>(.*?)</td>", text, re.S | re.I)
    divisor_value = parse_number(text_only(divisor.group(1))) if divisor else None
    if not weights or divisor_value is None or divisor_value <= 0:
        raise RuntimeError(f"Daily Summary parse failed: {observed.isoformat()}")
    return {
        "date": observed.isoformat(), "weights": weights, "divisor": divisor_value,
        "weight_source": "official_daily_summary_top10",
        "source_url": OFFICIAL_SUMMARY_URL.format(observed.strftime("%m%d%Y")),
    }


def cache_load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("official_daily_summaries", {}) if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def cache_write(path: Path, rows: dict[str, Any]) -> None:
    atomic_write_json(path, {
        "schema_version": "1.0",
        "updated_at": datetime.now(JST).replace(microsecond=0).isoformat(),
        "official_daily_summaries": {key: rows[key] for key in sorted(rows)},
    })


def fetch_summaries(days: list[date], cache: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    result, errors = dict(cache), []
    wanted = [item for item in days if item.isoformat() not in result]
    def one(item: date) -> dict[str, Any]:
        url = OFFICIAL_SUMMARY_URL.format(item.strftime("%m%d%Y"))
        return parse_summary(request(url, "text/html,*/*").decode("utf-8", errors="replace"), item)
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(one, item): item for item in wanted}
        for job in as_completed(jobs):
            item = jobs[job]
            try:
                result[item.isoformat()] = job.result()
            except Exception as exc:
                errors.append(f"{item.isoformat()}: {exc}")
    return result, errors


def topix_page_rows(text: str) -> list[dict[str, Any]]:
    output = []
    for raw_date, body in re.findall(r"<tr[^>]*>\s*<th[^>]*>(20\d{2}/\d{1,2}/\d{1,2})</th>(.*?)</tr>", text, re.S):
        numbers = re.findall(r'<span[^>]*_StyledNumber__value[^>]*>([^<]+)</span>', body, re.S)
        try:
            observed = datetime.strptime(raw_date, "%Y/%m/%d").date()
        except ValueError:
            continue
        close = parse_number(numbers[-1]) if numbers else None
        if close is not None and close > 0:
            output.append({"date": observed, "close": close})
    return output


def fetch_topix(start: date, end: date) -> list[dict[str, Any]]:
    def url(page: int) -> str:
        return f"{TOPIX_HISTORY_URL}?from={start:%Y%m%d}&to={(end + timedelta(days=1)):%Y%m%d}&term=d&page={page}"
    def one(page: int) -> tuple[int, list[dict[str, Any]], int | None]:
        text = request(url(page), "text/html,*/*").decode("utf-8", errors="replace")
        if page == 1:
            fragment = text[text.find("historyTable"):]
            match = re.search(r'\\"totalPage\\":(\d+)', fragment) or re.search(r'"totalPage":(\d+)', fragment)
            if not match:
                raise RuntimeError("TOPIX page count unavailable")
            return page, topix_page_rows(text), int(match.group(1))
        return page, topix_page_rows(text), None
    _, initial, pages = one(1)
    if pages is None or not 1 <= pages <= 80:
        raise RuntimeError("TOPIX page count is invalid")
    merged = {item["date"]: item["close"] for item in initial}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(one, page) for page in range(2, pages + 1)]
        for job in as_completed(jobs):
            _, rows, _ = job.result()
            merged.update({item["date"]: item["close"] for item in rows})
    rows = [{"date": key, "close": value} for key, value in sorted(merged.items()) if start <= key <= end]
    if len(rows) < 500:
        raise RuntimeError("TOPIX history is shorter than 36 months")
    return rows


def rows_map(rows: Any) -> dict[date, float]:
    result = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            observed = row["date"] if isinstance(row["date"], date) else date.fromisoformat(str(row["date"]))
        except (KeyError, ValueError):
            continue
        close = finite(row.get("close"))
        if close is not None and close > 0:
            result[observed] = close
    return result


def prior(values: dict[date, float], target: date, gap: int = 10) -> tuple[date | None, float | None]:
    days = sorted(values)
    index = bisect.bisect_right(days, target) - 1
    if index < 0 or (target - days[index]).days > gap:
        return None, None
    return days[index], values[days[index]]


def catalog(config: dict[str, Any]) -> list[dict[str, str]]:
    result = {}
    if config["candidate_universe"]["use_existing_japan_ai_linked"]:
        try:
            from update_data import COMPANIES
            for symbol, profile in COMPANIES.items():
                if profile.get("category") == "japan-ai":
                    item_code = str(profile.get("displayTicker") or symbol.replace(".T", "")).upper()
                    result[item_code] = {
                        "code": item_code, "name": str(profile.get("name") or item_code),
                        "symbol": symbol, "universe_source": "既存の日本・AI連動監視群",
                    }
        except Exception:
            for item_code, (name, symbol) in FALLBACK_AI.items():
                result[item_code] = {"code": item_code, "name": name, "symbol": symbol,
                                     "universe_source": "既存の日本・AI連動監視群"}
    for item_code in config["candidate_universe"]["additional_codes"] + config["manual_include"] + config["manual_exclude"]:
        name, symbol = EXTRA.get(item_code, FALLBACK_AI.get(item_code, (item_code, f"{item_code}.T")))
        result.setdefault(item_code, {"code": item_code, "name": name, "symbol": symbol,
                                      "universe_source": "設定で追加・手動指定した候補"})
    return list(result.values())


def summary_map(source: Any) -> dict[date, dict[str, Any]]:
    result = {}
    for raw_day, raw in (source or {}).items():
        try:
            observed = raw_day if isinstance(raw_day, date) else date.fromisoformat(str(raw_day))
        except ValueError:
            continue
        if not isinstance(raw, dict):
            continue
        weights = {}
        for item_code, value in (raw.get("weights") or {}).items():
            value = finite(value)
            if value is not None and 0 <= value < 1 and re.fullmatch(r"[0-9A-Z]{4}", str(item_code).upper()):
                weights[str(item_code).upper()] = value
        result[observed] = {
            **raw, "weights": weights,
            "confirmed_non_members": [str(value).upper() for value in raw.get("confirmed_non_members", [])],
        }
    return result


def weight(summary: dict[str, Any] | None, item_code: str) -> tuple[float | None, str]:
    if summary is None:
        return None, "missing"
    value = finite((summary.get("weights") or {}).get(item_code))
    if value is not None and 0 <= value <= 1:
        return value, "exact"
    # A zero is valid only for an explicitly supplied historical non-member flag.
    if item_code in set(summary.get("confirmed_non_members") or []):
        return 0.0, "exact"
    return None, "missing"


def screen_one(item: dict[str, str], end: date, topix: dict[date, float], prices: dict[date, float],
               summaries: dict[date, dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    start = years_before(end, 3)
    _, close0 = prior(prices, start)
    _, close1 = prior(prices, end)
    _, topix0 = prior(topix, start)
    _, topix1 = prior(topix, end)
    stock_return, topix_return = pct_change(close1, close0), pct_change(topix1, topix0)
    excess = stock_return - topix_return if stock_return is not None and topix_return is not None else None
    rolling = []
    for observed, current in prices.items():
        if start <= observed <= end:
            _, old = prior(prices, years_before(observed, 1))
            change = pct_change(current, old)
            if change is not None:
                rolling.append(change)
    observations = [(observed, weight(summary, item["code"])[0]) for observed, summary in summaries.items()]
    observations = [(observed, value) for observed, value in observations if value is not None]
    peak = max((value for _, value in observations), default=None)
    current_weight, _ = weight(summaries.get(end), item["code"])
    thresholds = config["screen"]
    def cond(value: float | None, threshold: float, label: str) -> dict[str, Any]:
        return {"value": round(value, 6) if value is not None else None, "threshold": threshold,
                "met": value >= threshold if value is not None else None, "label": label}
    conditions = {
        "A": cond(excess, thresholds["excess_return_vs_topix_36m_pp"], "36か月騰落率－TOPIX"),
        "B": cond(max(rolling) if rolling else None, thresholds["max_rolling_12m_return_pct"], "最大12か月騰落率"),
        "C": cond(peak * 100 if peak is not None else None, thresholds["peak_nikkei_weight_pct"], "ピーク日経ウエート"),
        "D": cond(None, thresholds["price_minus_business_growth_36m_pp"], "株価－売上/評価用FCF成長率"),
    }
    hit = [key for key, value in conditions.items() if value["met"] is True]
    keeps, excluded, included = ({row["code"] for row in config["explicit_keep"]},
                                  set(config["manual_exclude"]), set(config["manual_include"]))
    if item["code"] in keeps:
        status, reason = "explicit_keep", "explicit_keepが最優先のため除外しない"
    elif item["code"] in excluded:
        status, reason = "manual_exclude", "manual_excludeで対象外"
    elif item["code"] in included:
        status, reason = "manual_include", "manual_includeで対象に指定"
    elif config["auto_use_screened_candidates"] and len(hit) >= thresholds["minimum_conditions"]:
        status, reason = "auto_screened_provisional", f"{len(hit)}条件が該当"
    else:
        status, reason = "not_selected", f"該当{len(hit)}条件（必要数{thresholds['minimum_conditions']}）"
    return {
        **item, "status": status, "selection_reason": reason,
        "selected_for_proxy": status in {"auto_screened_provisional", "manual_include"},
        "screen_period_start": start.isoformat(), "screen_period_end": end.isoformat(),
        "price_return_36m_pct": round(stock_return, 6) if stock_return is not None else None,
        "topix_return_36m_pct": round(topix_return, 6) if topix_return is not None else None,
        "business_growth_36m_pct": None, "conditions": conditions, "passed_conditions": hit,
        "passed_condition_count": len(hit),
        "current_nikkei_weight_pct": current_weight * 100 if current_weight is not None else None,
        "peak_nikkei_weight_pct": peak * 100 if peak is not None else None,
        "peak_nikkei_weight_date": max(observations, key=lambda row: row[1])[0].isoformat() if observations else None,
        "weight_observation_count": len(observations),
        "weight_method": "日経公式Daily Summary上位10銘柄掲載値。未掲載日は0ではなくmissing。",
        "data_status": "D条件の一貫した36か月売上・評価用FCF成長率は未接続。",
    }


def proxy_rows(actual: list[dict[str, Any]], topix: dict[date, float], prices: dict[str, dict[date, float]],
               summaries: dict[date, dict[str, Any]], targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result, codes = [], [item["code"] for item in targets]
    for previous, current in zip(actual, actual[1:]):
        items, missing = {}, []
        for item_code in codes:
            value, source = weight(summaries.get(previous["date"]), item_code)
            if value is None:
                missing.append(f"{item_code}の前営業日ウエート")
            else:
                items[item_code] = value
            if previous["date"] not in prices[item_code] or current["date"] not in prices[item_code]:
                missing.append(f"{item_code}のClose")
        if previous["date"] not in topix or current["date"] not in topix:
            missing.append("TOPIX Close")
        if missing:
            result.append({"date": current["date"], "previous_date": previous["date"], "computed": False,
                           "quality": "missing", "missing": sorted(set(missing))})
            continue
        total = sum(items.values())
        if total >= 1:
            result.append({"date": current["date"], "previous_date": previous["date"], "computed": False,
                           "quality": "missing", "missing": ["対象ウエート合計が1以上でrExcludedの分母が0以下"],
                           "combined_weight": total})
            continue
        returns = {item_code: prices[item_code][current["date"]] / prices[item_code][previous["date"]] - 1
                   for item_code in codes}
        nikkei = current["close"] / previous["close"] - 1
        market = topix[current["date"]] / topix[previous["date"]] - 1
        contribution = sum(items[key] * returns[key] for key in codes)
        result.append({
            "date": current["date"], "previous_date": previous["date"], "computed": True, "quality": "exact",
            "nikkei_return": nikkei, "normalized_return": nikkei + sum(items[key] * (market - returns[key]) for key in codes),
            "excluded_return": (nikkei - contribution) / (1 - total),
            "combined_weight": total, "target_contribution": contribution, "weights": items,
        })
    return result


def segments(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    output, current = [], []
    for row in rows:
        if row["computed"]:
            current.append(row)
        elif current:
            output.append(current)
            current = []
    if current:
        output.append(current)
    return output


def weekly(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    picked = {}
    for row in rows:
        picked[row["date"].isocalendar()[:2]] = row
    output = [picked[key] for key in sorted(picked)]
    if rows and output[0]["date"] != rows[0]["date"]:
        output.insert(0, rows[0])
    if rows and output[-1]["date"] != rows[-1]["date"]:
        output.append(rows[-1])
    return output


def full_actual(actual: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = actual[0]["close"]
    rows = [{"date": item["date"], "nikkei_actual": 100 * item["close"] / base, "nikkei_close": item["close"]}
            for item in actual]
    return [{"date": item["date"].isoformat(), "nikkei_actual": round(item["nikkei_actual"], 6),
             "nikkei_close": round(item["nikkei_close"], 2)} for item in weekly(rows)]


def make_segment(segment: list[dict[str, Any]], closes: dict[date, float]) -> list[dict[str, Any]]:
    base_date, actual, normalized, excluded = segment[0]["previous_date"], 100.0, 100.0, 100.0
    base_close = closes[base_date]
    rows = [{
        "date": base_date,
        "nikkei_actual": actual,
        "ai_overheat_normalized": normalized,
        "ai_overheat_excluded": excluded,
        "nikkei_close": base_close,
        "ai_overheat_normalized_close": base_close,
        "ai_overheat_excluded_close": base_close,
        "quality": "exact",
    }]
    for item in segment:
        actual *= 1 + item["nikkei_return"]
        normalized *= 1 + item["normalized_return"]
        excluded *= 1 + item["excluded_return"]
        rows.append({
            "date": item["date"],
            "nikkei_actual": actual,
            "ai_overheat_normalized": normalized,
            "ai_overheat_excluded": excluded,
            "nikkei_close": closes[item["date"]],
            "ai_overheat_normalized_close": base_close * normalized / 100,
            "ai_overheat_excluded_close": base_close * excluded / 100,
            "quality": item["quality"],
            "combined_weight_pct": item["combined_weight"] * 100,
            "actual_minus_normalized": actual - normalized,
            "normalized_minus_excluded": normalized - excluded,
        })
    output = []
    for item in weekly(rows):
        output.append({
            "date": item["date"].isoformat(), "nikkei_actual": round(item["nikkei_actual"], 6),
            "ai_overheat_normalized": round(item["ai_overheat_normalized"], 6),
            "ai_overheat_excluded": round(item["ai_overheat_excluded"], 6),
            "nikkei_close": round(item["nikkei_close"], 2),
            "ai_overheat_normalized_close": round(item["ai_overheat_normalized_close"], 2),
            "ai_overheat_excluded_close": round(item["ai_overheat_excluded_close"], 2),
            "quality": item["quality"],
            "combined_weight_pct": round(item["combined_weight_pct"], 6) if finite(item.get("combined_weight_pct")) is not None else None,
            "actual_minus_normalized": round(item["actual_minus_normalized"], 6) if finite(item.get("actual_minus_normalized")) is not None else None,
            "normalized_minus_excluded": round(item["normalized_minus_excluded"], 6) if finite(item.get("normalized_minus_excluded")) is not None else None,
        })
    return output


def only_actual(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        **row,
        "ai_overheat_normalized": None,
        "ai_overheat_excluded": None,
        "ai_overheat_normalized_close": None,
        "ai_overheat_excluded_close": None,
        "actual_minus_normalized": None,
        "normalized_minus_excluded": None,
        "quality": "actual_only",
        "combined_weight_pct": None,
    } for row in rows]


def monthly_check(values: dict[date, float], monthly: list[dict[str, Any]], start: date) -> dict[str, Any]:
    ends = {(item.year, item.month): value for item, value in values.items()}
    errors, missing = [], []
    for row in monthly:
        if row["date"] < start:
            continue
        value = ends.get((row["date"].year, row["date"].month))
        if value is None:
            missing.append(row["date"].isoformat())
        else:
            errors.append(abs(value - row["close"]))
    return {"matched_months": len(errors), "missing_months": missing,
            "max_abs_error_jpy": max(errors) if errors else None,
            "within_0_02_jpy": bool(errors) and max(errors) <= .02}


def json_is_finite(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, list):
        return all(json_is_finite(item) for item in value)
    return isinstance(value, dict) and all(json_is_finite(item) for item in value.values())


def build_payload(config: dict[str, Any], *, yahoo_rows: list[dict[str, Any]], official_daily: list[dict[str, Any]],
                  official_monthly: list[dict[str, Any]], topix_rows: list[dict[str, Any]] | None = None,
                  candidate_prices: dict[str, Any] | None = None, official_summaries: dict[Any, Any] | None = None,
                  candidate_catalog: list[dict[str, str]] | None = None, generated_at: datetime | None = None) -> dict[str, Any]:
    daily, monthly = rows_map(official_daily), rows_map(official_monthly)
    if not daily:
        raise RuntimeError("official Nikkei daily data is missing")
    end, floor = max(daily), years_before(max(daily), 10)
    merged = {key: value for key, value in rows_map(yahoo_rows).items() if floor <= key <= end}
    merged.update({key: value for key, value in daily.items() if floor <= key <= end})
    actual = [{"date": key, "close": value} for key, value in sorted(merged.items())]
    if len(actual) < 1000:
        raise RuntimeError("10-year Nikkei actual history is incomplete")
    cross = monthly_check(merged, [{"date": key, "close": value} for key, value in monthly.items()], actual[0]["date"])
    if cross["matched_months"] < 100:
        raise RuntimeError("monthly Nikkei cross-check is incomplete")
    topix, summaries = rows_map(topix_rows), summary_map(official_summaries)
    candidates = candidate_catalog or catalog(config)
    price_inputs = candidate_prices or {}
    prices = {item["code"]: rows_map((price_inputs.get(item["code"]) or {}).get("rows")
                                    if isinstance(price_inputs.get(item["code"]), dict)
                                    else price_inputs.get(item["code"]))
              for item in candidates}
    screened = [screen_one(item, end, topix, prices[item["code"]], summaries, config) for item in candidates]
    targets = [item for item in screened if item["selected_for_proxy"]]
    actual_series = full_actual(actual)
    calculations = proxy_rows(actual, topix, prices, summaries, targets) if targets and config["mode"] == "public_contribution_proxy" else []
    good, blocks = [item for item in calculations if item["computed"]], segments(calculations)
    total_days, coverage = len(actual) - 1, (100 * len(good) / (len(actual) - 1) if len(actual) > 1 else 0)
    selected = max(blocks, key=len) if blocks else []
    if config["mode"] == "exact_reconstruction":
        status, warning, display = "data-insufficient-exact-reconstruction-inputs", "ライセンス済みの日次構成・PAF/CPAF・除数が未接続のため、exact_reconstructionは実績のみです。", only_actual(actual_series)
    elif not targets:
        status, warning, display = "actual-only-no-screened-candidates", "現在の運用基準を満たすAI過熱候補はありません。日経平均の実績のみを表示します。", only_actual(actual_series)
    elif not selected:
        status, warning, display = "data-insufficient-public-proxy-inputs", "候補は抽出されましたが、必要な公開入力が連続してそろわないため実績のみを表示します。", only_actual(actual_series)
    else:
        status, warning, display = "public-contribution-proxy", "2本の合成系列は公式の日経平均ではありません。公開データから対象銘柄の日次寄与を調整した研究用proxyです。", make_segment(selected, {item["date"]: item["close"] for item in actual})
    max_weight = max((item.get("combined_weight") for item in good), default=None)
    latest_weight = None
    if targets:
        latest = [weight(summaries.get(end), item["code"])[0] for item in targets]
        latest_weight = sum(latest) if all(item is not None for item in latest) else None
    has_proxy = bool(selected and display[-1]["ai_overheat_normalized"] is not None)
    comp_actual = display[-1]["nikkei_actual"] - 100 if has_proxy else None
    normalized = display[-1]["ai_overheat_normalized"] - 100 if has_proxy else None
    excluded = display[-1]["ai_overheat_excluded"] - 100 if has_proxy else None
    missing_dates = [item["date"].isoformat() for item in calculations if not item["computed"]]
    if not targets:
        missing_dates = [item["date"].isoformat() for item in actual[1:]]
    exact = sum(item["quality"] == "exact" for item in good)
    reconstructed = sum(item["quality"] == "reconstructed" for item in good)
    legacy = sum(item["quality"] == "legacy_reconstructed" for item in good)
    full_visible = bool(has_proxy and coverage >= 90 and display[0]["date"] == actual_series[0]["date"] and display[-1]["date"] == actual_series[-1]["date"])
    latest_display = display[-1] if display else {}
    proxy_base_close = finite(display[0].get("nikkei_close")) if display else None
    latest_actual_close = finite(latest_display.get("nikkei_close"))
    latest_normalized_close = finite(latest_display.get("ai_overheat_normalized_close"))
    latest_excluded_close = finite(latest_display.get("ai_overheat_excluded_close"))
    actual_minus_normalized_jpy = (
        latest_actual_close - latest_normalized_close
        if latest_actual_close is not None and latest_normalized_close is not None
        else None
    )
    actual_minus_excluded_jpy = (
        latest_actual_close - latest_excluded_close
        if latest_actual_close is not None and latest_excluded_close is not None
        else None
    )
    historical_events = [dict(item) for item in HISTORICAL_EVENTS if item["date"] <= end.isoformat()]
    payload = {
        "meta": {
            "title": "日経平均からAI過熱候補の寄与を分ける",
            "generated_at": (generated_at or datetime.now(JST)).astimezone(JST).replace(microsecond=0).isoformat(),
            "market_date": end.isoformat(), "start_date": actual[0]["date"].isoformat(), "end_date": end.isoformat(),
            "display_start_date": display[0]["date"], "display_end_date": display[-1]["date"],
            "proxy_base_close": round(proxy_base_close, 2) if proxy_base_close is not None else None,
            "base_value": 100, "calculation_frequency": "daily", "display_frequency": "weekly",
            "nominal_chart_unit": "JPY", "nominal_chart_description": "日経平均の10年実績は円建て。2本のproxyは比較開始日の実額を基準に円換算し、利用可能な連続区間だけを表示する。",
            "dividends_included": False, "price_field": "Close（配当調整済みAdj Closeは使用しない。株式分割だけを機械調整として扱う）",
            "mode": config["mode"], "normalization_reference": "TOPIX", "synthetic_series_are_official": False,
            "method_label": "公開データによる日次寄与調整proxy" if status == "public-contribution-proxy" else "実績のみ / データ状態を確認",
            "comparison_status": status, "official_daily_available_from": min(daily).isoformat(),
            "official_monthly_available_from": min(monthly).isoformat(),
            "proxy_disclaimer": "2本の合成系列は公式の日経平均ではありません。公開データから対象銘柄の日次寄与を調整した研究用proxyです。",
        },
        "summary": {
            "actual_full_period_return_pct": round(actual_series[-1]["nikkei_actual"] - 100, 6),
            "comparison_actual_return_pct": round(comp_actual, 6) if comp_actual is not None else None,
            "normalized_return_pct": round(normalized, 6) if normalized is not None else None,
            "excluded_return_pct": round(excluded, 6) if excluded is not None else None,
            "latest_actual_close": round(latest_actual_close, 2) if latest_actual_close is not None else None,
            "latest_normalized_close": round(latest_normalized_close, 2) if latest_normalized_close is not None else None,
            "latest_excluded_close": round(latest_excluded_close, 2) if latest_excluded_close is not None else None,
            "actual_minus_normalized_jpy": round(actual_minus_normalized_jpy, 2) if actual_minus_normalized_jpy is not None else None,
            "actual_minus_excluded_jpy": round(actual_minus_excluded_jpy, 2) if actual_minus_excluded_jpy is not None else None,
            "ai_excess_contribution_percentage_points": round(comp_actual - normalized, 6) if comp_actual is not None and normalized is not None else None,
            "retained_normal_contribution_percentage_points": round(normalized - excluded, 6) if normalized is not None and excluded is not None else None,
            "candidate_count": len(screened), "selected_candidate_count": len(targets),
            "current_combined_weight_pct": round(latest_weight * 100, 6) if latest_weight is not None else None,
            "peak_combined_weight_pct": round(max_weight * 100, 6) if max_weight is not None else None,
            "full_period_returns_visible": full_visible,
        },
        "quality": {
            "coverage_pct": round(coverage, 6), "coverage_status": "normal" if coverage >= 95 else "caution" if coverage >= 90 else "partial",
            "full_period_returns_visible": full_visible, "calculation_day_count": total_days,
            "valid_proxy_day_count": len(good), "missing_date_count": len(missing_dates), "missing_dates": missing_dates,
            "day_counts": {"exact": exact, "reconstructed": reconstructed, "legacy_reconstructed": legacy, "missing": total_days - len(good)},
            "maximum_combined_weight_pct": round(max_weight * 100, 6) if max_weight is not None else None,
            "current_combined_weight_pct": round(latest_weight * 100, 6) if latest_weight is not None else None,
            "proxy_data_available_from": min(summaries).isoformat() if summaries else None,
            "proxy_data_available_to": max(summaries).isoformat() if summaries else None,
            "proxy_segments": [{"start_date": block[0]["previous_date"].isoformat(), "end_date": block[-1]["date"].isoformat(), "return_day_count": len(block)} for block in blocks],
            "weight_method": "日経公式Daily Summary掲載の上位10銘柄日次ウエート。未掲載は0ではなくmissing。PAF/CPAF再構成は未使用。",
            "price_method": "Yahoo Finance Close。配当調整済みAdj Closeは使わず、株式分割イベントを取得して終値系列の連続性を確認する。",
            "membership_handling": "日経平均への採用・除外が公式に確認できる期間だけウエート0とする。Daily Summaryの上位10銘柄に未掲載なだけの銘柄はmissingのままにする。",
            "candidate_price_audit": [
                {"code": item["code"],
                 "source_url": (price_inputs.get(item["code"]) or {}).get("source_url") if isinstance(price_inputs.get(item["code"]), dict) else None,
                 "split_events": (price_inputs.get(item["code"]) or {}).get("split_events", []) if isinstance(price_inputs.get(item["code"]), dict) else []}
                for item in candidates
            ],
            "monthly_crosscheck": cross, "data_state": status,
            "missing_items": ["10年全期間の対象銘柄別日次ウエート", "対象銘柄の日経平均採用・除外日の完全履歴", "PAF/CPAFまたは2021年9月以前のみなし額面相当係数", "D条件用の一貫した36か月売上・評価用FCF成長率"],
        },
        "selection_config": {"method_version": config["method_version"], "mode": config["mode"], "screen": config["screen"], "auto_use_screened_candidates": config["auto_use_screened_candidates"]},
        "candidates": screened, "selected_candidates": targets, "explicit_keep": config["explicit_keep"],
        "historical_events": historical_events,
        "actual_series": actual_series, "series": display, "warnings": [warning],
        "sources": [
            {"label": "日経公式・Daily Summary", "url": "https://indexes.nikkei.co.jp/en/nkave/archives/summary", "used_for": "対象候補の公開日次ウエートと日次除数"},
            {"label": "日経公式・日次終値", "url": OFFICIAL_DAILY_PAGE_URL, "used_for": "直近の公式日次終値"},
            {"label": "日経公式・月次終値CSV", "url": OFFICIAL_MONTHLY_URL, "used_for": "10年実績系列の月次クロスチェック"},
            {"label": "Yahoo Finance ^N225", "url": "https://finance.yahoo.com/quote/%5EN225/history", "used_for": "10年の日付付きClose"},
            {"label": "Yahoo!ファイナンス TOPIX", "url": TOPIX_HISTORY_URL, "used_for": "TOPIXの日次Close"},
            {"label": "AI過熱候補の設定", "url": "https://github.com/mxe050/ai-bubble-collapse-monitor/blob/main/config/nikkei-ai-overheat-config.json", "used_for": "候補ユニバースと抽出規則"},
        ],
    }
    if not json_is_finite(payload):
        raise RuntimeError("payload contains NaN or Infinity")
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        temporary = Path(handle.name)
    temporary.replace(path)


def write_nikkei_ai_three_series(config_path: Path = CONFIG_PATH, output_path: Path = OUTPUT_PATH,
                                 cache_path: Path = CACHE_PATH) -> dict[str, Any]:
    config, nikkei = load_config(config_path), fetch_yahoo_close("^N225")
    daily, monthly = fetch_official_csv(OFFICIAL_DAILY_URL), fetch_official_csv(OFFICIAL_MONTHLY_URL)
    end, start = max(item["date"] for item in daily), years_before(max(item["date"] for item in daily), 3) - timedelta(days=5)
    topix, candidates = fetch_topix(start, end), catalog(config)
    prices, price_errors = {}, []
    for item in candidates:
        try:
            prices[item["code"]] = fetch_yahoo_close(item["symbol"])
        except Exception as exc:
            prices[item["code"]] = {"rows": []}
            price_errors.append(f"{item['code']} Close: {exc}")
    old = cache_load(cache_path)
    summaries, summary_errors = fetch_summaries([item["date"] for item in daily if start <= item["date"] <= end], old)
    if summaries != old:
        cache_write(cache_path, summaries)
    payload = build_payload(config, yahoo_rows=nikkei["rows"], official_daily=daily, official_monthly=monthly,
                            topix_rows=topix, candidate_prices=prices, official_summaries=summaries,
                            candidate_catalog=candidates)
    if price_errors or summary_errors:
        payload["warnings"].append("一部の公開入力を取得できませんでした。該当日はmissingのままとし、0・補間・実績同値で埋めていません。")
        payload["quality"]["fetch_errors"] = (price_errors + summary_errors)[:100]
    atomic_write_json(output_path, payload)
    return payload
