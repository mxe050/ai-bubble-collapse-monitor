#!/usr/bin/env python3
"""Build the lightweight, frequently refreshed market-intelligence package.

The long-form monitor is intentionally rebuilt less often.  This module only
collects inputs that matter between cash-market closes: intraday prices,
official releases, overseas news discovery, and clearly labelled social
signals.  It never treats a social post or a price move as proof of intervention.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "live-intelligence.json"
USER_AGENT = "mxe050-ai-bubble-monitor-live/1.0 (https://github.com/mxe050)"
JST = timezone(timedelta(hours=9))
BRIEFING_ITEM_LIMIT = 16

MOF_INTERVENTION_URL = "https://www.mof.go.jp/policy/international_policy/reference/feio/index.html"

INTRADAY_INSTRUMENTS: dict[str, dict[str, str]] = {
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

OFFICIAL_FEEDS = (
    {
        "name": "Federal Reserve",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "kind": "official-us",
    },
    {
        "name": "Federal Reserve speeches",
        "url": "https://www.federalreserve.gov/feeds/speeches.xml",
        "kind": "official-us",
    },
    {
        "name": "U.S. Treasury",
        "url": "https://home.treasury.gov/news/press-releases",
        "kind": "official-us",
        "format": "html-links",
    },
    {
        "name": "The White House",
        "url": "https://www.whitehouse.gov/news/feed/",
        "kind": "official-us",
    },
    {
        "name": "Bank of Japan",
        "url": "https://www.boj.or.jp/rss/whatsnew.xml",
        "kind": "official-japan",
    },
    {
        "name": "財務省",
        "url": "https://www.mof.go.jp/news.rss",
        "kind": "official-japan",
    },
)

NEWS_QUERIES = (
    {
        "key": "fx-rates",
        "query": '(USDJPY OR yen OR dollar) (intervention OR "Bank of Japan" OR rates)',
    },
    {
        "key": "us-stocks",
        "query": '("S&P 500" OR Nasdaq OR "Wall Street") (rally OR selloff OR earnings OR outlook)',
    },
    {
        "key": "japan-stocks",
        "query": '(Nikkei OR TOPIX OR "Japan stocks") (futures OR rally OR selloff OR outlook)',
    },
    {
        "key": "ai-bubble",
        "query": '("AI bubble" OR "AI stocks" OR semiconductor) (valuation OR capex OR earnings OR crash)',
    },
    {
        "key": "policy",
        "query": '("Federal Reserve" OR FOMC OR Treasury OR "White House") (markets OR rates OR tariffs)',
    },
    {
        "key": "economists",
        "query": '("Mohamed El-Erian" OR "Jason Furman" OR "Claudia Sahm" OR "Liz Ann Sonders" OR "Jim Bianco") (markets OR economy OR rates)',
    },
)

PUBLIC_SOCIAL_SEARCHES = (
    {
        "name": "X 公開ウェブ索引",
        "kind": "x-index",
        "requiredHost": "x.com",
        "query": (
            'site:x.com (federalreserve OR USTreasury OR WhiteHouse OR POTUS OR '
            'realDonaldTrump OR elerianm OR LizAnnSonders OR jasonfurman OR '
            'Claudia_Sahm OR BiancoResearch OR charliebilello) '
            '(USDJPY OR stocks OR "AI bubble" OR rates)'
        ),
    },
    {
        "name": "LinkedIn 公開ウェブ索引",
        "kind": "linkedin",
        "requiredHost": "linkedin.com",
        "query": (
            'site:linkedin.com/posts ("Mohamed El-Erian" OR "Jason Furman" OR '
            '"Claudia Sahm" OR "Liz Ann Sonders" OR "Jim Bianco") '
            '(markets OR economy OR "AI bubble" OR rates)'
        ),
    },
)

TOPICS: dict[str, dict[str, Any]] = {
    "fx-rates": {
        "label": "為替・金利",
        "terms": (
            "usd/jpy", "usdjpy", "yen", "円", "dollar", "fx", "foreign exchange",
            "intervention", "介入", "rate", "yield", "bond", "boj", "bank of japan",
            "fomc", "federal reserve", "treasury",
        ),
    },
    "ai-bubble": {
        "label": "AIバブル",
        "terms": (
            "ai bubble", "artificial intelligence", "生成ai", "semiconductor", "nvidia",
            "gpu", "data center", "datacenter", "capex", "hyperscaler", "openai", "anthropic",
        ),
    },
    "japan-stocks": {
        "label": "日本株",
        "terms": (
            "nikkei", "topix", "japan stock", "japanese stock", "東証", "日経",
            "日本株", "softbank", "tokyo electron",
        ),
    },
    "us-stocks": {
        "label": "米国株",
        "terms": (
            "s&p", "nasdaq", "dow", "wall street", "u.s. stock", "us stock",
            "american stock", "russell", "equities", "earnings",
        ),
    },
    "policy": {
        "label": "政策・政府",
        "terms": (
            "white house", "president trump", "donald trump", "tariff", "sanction",
            "regulation", "government", "ministry of finance", "財務省", "fiscal",
        ),
    },
}

BULL_TERMS = (
    "rally", "surge", "gain", "record high", "beat estimates", "strong growth",
    "soft landing", "rate cut", "easing", "bullish", "upside", "rebound", "optimistic",
    "profit growth", "収益化", "増益", "上昇", "反発", "強気", "追い風",
)
BEAR_TERMS = (
    "selloff", "plunge", "slump", "drop", "crash", "bubble", "recession", "warning",
    "weak", "downside", "bearish", "rate hike", "inflation", "tariff", "credit stress",
    "cash burn", "expenses", "cost burden", "spending burden", "valuation concern",
    "cash flow pressure", "圧迫", "警戒", "負担", "下落", "懸念", "弱気", "逆風",
)
MARKET_RELEVANCE_TERMS = tuple(
    dict.fromkeys(term for profile in TOPICS.values() for term in profile["terms"])
)
OFFICIAL_MARKET_TERMS = (
    "stock market", "equity market", "financial market", "market conditions",
    "economy", "economic growth", "inflation", "employment", "jobs report",
    "interest rate", "monetary policy", "fomc", "financial stability",
    "foreign exchange", "exchange rate", "currency", "yen", "dollar",
    "intervention", "tariff", "international trade", "trade policy",
    "semiconductor", "artificial intelligence", "ai infrastructure",
    "treasury yield", "government bond", "credit conditions",
    "株式", "市場", "景気", "物価", "雇用", "金融政策", "金利", "為替", "円",
    "介入", "関税", "半導体", "人工知能",
)

TRUTH_MARKET_TERMS = OFFICIAL_MARKET_TERMS + (
    "stock", "stocks", "equity", "equities", "wall street", "market", "markets",
    "oil price", "energy price", "federal reserve", "fed", "trade", "debt",
)

CURATED_X_HANDLES = {
    "federalreserve": "FRB公式",
    "ustreasury": "米財務省公式",
    "whitehouse": "米ホワイトハウス公式",
    "potus": "米大統領公式",
    "realdonaldtrump": "Donald Trump",
    "elerianm": "Mohamed El-Erian",
    "lizannsonders": "Liz Ann Sonders",
    "jasonfurman": "Jason Furman",
    "claudia_sahm": "Claudia Sahm",
    "biancoresearch": "Bianco Research",
    "charliebilello": "Charlie Bilello",
}

ECONOMIST_WATCH_NAMES = (
    "mohamed el-erian",
    "jason furman",
    "claudia sahm",
    "liz ann sonders",
    "jim bianco",
)

TRUSTED_NEWS_NAMES = (
    "reuters", "associated press", "ap news", "bloomberg", "wall street journal",
    "wsj", "financial times", "nikkei", "axios", "mainichi", "fxstreet",
)


def audited_current_event_items(now: datetime) -> list[dict[str, Any]]:
    """Return short-lived, manually audited evidence for the July 30 yen shock."""

    event_time = datetime(2026, 7, 30, 14, 10, tzinfo=timezone.utc)
    if now < event_time - timedelta(hours=2) or now > event_time + timedelta(days=7):
        return []
    rows = (
        {
            "title": "Yen strengthens sharply against the U.S. dollar; traders alert to possible Japan intervention",
            "summary": (
                "Reutersは円が一時157.8円付近まで急伸したと報道。規模と速度から介入観測が広がった一方、"
                "当局が市場にいたかは直ちに明らかでなく、広範なドル安や月末フローも併記しています。"
            ),
            "url": "https://www.investing.com/news/forex-news/yen-strengthens-sharply-against-the-us-dollar-4824988",
            "source": "Reuters",
            "source_kind": "news-wire",
            "published": "2026-07-30T14:12:00Z",
            "verification": "reported-unconfirmed",
        },
        {
            "title": "Instant View: Yen jumps against the dollar; analysts see intervention-like move but no firm evidence",
            "summary": (
                "Reutersのアナリスト集約。MUFG、AGF、Capital Economics、INGが介入らしい値動きと評価する一方、"
                "確定的・直接的な証拠はまだないとの見方も掲載しています。"
            ),
            "url": "https://www.investing.com/news/economy-news/instant-view-yen-jumps-against-the-dollar-traders-alert-to-japan-intervention-4825019",
            "source": "Reuters",
            "source_kind": "news-wire",
            "published": "2026-07-30T14:23:00Z",
            "verification": "reported-unconfirmed",
        },
        {
            "title": "Yen gains in sharp move, stoking intervention speculation",
            "summary": "Bloombergは急な円高を介入観測として報道。実施確認ではなく、観測段階の情報です。",
            "url": "https://www.investing.com/news/pro/yen-gains-in-sharp-move-stoking-intervention-speculation--bloomberg-432SI-4824817",
            "source": "Bloomberg",
            "source_kind": "news-wire",
            "published": "2026-07-30T13:42:00Z",
            "verification": "reported-unconfirmed",
        },
        {
            "title": "Japanese Yen surges on suspected intervention; EUR/JPY tumbles about 400 pips in minutes",
            "summary": (
                "FXStreetは23時15分JST前後の円全面高を報道。ドル円だけでなくクロス円も急落した事実は、"
                "円固有のショックと整合しますが、介入の公式確認ではありません。"
            ),
            "url": "https://www.fxstreet.com/news/japanese-yen-surges-on-suspected-intervention-eur-jpy-tumbles-400-pips-in-minutes-202607301415",
            "source": "FXStreet",
            "source_kind": "news",
            "published": "2026-07-30T14:15:29Z",
            "verification": "reported-unconfirmed",
        },
        {
            "title": "財務省の7月31日公表分は7月30日夜の急変を対象に含まない",
            "summary": (
                "7月31日19時公表予定の月次集計は6月29日～7月29日分です。"
                "7月30日分を形式的に含み得る次回月次公表は8月28日19時予定で、"
                "7月31日の公表だけでは今回の実施有無を確認も否定もできません。"
            ),
            "url": MOF_INTERVENTION_URL,
            "source": "財務省",
            "source_kind": "official-japan",
            "published": "2026-07-30T15:00:00Z",
            "verification": "primary",
        },
        {
            "title": "Federal Reserve issues FOMC statement on July 29, 2026",
            "summary": (
                "FRBは政策金利を3.50～3.75%に据え置き、9対3で決定。3人は25bp利上げを支持しました。"
                "円急変より約21時間前のため、瞬間的な単独原因とは断定しません。"
            ),
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm",
            "source": "Federal Reserve",
            "source_kind": "official-us",
            "published": "2026-07-29T18:00:00Z",
            "verification": "primary",
        },
    )
    return [
        build_item(
            title=row["title"],
            summary=row["summary"],
            url=row["url"],
            source=row["source"],
            source_kind=row["source_kind"],
            published=row["published"],
            retrieved_at=now,
            verification=row["verification"],
            topic_hint="fx-rates" if "FOMC" not in row["title"] else "policy",
            identity_note="2026年7月31日更新時に原文・時刻・確認状態を監査した短期保持項目。",
        )
        for row in rows
    ]


def audited_current_market_items(now: datetime) -> list[dict[str, Any]]:
    """Keep a small, expiring set of directly checked market context links."""

    anchor = datetime(2026, 7, 30, 5, 0, tzinfo=timezone.utc)
    if now < anchor - timedelta(days=2) or now > anchor + timedelta(days=14):
        return []
    rows = (
        {
            "title": "Microsoft beats Wall Street expectations with $90B in revenue",
            "summary": (
                "APはMicrosoftの四半期売上高が900億ドル、1株利益が4.81ドルとなり、"
                "市場予想の876.2億ドル、4.24ドルを上回ったと報道。Microsoft Cloudは27%増、"
                "Azureは43%増で、AI投資が売上成長につながっている強気側の確認材料です。"
            ),
            "url": "https://apnews.com/article/microsoft-earnings-results-ai-f7dff4fb9d51a2bdec56a13e5da1053d",
            "source": "Associated Press",
            "source_kind": "news-wire",
            "published": "2026-07-29T21:20:50Z",
            "verification": "reported",
            "topic": "ai-bubble",
            "identity": "記事本文と掲載時刻を2026年7月31日に確認。",
        },
        {
            "title": "Microsoft leads a Wall Street rally while bond-market inflation worries remain",
            "summary": (
                "APはMicrosoftの決算を受けNasdaqが一時2.3%高、Microsoftが15.1%高と報道。"
                "一方、Metaは9%安、米10年金利は4.66%で、AI投資の収益化に成功した企業と"
                "費用増が先行する企業の選別が強まっています。"
            ),
            "url": "https://apnews.com/article/stock-markets-rates-korea-ai-oil-99b5702d93a2b5c6e513fb952ccdcc92",
            "source": "Associated Press",
            "source_kind": "news-wire",
            "published": "2026-07-30T05:09:50Z",
            "verification": "reported",
            "topic": "us-stocks",
            "identity": "記事本文と掲載時刻を2026年7月31日に確認。",
        },
        {
            "title": "Microsoft and Meta report ballooning AI expenses",
            "summary": (
                "AxiosはMicrosoftが増益を維持した一方、Metaは利益が大きく低下したと整理。"
                "短寿命のCPU・GPUがMicrosoft設備投資の約3分の2を占めるとの説明もあり、"
                "AI需要の強さと更新投資・減価償却負担を同時に見る必要があります。"
            ),
            "url": "https://www.axios.com/2026/07/29/meta-microsoft-earnings-reports-ai",
            "source": "Axios",
            "source_kind": "news",
            "published": "2026-07-29T20:39:54Z",
            "verification": "reported",
            "topic": "ai-bubble",
            "identity": "記事本文と掲載時刻を2026年7月31日に確認。",
        },
        {
            "title": "Alphabet's cash burn raises alarm as Big Tech AI spending climbs",
            "summary": (
                "ReutersはAlphabetの四半期フリーキャッシュフローが初の赤字となり、"
                "主要社の2026年設備投資が7000億ドル超へ向かうと報道。"
                "強いクラウド需要と、設備投資・減価償却・資金調達負担の両面を示す弱気論点です。"
            ),
            "url": "https://www.investing.com/news/stock-market-news/alphabets-cash-burn-raises-alarm-for-big-tech-as-ai-spending-climbs-4808737",
            "source": "Reuters",
            "source_kind": "news-wire",
            "published": "2026-07-23T12:05:00Z",
            "verification": "reported",
            "topic": "ai-bubble",
            "identity": "Reuters配信記事の本文と掲載ページを2026年7月31日に確認。",
        },
        {
            "title": "AI financing anxiety triggers a broad Asian tech selloff, with Japan's Nikkei down about 4%",
            "summary": (
                "Reutersは7月28日、AI投資の費用負担と中国半導体の競争懸念からアジアの半導体株が売られ、"
                "日経平均が約4%下落したと報道。現在の先物反発だけで底打ちとせず、"
                "米半導体株、円相場、企業決算と合わせて確認するための弱気側の文脈です。"
            ),
            "url": "https://au.investing.com/news/stock-market-news/ai-anxiety-sparks-tech-rout-broad-selloff-in-asian-markets-4555334",
            "source": "Reuters",
            "source_kind": "news-wire",
            "published": "2026-07-28T03:31:00Z",
            "verification": "reported",
            "topic": "japan-stocks",
            "identity": "Reuters配信記事の掲載ページと日付を2026年7月31日に確認。",
        },
        {
            "title": "LinkedIn論点：AI設備投資は資本破壊か、余剰能力の収益化機会か",
            "summary": (
                "CFAのKaren Lucey氏は、ハイパースケーラー4社の2026年設備投資を"
                "約7250億ドルとし、フリーキャッシュフロー圧迫を警戒する一方、"
                "余剰計算能力を外販できればROI懸念が和らぐという反対側の見方も提示しています。"
            ),
            "url": "https://www.linkedin.com/posts/karen-lucey-cfa-76931241_markets-equities-ai-activity-7478521017129271296-wX6U",
            "source": "Karen Lucey, CFA / LinkedIn",
            "source_kind": "linkedin",
            "published": "2026-07-02T18:52:34Z",
            "verification": "public-indexed",
            "topic": "ai-bubble",
            "identity": (
                "LinkedIn公開ページとactivity ID由来の時刻。専門家の見解であり、"
                "数値・本人性・反応数はリンク先で再確認します。"
            ),
        },
    )
    return [
        build_item(
            title=row["title"],
            summary=row["summary"],
            url=row["url"],
            source=row["source"],
            source_kind=row["source_kind"],
            published=row["published"],
            retrieved_at=now,
            verification=row["verification"],
            topic_hint=row["topic"],
            identity_note=row["identity"],
        )
        for row in rows
        if (
            parse_datetime(row["published"]) is not None
            and timedelta(0) <= now - parse_datetime(row["published"]) <= timedelta(days=7)
        )
    ]


def request(
    url: str,
    *,
    timeout: int = 18,
    attempts: int = 2,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    base_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,application/rss+xml,application/atom+xml,text/xml,text/html,*/*",
    }
    if headers:
        base_headers.update(headers)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=base_headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read(), response.geturl()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.7 * (attempt + 1))
    raise RuntimeError(f"Unable to retrieve {url}: {last_error}")


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


def clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def iso_or_none(value: Any) -> str | None:
    parsed = parse_datetime(value)
    return parsed.astimezone(timezone.utc).isoformat() if parsed else None


def normalize_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlparse(value)
        query = urllib.parse.parse_qs(parsed.query)
        for key in ("url", "u", "target"):
            candidate = query.get(key, [None])[0]
            if candidate and candidate.startswith(("http://", "https://")):
                return urllib.parse.unquote(candidate)
        return urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path,
            "",
            "",
            "",
        ))
    except Exception:
        return value


def contains_term(text: str, term: str) -> bool:
    """Match English terms as words, while retaining substring matching for Japanese."""

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


def classify_topic(text: str, hint: str | None = None) -> tuple[str, str]:
    lowered = text.lower()
    scores = {
        key: sum(1 for term in profile["terms"] if contains_term(lowered, term))
        for key, profile in TOPICS.items()
    }
    if hint in TOPICS:
        scores[hint] += 2
    key = max(scores, key=scores.get)
    if scores[key] <= 0:
        key = hint if hint in TOPICS else "policy"
    return key, TOPICS[key]["label"]


def classify_stance(text: str) -> str:
    lowered = text.lower()
    bull = sum(1 for term in BULL_TERMS if contains_term(lowered, term))
    bear = sum(1 for term in BEAR_TERMS if contains_term(lowered, term))
    if bull and bear:
        return "mixed"
    if bull:
        return "bullish"
    if bear:
        return "bearish"
    return "neutral"


def relevance_score(text: str) -> int:
    lowered = text.lower()
    return sum(1 for term in MARKET_RELEVANCE_TERMS if contains_term(lowered, term))


def item_id(url: str, title: str) -> str:
    digest = hashlib.sha1((normalize_url(url) + "\n" + title).encode("utf-8")).hexdigest()
    return "live-" + digest[:14]


def source_weight(kind: str) -> int:
    if kind.startswith("official"):
        return 34
    if kind in {"news-wire", "news"}:
        return 24
    if kind in {"truth-social", "truth-social-archive", "x-api"}:
        return 17
    if kind in {"linkedin", "bluesky", "x-index"}:
        return 10
    return 8


def build_item(
    *,
    title: str,
    url: str,
    source: str,
    source_kind: str,
    published: Any,
    retrieved_at: datetime,
    summary: str = "",
    topic_hint: str | None = None,
    verification: str | None = None,
    engagement: dict[str, int] | None = None,
    author: str = "",
    identity_note: str = "",
) -> dict[str, Any]:
    clean_title = clean_text(title)
    clean_summary = clean_text(summary)
    topic_key, topic_label = classify_topic(clean_title + " " + clean_summary, topic_hint)
    published_at = iso_or_none(published)
    published_dt = parse_datetime(published_at)
    age_hours = (
        max(0.0, (retrieved_at - published_dt).total_seconds() / 3600.0)
        if published_dt else None
    )
    engagement = engagement or {}
    engagement_total = sum(max(0, int(value or 0)) for value in engagement.values())
    recency = 4 if age_hours is None else max(0, round(34 - min(age_hours, 96) / 4))
    engagement_score = min(30, round(math.log10(engagement_total + 1) * 9))
    source_text = (source + " " + url).lower()
    trust_bonus = (
        24 if source_kind in {"news", "news-wire"} and any(name in source_text for name in TRUSTED_NEWS_NAMES)
        else 0
    )
    priority = source_weight(source_kind) + trust_bonus + recency + engagement_score + min(12, relevance_score(clean_title) * 3)
    if verification is None:
        verification = (
            "primary"
            if source_kind.startswith("official") or source_kind == "truth-social"
            else "reported"
            if source_kind in {"news", "news-wire"}
            else "unverified"
        )
    return {
        "id": item_id(url, clean_title),
        "title": clean_title,
        "summary": clean_summary,
        "url": normalize_url(url),
        "source": source,
        "sourceKind": source_kind,
        "verification": verification,
        "publishedAtUtc": published_at,
        "retrievedAtUtc": retrieved_at.isoformat(),
        "ageHours": round(age_hours, 2) if age_hours is not None else None,
        "topicKey": topic_key,
        "topic": topic_label,
        "stance": classify_stance(clean_title + " " + clean_summary),
        "engagement": engagement,
        "engagementTotal": engagement_total,
        "priorityScore": priority,
        "talkScore": 0,
        "author": author,
        "identityNote": identity_note,
    }


def _max_window_move(points: list[dict[str, Any]], minutes: int) -> dict[str, Any]:
    if len(points) < 2:
        return {"minutes": minutes, "points": None, "pct": None, "startUtc": None, "endUtc": None}
    best: dict[str, Any] | None = None
    left = 0
    window_seconds = minutes * 60
    for right, row in enumerate(points):
        while left < right and row["timestamp"] - points[left]["timestamp"] > window_seconds:
            left += 1
        candidates = range(left, right)
        for index in candidates:
            start = points[index]
            delta = row["value"] - start["value"]
            if best is None or abs(delta) > abs(best["points"]):
                best = {
                    "minutes": minutes,
                    "points": delta,
                    "pct": pct_change(row["value"], start["value"]),
                    "startUtc": datetime.fromtimestamp(start["timestamp"], timezone.utc).isoformat(),
                    "endUtc": datetime.fromtimestamp(row["timestamp"], timezone.utc).isoformat(),
                }
    return best or {"minutes": minutes, "points": None, "pct": None, "startUtc": None, "endUtc": None}


def _peak_to_trough(points: list[dict[str, Any]]) -> dict[str, Any]:
    if len(points) < 2:
        return {"points": None, "pct": None, "startUtc": None, "endUtc": None}
    peak = points[0]
    best = {
        "points": 0.0,
        "pct": 0.0,
        "startUtc": datetime.fromtimestamp(peak["timestamp"], timezone.utc).isoformat(),
        "endUtc": datetime.fromtimestamp(peak["timestamp"], timezone.utc).isoformat(),
    }
    for row in points[1:]:
        decline = peak["value"] - row["value"]
        if decline > best["points"]:
            best = {
                "points": decline,
                "pct": decline / peak["value"] * 100.0 if peak["value"] else None,
                "startUtc": datetime.fromtimestamp(peak["timestamp"], timezone.utc).isoformat(),
                "endUtc": datetime.fromtimestamp(row["timestamp"], timezone.utc).isoformat(),
            }
        if row["value"] > peak["value"]:
            peak = row
    return best


def fetch_intraday_quote(key: str, profile: dict[str, str], now: datetime) -> dict[str, Any]:
    symbol = profile["symbol"]
    encoded = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
        "?range=5d&interval=5m&includePrePost=true&events=div%2Csplits"
    )
    raw, _ = request(url)
    payload = json.loads(raw.decode("utf-8"))
    result = payload["chart"]["result"][0]
    meta = result.get("meta") or {}
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    volumes = quote.get("volume") or []
    points: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        value = finite(closes[index]) if index < len(closes) else None
        if value is None:
            continue
        points.append({"timestamp": int(timestamp), "value": value})
    if not points:
        raise RuntimeError(f"No intraday values for {symbol}")
    latest = points[-1]
    latest_dt = datetime.fromtimestamp(latest["timestamp"], timezone.utc)
    recent_cutoff = max(
        int((now - timedelta(hours=30)).timestamp()),
        points[0]["timestamp"],
    )
    recent_points = [row for row in points if row["timestamp"] >= recent_cutoff]
    if len(recent_points) < 2:
        recent_points = points[-2:]
    recent_values = [row["value"] for row in recent_points]
    previous_close = finite(meta.get("chartPreviousClose"))
    if previous_close is None:
        previous_close = finite(meta.get("previousClose"))
    stale_minutes = max(0.0, (now - latest_dt).total_seconds() / 60.0)
    market_state = "updating" if stale_minutes <= 25 else "delayed-or-closed"
    source_url = f"https://finance.yahoo.com/quote/{urllib.parse.quote(symbol)}"
    spark = recent_points[-96:]
    return {
        "key": key,
        **profile,
        "value": latest["value"],
        "previousClose": previous_close,
        "changePct": pct_change(latest["value"], previous_close),
        "changePoints": latest["value"] - previous_close if previous_close is not None else None,
        "sessionHigh": max(recent_values),
        "sessionLow": min(recent_values),
        "sessionRangePct": pct_change(max(recent_values), min(recent_values)),
        "quoteTimeUtc": latest_dt.isoformat(),
        "quoteTimeJst": latest_dt.astimezone(JST).isoformat(),
        "staleMinutes": round(stale_minutes, 1),
        "marketState": market_state,
        "exchangeName": meta.get("exchangeName"),
        "exchangeTimezone": meta.get("exchangeTimezoneName"),
        "instrumentType": meta.get("instrumentType"),
        "currencyReported": meta.get("currency"),
        "regularMarketVolume": (
            finite(volumes[-1]) if volumes and len(volumes) == len(timestamps) else finite(meta.get("regularMarketVolume"))
        ),
        "move5m": _max_window_move(recent_points, 5),
        "move15m": _max_window_move(recent_points, 15),
        "move30m": _max_window_move(recent_points, 30),
        "peakToTrough": _peak_to_trough(recent_points),
        "sparkline": [
            {
                "timeUtc": datetime.fromtimestamp(row["timestamp"], timezone.utc).isoformat(),
                "value": row["value"],
            }
            for row in spark
        ],
        "sourceUrl": source_url,
        "_rawHighCount": sum(1 for value in highs if finite(value) is not None),
        "_rawLowCount": sum(1 for value in lows if finite(value) is not None),
    }


def fetch_intraday_quotes(now: datetime) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    quotes: dict[str, Any] = {}
    statuses: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(fetch_intraday_quote, key, profile, now): (key, profile)
            for key, profile in INTRADAY_INSTRUMENTS.items()
        }
        for future in as_completed(futures):
            key, profile = futures[future]
            try:
                quote = future.result()
                quote.pop("_rawHighCount", None)
                quote.pop("_rawLowCount", None)
                quotes[key] = quote
                statuses.append({
                    "name": profile["label"],
                    "kind": "market-price",
                    "status": "ok",
                    "url": quote["sourceUrl"],
                    "retrievedAtUtc": now.isoformat(),
                    "message": "5分足を取得",
                })
            except Exception as exc:
                statuses.append({
                    "name": profile["label"],
                    "kind": "market-price",
                    "status": "failed",
                    "url": f"https://finance.yahoo.com/quote/{urllib.parse.quote(profile['symbol'])}",
                    "retrievedAtUtc": now.isoformat(),
                    "message": str(exc),
                })
    return quotes, statuses


def build_market_shock(quotes: dict[str, Any], now: datetime) -> dict[str, Any]:
    fx = quotes.get("USDJPY") or {}
    day_change = finite(fx.get("changePct"))
    range_pct = finite(fx.get("sessionRangePct"))
    peak_to_trough = finite((fx.get("peakToTrough") or {}).get("pct"))
    move30 = finite((fx.get("move30m") or {}).get("pct"))
    magnitude = max(
        abs(day_change or 0.0),
        abs(range_pct or 0.0),
        abs(peak_to_trough or 0.0),
        abs(move30 or 0.0),
    )
    if magnitude >= 2.0 or abs(finite((fx.get("peakToTrough") or {}).get("points")) or 0.0) >= 3.0:
        severity = "critical"
        severity_label = "重大な急変"
    elif magnitude >= 1.0 or abs(finite((fx.get("move30m") or {}).get("points")) or 0.0) >= 1.5:
        severity = "warning"
        severity_label = "急変を監視"
    elif fx:
        severity = "normal"
        severity_label = "通常範囲"
    else:
        severity = "unknown"
        severity_label = "取得不能"
    if severity in {"critical", "warning"}:
        intervention_status = "price-shock-only"
        intervention_label = "急変を検知・介入は公式未確認"
        headline = "USD/JPYで円高方向の急変を検知。介入実施はまだ確定できません"
        summary = (
            "価格データから大幅な円高方向の動きを即時検知しました。値動きだけでは為替介入、"
            "要人発言、金利材料、ポジション解消を区別できないため、財務省の公表と会見を待って確認します。"
        )
    elif severity == "normal":
        intervention_status = "no-shock-observed"
        intervention_label = "確認範囲で重大な急変なし"
        headline = "USD/JPYの急変条件は現在点灯していません"
        summary = "5分足・30分変化・前日比を監視しています。介入がなかったことを証明する表示ではありません。"
    else:
        intervention_status = "unknown"
        intervention_label = "価格取得不能・判定保留"
        headline = "USD/JPYの急変判定を更新できません"
        summary = "前回表示がある場合は、その取得時刻を確認してください。"
    return {
        "instrument": "USD/JPY",
        "severity": severity,
        "severityLabel": severity_label,
        "headline": headline,
        "summary": summary,
        "interventionStatus": intervention_status,
        "interventionLabel": intervention_label,
        "officiallyConfirmed": False,
        "assessmentRule": (
            "前日比・約30時間レンジ・30分変化の絶対値が1%以上、または30分で1.5円以上を監視。"
            "2%以上または高値から安値まで3円以上を重大とする。閾値は介入認定条件ではない。"
        ),
        "observedAtUtc": fx.get("quoteTimeUtc"),
        "observedAtJst": fx.get("quoteTimeJst"),
        "checkedAtUtc": now.isoformat(),
        "current": finite(fx.get("value")),
        "previousClose": finite(fx.get("previousClose")),
        "changePct": day_change,
        "sessionHigh": finite(fx.get("sessionHigh")),
        "sessionLow": finite(fx.get("sessionLow")),
        "sessionRangePct": range_pct,
        "move5m": fx.get("move5m"),
        "move15m": fx.get("move15m"),
        "move30m": fx.get("move30m"),
        "peakToTrough": fx.get("peakToTrough"),
        "sparkline": fx.get("sparkline") or [],
        "priceSourceUrl": fx.get("sourceUrl"),
        "officialVerificationUrl": MOF_INTERVENTION_URL,
        "officialVerificationNote": (
            "財務省の月次公表は対象期間終了後に公表されるため、急変直後は公式未確認が通常です。"
            "大臣会見・財務省新着・外国為替平衡操作の実施状況を継続確認します。"
        ),
    }


def intervention_event_window(
    shock: dict[str, Any],
) -> tuple[datetime | None, datetime | None]:
    """Locate the strongest short USD/JPY move represented in this snapshot."""

    candidates: list[tuple[tuple[float, float], datetime, datetime]] = []
    for key in ("move5m", "move15m", "move30m"):
        move = shock.get(key) or {}
        start = parse_datetime(move.get("startUtc"))
        end = parse_datetime(move.get("endUtc"))
        if start is None or end is None or end < start:
            continue
        score = (
            abs(finite(move.get("pct")) or 0.0),
            abs(finite(move.get("points")) or 0.0),
        )
        candidates.append((score, start, end))
    if candidates:
        _, start, end = max(candidates, key=lambda row: row[0])
        return start, end
    observed = parse_datetime(shock.get("observedAtUtc"))
    if observed is None:
        return None, None
    return observed - timedelta(minutes=30), observed


def update_intervention_assessment(
    shock: dict[str, Any],
    items: list[dict[str, Any]],
) -> None:
    """Promote price-only status to reported-unconfirmed, never to confirmed."""

    event_start, event_end = intervention_event_window(shock)
    evidence_start = event_start - timedelta(hours=1) if event_start else None
    evidence_end = event_end + timedelta(hours=24) if event_end else None
    evidence = []
    for item in items:
        text = (item.get("title") or "") + " " + (item.get("summary") or "")
        if not re.search(r"\bintervention\b|介入", text, re.I):
            continue
        if item.get("sourceKind") not in {"news-wire", "news"}:
            continue
        if item.get("verification") not in {"reported", "reported-unconfirmed"}:
            continue
        published = parse_datetime(item.get("publishedAtUtc"))
        if published is None or evidence_start is None or evidence_end is None:
            continue
        if not evidence_start <= published <= evidence_end:
            continue
        evidence.append({
            "id": item.get("id"),
            "source": item.get("source"),
            "title": item.get("title"),
            "url": item.get("url"),
            "publishedAtUtc": item.get("publishedAtUtc"),
            "claimStatus": "intervention-observation",
        })
    if shock.get("severity") not in {"critical", "warning"}:
        evidence = []
    if evidence and shock.get("severity") in {"critical", "warning"}:
        shock["interventionStatus"] = "reported-unconfirmed"
        shock["interventionLabel"] = "主要報道が介入観測・公式確認なし"
        shock["headline"] = "USD/JPYの急変で介入観測。主要報道あり、公式確認はまだありません"
        shock["summary"] = (
            "価格の規模と速度から複数の主要報道・アナリストが介入を疑っています。"
            "ただし財務省・日銀の公式確認はなく、月末フロー、米金利材料、広範なドル安も候補です。"
        )
    shock["reportedEvidence"] = evidence[:6]
    shock["reportedEvidenceCount"] = len(evidence)
    shock["officiallyConfirmed"] = False
    july_event_start = datetime(2026, 7, 30, 13, 0, tzinfo=timezone.utc)
    july_event_end = datetime(2026, 7, 30, 15, 30, tzinfo=timezone.utc)
    is_july_event = (
        shock.get("severity") in {"critical", "warning"}
        and event_start is not None
        and event_end is not None
        and event_start <= july_event_end
        and event_end >= july_event_start
    )
    if is_july_event:
        shock["eventId"] = "usdjpy-2026-07-30-shock"
        shock["eventStartEstimateJst"] = event_start.astimezone(JST).replace(microsecond=0).isoformat()
        shock["officialDisclosureSchedule"] = {
            "immediateRelease": {
                "atJst": "2026-07-31T19:00:00+09:00",
                "coversThrough": "2026-07-29",
                "coversThisEvent": False,
            },
            "nextMonthlyReleaseIncludingEventDate": {
                "atJst": "2026-08-28T19:00:00+09:00",
                "expectedCoverageStart": "2026-07-30",
                "coversThisEventDate": True,
            },
            "sourceUrl": MOF_INTERVENTION_URL,
        }


def build_premarket(quotes: dict[str, Any], now: datetime) -> dict[str, Any]:
    cash = quotes.get("NIKKEI_CASH") or {}
    yen_future = quotes.get("NIKKEI_FUTURES_YEN") or {}
    dollar_future = quotes.get("NIKKEI_FUTURES_USD") or {}
    primary = yen_future or dollar_future
    cash_value = finite(cash.get("value"))
    future_value = finite(primary.get("value"))
    gap_points = future_value - cash_value if future_value is not None and cash_value is not None else None
    gap_pct = pct_change(future_value, cash_value)
    us_keys = ("SP500_FUTURES", "NASDAQ100_FUTURES", "DOW_FUTURES", "RUSSELL2000_FUTURES")
    us_changes = [
        finite((quotes.get(key) or {}).get("changePct"))
        for key in us_keys
        if finite((quotes.get(key) or {}).get("changePct")) is not None
    ]
    us_average = sum(us_changes) / len(us_changes) if us_changes else None
    cues: list[dict[str, str]] = []
    if gap_pct is not None:
        if gap_pct >= 0.5:
            cues.append({
                "state": "positive",
                "title": "日経先物は現物終値を上回る",
                "text": "買い優勢の参考材料ですが、配当・限月・為替・寄り前材料で差は変わります。",
            })
        elif gap_pct <= -0.5:
            cues.append({
                "state": "negative",
                "title": "日経先物は現物終値を下回る",
                "text": "寄り前の警戒材料です。ギャップをそのまま予想始値とは扱いません。",
            })
        else:
            cues.append({
                "state": "neutral",
                "title": "日経先物と現物終値の差は小さい",
                "text": "個別決算、為替、米国引け後材料の確認が相対的に重要です。",
            })
    if us_average is not None:
        direction = "強い" if us_average >= 0.35 else "弱い" if us_average <= -0.35 else "まちまち"
        cues.append({
            "state": "positive" if us_average >= 0.35 else "negative" if us_average <= -0.35 else "neutral",
            "title": f"米国株先物は平均で{direction}",
            "text": f"取得できた{len(us_changes)}指数先物の単純平均は{us_average:+.2f}%です。",
        })
    fx = quotes.get("USDJPY") or {}
    fx_change = finite(fx.get("changePct"))
    if fx_change is not None and abs(fx_change) >= 0.75:
        cues.append({
            "state": "negative" if fx_change < 0 else "mixed",
            "title": "ドル円の変動が大きい",
            "text": (
                "円高は輸出株の円換算利益に逆風、輸入コストには追い風になり得ます。"
                "株式全体への方向は一意ではありません。"
            ),
        })
    vix = finite((quotes.get("VIX") or {}).get("value"))
    if vix is not None:
        cues.append({
            "state": "negative" if vix >= 30 else "warning" if vix >= 20 else "neutral",
            "title": f"VIXは{vix:.1f}",
            "text": "30以上は高ストレス、20以上は変動拡大の目安です。方向や暴落確率を確定しません。",
        })
    active = sum(1 for row in quotes.values() if row.get("marketState") == "updating")
    return {
        "checkedAtUtc": now.isoformat(),
        "checkedAtJst": now.astimezone(JST).isoformat(),
        "marketStateLabel": (
            f"{active}/{len(quotes)}系列が直近25分以内に更新"
            if quotes else "先物・時間外データを取得できません"
        ),
        "cashReference": cash,
        "primaryNikkeiFutureKey": "NIKKEI_FUTURES_YEN" if yen_future else "NIKKEI_FUTURES_USD" if dollar_future else None,
        "nikkeiFutureValue": future_value,
        "nikkeiCashReferenceValue": cash_value,
        "nikkeiFutureCashGapPoints": gap_points,
        "nikkeiFutureCashGapPct": gap_pct,
        "usFuturesAverageChangePct": us_average,
        "quotes": quotes,
        "strategyCues": cues[:5],
        "summary": (
            "東証休場中はCME日経225先物を主軸に、米国4指数先物、ドル円、米10年金利、VIXを同じ取得時刻で確認します。"
            "先物と現物の差は翌営業日の参考材料で、予想始値や売買指示ではありません。"
        ),
        "caution": (
            "CME円建て・ドル建て、OSE現物は取引所、限月、通貨、配当、休場時間が異なります。"
            "Yahoo Financeの値は遅延する場合があるため、各カードの原典と取得時刻を確認してください。"
        ),
    }


def parse_feed_items(raw: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(raw)
    rows: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        rows.append({
            "title": item.findtext("title") or "",
            "link": item.findtext("link") or "",
            "published": item.findtext("pubDate") or item.findtext("date") or "",
            "summary": item.findtext("description") or "",
            "source": item.findtext("source") or "",
        })
    if rows:
        return rows
    atom_ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall(".//atom:entry", atom_ns) or root.findall(".//entry")
    for entry in entries:
        link_node = entry.find("atom:link", atom_ns) or entry.find("link")
        link = link_node.get("href", "") if link_node is not None else ""
        rows.append({
            "title": entry.findtext("atom:title", default="", namespaces=atom_ns) or entry.findtext("title") or "",
            "link": link,
            "published": (
                entry.findtext("atom:published", default="", namespaces=atom_ns)
                or entry.findtext("atom:updated", default="", namespaces=atom_ns)
                or entry.findtext("published")
                or entry.findtext("updated")
                or ""
            ),
            "summary": (
                entry.findtext("atom:summary", default="", namespaces=atom_ns)
                or entry.findtext("atom:content", default="", namespaces=atom_ns)
                or entry.findtext("summary")
                or ""
            ),
            "source": "",
        })
    return rows


def fetch_official_feed(feed: dict[str, str], now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw, _ = request(feed["url"])
    if feed.get("format") == "html-links":
        page = raw.decode("utf-8", errors="replace")
        feed_rows: list[dict[str, str]] = []
        seen_links: set[str] = set()
        pattern = re.compile(
            r'<a[^>]+href=["\']([^"\']*/news/press-releases/[^"\']+)["\'][^>]*>(.*?)</a>',
            flags=re.I | re.S,
        )
        for match in pattern.finditer(page):
            link = urllib.parse.urljoin(feed["url"], html.unescape(match.group(1)))
            title = clean_text(match.group(2))
            if not title or link in seen_links:
                continue
            seen_links.add(link)
            preceding = page[max(0, match.start() - 500):match.start()]
            dates = re.findall(r"20\d{2}-\d{2}-\d{2}", preceding)
            feed_rows.append({
                "title": title,
                "link": link,
                "published": dates[-1] + "T12:00:00Z" if dates else "",
                "summary": "",
                "source": feed["name"],
            })
            if len(feed_rows) >= 30:
                break
    else:
        feed_rows = parse_feed_items(raw)[:30]
    output: list[dict[str, Any]] = []
    for row in feed_rows:
        text = clean_text(row["title"] + " " + row["summary"])
        if not any(contains_term(text, term) for term in OFFICIAL_MARKET_TERMS):
            continue
        item = build_item(
            title=row["title"],
            url=row["link"] or feed["url"],
            source=feed["name"],
            source_kind=feed["kind"],
            published=row["published"],
            retrieved_at=now,
            summary=row["summary"],
            verification="primary",
        )
        if item["ageHours"] is None or item["ageHours"] <= 336:
            output.append(item)
    return output[:10], {
        "name": feed["name"],
        "kind": feed["kind"],
        "status": "ok",
        "url": feed["url"],
        "retrievedAtUtc": now.isoformat(),
        "message": f"市場関連 {len(output[:10])}件",
    }


def fetch_bing_news(query_def: dict[str, str], now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = urllib.parse.urlencode({
        "q": query_def["query"],
        "format": "rss",
        "setlang": "en-US",
    })
    url = "https://www.bing.com/news/search?" + params
    raw, _ = request(url)
    output: list[dict[str, Any]] = []
    for row in parse_feed_items(raw)[:12]:
        if not row["title"] or not row["link"]:
            continue
        source = clean_text(row["source"]) or "Bing News discovery"
        kind = "news-wire" if any(name in source.lower() for name in ("reuters", "associated press", "bloomberg")) else "news"
        item = build_item(
            title=row["title"],
            url=row["link"],
            source=source,
            source_kind=kind,
            published=row["published"],
            retrieved_at=now,
            summary=row["summary"],
            topic_hint=query_def["key"],
        )
        if item["ageHours"] is None or item["ageHours"] <= 168:
            output.append(item)
    return output[:8], {
        "name": f"Bing News / {TOPICS.get(query_def['key'], {'label': query_def['key']})['label']}",
        "kind": "news-discovery",
        "status": "ok" if output else "limited",
        "url": url,
        "retrievedAtUtc": now.isoformat(),
        "message": f"{len(output[:8])}件",
    }


def fetch_google_news(query_def: dict[str, str], now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Use a second public news index so one empty provider does not hide a story."""

    params = urllib.parse.urlencode({
        "q": query_def["query"],
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    })
    url = "https://news.google.com/rss/search?" + params
    raw, _ = request(url)
    output: list[dict[str, Any]] = []
    for row in parse_feed_items(raw)[:16]:
        if not row["title"] or not row["link"]:
            continue
        source = clean_text(row["source"]) or "Google News discovery"
        lowered_source = source.lower()
        kind = (
            "news-wire"
            if any(name in lowered_source for name in ("reuters", "associated press", "bloomberg"))
            else "news"
        )
        item = build_item(
            title=row["title"],
            url=row["link"],
            source=source,
            source_kind=kind,
            published=row["published"],
            retrieved_at=now,
            summary=row["summary"],
            topic_hint=query_def["key"],
            identity_note="Google News公開RSS経由。リンク先の記事本文と掲載時刻を確認します。",
        )
        if item["ageHours"] is None or item["ageHours"] <= 168:
            output.append(item)
    return output[:8], {
        "name": f"Google News / {TOPICS.get(query_def['key'], {'label': query_def['key']})['label']}",
        "kind": "news-discovery",
        "status": "ok",
        "url": url,
        "retrievedAtUtc": now.isoformat(),
        "message": f"{len(output[:8])}件",
    }


def fetch_public_social_index(
    search_def: dict[str, str],
    now: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = urllib.parse.urlencode({
        "q": search_def["query"],
        "format": "rss",
        "setlang": "en-US",
    })
    url = "https://www.bing.com/search?" + params
    raw, _ = request(url)
    output: list[dict[str, Any]] = []
    for row in parse_feed_items(raw)[:20]:
        direct = normalize_url(row["link"])
        host = urllib.parse.urlparse(direct).netloc.lower()
        if search_def["requiredHost"] not in host:
            continue
        path = urllib.parse.urlparse(direct).path.lower()
        if search_def["kind"] == "x-index" and "/status/" not in path:
            continue
        if search_def["kind"] == "linkedin" and "/posts/" not in path:
            continue
        searchable_text = clean_text((row.get("title") or "") + " " + (row.get("summary") or ""))
        if relevance_score(searchable_text) <= 0:
            continue
        output.append(build_item(
            title=row["title"],
            url=direct,
            source=search_def["name"],
            source_kind=search_def["kind"],
            published=row["published"],
            retrieved_at=now,
            summary=row["summary"],
            verification="unverified",
            identity_note="公開検索索引経由。投稿時刻・本人性・完全性は保証しません。",
        ))
    return output[:8], {
        "name": search_def["name"],
        "kind": search_def["kind"],
        "status": "limited",
        "url": url,
        "retrievedAtUtc": now.isoformat(),
        "message": f"公開索引 {len(output[:8])}件。全投稿取得ではありません。",
    }


def fetch_x_api(now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    monitor_url = (
        "https://x.com/search?q="
        + urllib.parse.quote('(USDJPY OR "AI bubble" OR stocks OR rates) lang:en')
        + "&src=typed_query&f=live"
    )
    if not token:
        return [], {
            "name": "X recent search API",
            "kind": "x-api",
            "status": "not-configured",
            "url": monitor_url,
            "retrievedAtUtc": now.isoformat(),
            "message": "APIキー未設定。公開ウェブ索引は別経路で監視します。",
        }
    queries = (
        '(USDJPY OR yen OR "AI bubble" OR semiconductor OR stocks OR rates) lang:en -is:retweet',
        (
            '(from:federalreserve OR from:USTreasury OR from:WhiteHouse OR '
            'from:realDonaldTrump OR from:elerianm OR from:LizAnnSonders OR '
            'from:jasonfurman OR from:Claudia_Sahm) -is:retweet'
        ),
    )
    output: list[dict[str, Any]] = []
    for query in queries:
        params = urllib.parse.urlencode({
            "query": query,
            "max_results": 25,
            "tweet.fields": "created_at,author_id,lang,public_metrics",
            "expansions": "author_id",
            "user.fields": "username,name,verified,verified_type",
        })
        url = "https://api.x.com/2/tweets/search/recent?" + params
        raw, _ = request(url, headers={"Authorization": f"Bearer {token}"})
        payload = json.loads(raw.decode("utf-8"))
        users = {
            str(row.get("id")): row
            for row in (payload.get("includes") or {}).get("users", [])
        }
        for row in payload.get("data") or []:
            post_text = clean_text(row.get("text") or "")
            if relevance_score(post_text) <= 0:
                continue
            user = users.get(str(row.get("author_id")), {})
            username = str(user.get("username") or "")
            metrics = row.get("public_metrics") or {}
            engagement = {
                "likes": int(metrics.get("like_count") or 0),
                "reposts": int(metrics.get("retweet_count") or 0),
                "replies": int(metrics.get("reply_count") or 0),
                "quotes": int(metrics.get("quote_count") or 0),
            }
            handle_key = username.lower()
            identity = CURATED_X_HANDLES.get(handle_key, "")
            output.append(build_item(
                title=post_text,
                url=(
                    f"https://x.com/{username}/status/{row['id']}"
                    if username else f"https://x.com/i/web/status/{row['id']}"
                ),
                source="@" + username if username else "X",
                source_kind="x-api",
                published=row.get("created_at"),
                retrieved_at=now,
                verification="primary-statement" if identity else "unverified",
                engagement=engagement,
                author=user.get("name") or "",
                identity_note=(
                    f"監視対象: {identity}。認証表示は発言内容の事実確認を意味しません。"
                    if identity else "X投稿。認証表示や反応数は内容の正確性を保証しません。"
                ),
            ))
    deduped = deduplicate_items(output)
    return deduped[:24], {
        "name": "X recent search API",
        "kind": "x-api",
        "status": "ok",
        "url": monitor_url,
        "retrievedAtUtc": now.isoformat(),
        "message": f"{len(deduped[:24])}件。反応数・投稿時刻を取得。",
    }


def fetch_bluesky(now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    queries = ("USDJPY intervention yen", "AI bubble stocks", "Federal Reserve markets")
    output: list[dict[str, Any]] = []
    for query in queries:
        params = urllib.parse.urlencode({"q": query, "limit": 20, "sort": "latest"})
        url = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?" + params
        raw, _ = request(url)
        payload = json.loads(raw.decode("utf-8"))
        for row in payload.get("posts") or []:
            record = row.get("record") or {}
            author = row.get("author") or {}
            uri = str(row.get("uri") or "")
            parts = uri.split("/")
            rkey = parts[-1] if parts else ""
            handle = str(author.get("handle") or "")
            if not handle or not rkey:
                continue
            engagement = {
                "likes": int(row.get("likeCount") or 0),
                "reposts": int(row.get("repostCount") or 0),
                "replies": int(row.get("replyCount") or 0),
                "quotes": int(row.get("quoteCount") or 0),
            }
            output.append(build_item(
                title=record.get("text") or "",
                url=f"https://bsky.app/profile/{handle}/post/{rkey}",
                source="@" + handle,
                source_kind="bluesky",
                published=record.get("createdAt") or row.get("indexedAt"),
                retrieved_at=now,
                verification="unverified",
                engagement=engagement,
                author=author.get("displayName") or "",
                identity_note="Bluesky公開API。プロフィール表示と投稿内容の事実確認は別です。",
            ))
    deduped = deduplicate_items(output)
    return deduped[:18], {
        "name": "Bluesky public search",
        "kind": "bluesky",
        "status": "ok",
        "url": "https://bsky.app/search",
        "retrievedAtUtc": now.isoformat(),
        "message": f"{len(deduped[:18])}件。公開APIから取得。",
    }


def fetch_truth_social(now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lookup_url = "https://truthsocial.com/api/v1/accounts/lookup?acct=realDonaldTrump"
    archive_used = False
    try:
        raw, _ = request(lookup_url)
        account = json.loads(raw.decode("utf-8"))
        account_id = account.get("id")
        if not account_id:
            raise RuntimeError("Truth Social account lookup returned no id")
        statuses_url = (
            f"https://truthsocial.com/api/v1/accounts/{account_id}/statuses"
            "?exclude_replies=true&exclude_reblogs=true&limit=20"
        )
        raw, _ = request(statuses_url)
        source_rows = [
            {
                "text": clean_text(row.get("content") or ""),
                "url": row.get("url") or row.get("uri") or "https://truthsocial.com/@realDonaldTrump",
                "published": row.get("created_at"),
                "engagement": {
                    "likes": int(row.get("favourites_count") or 0),
                    "reposts": int(row.get("reblogs_count") or 0),
                    "replies": int(row.get("replies_count") or 0),
                },
            }
            for row in json.loads(raw.decode("utf-8"))
        ]
    except Exception:
        archive_used = True
        archive_url = "https://www.trumpstruth.org/feed"
        raw, _ = request(archive_url)
        source_rows = []
        for row in parse_feed_items(raw)[:30]:
            archive_title = clean_text(row.get("title") or "")
            archive_summary = clean_text(row.get("summary") or "")
            if archive_title and archive_summary and (
                archive_title.casefold() in archive_summary.casefold()
                or archive_summary.casefold() in archive_title.casefold()
            ):
                text = archive_title if len(archive_title) <= len(archive_summary) else archive_summary
            else:
                text = clean_text(archive_title + " " + archive_summary)
            direct_match = re.search(r"https://truthsocial\.com/[^\s\"'<]+", row.get("summary") or "")
            source_rows.append({
                "text": text,
                "url": html.unescape(direct_match.group(0)) if direct_match else row.get("link") or archive_url,
                "published": row.get("published"),
                "engagement": {},
            })
    output: list[dict[str, Any]] = []
    for row in source_rows:
        text = row["text"]
        if not any(contains_term(text, term) for term in TRUTH_MARKET_TERMS):
            continue
        output.append(build_item(
            title=text,
            url=row["url"],
            source="Trump's Truth archive" if archive_used else "Donald J. Trump / Truth Social",
            source_kind="truth-social-archive" if archive_used else "truth-social",
            published=row["published"],
            retrieved_at=now,
            verification="archived-statement" if archive_used else "primary-statement",
            engagement=row["engagement"],
            author="Donald J. Trump",
            identity_note=(
                "第三者公開アーカイブ経由。必ずリンク先のTruth Social原投稿と照合します。"
                if archive_used else
                "本人アカウントの発言としての一次資料。発言内の事実を別途保証するものではありません。"
            ),
        ))
    return output[:8], {
        "name": "Donald Trump / Truth Social" if not archive_used else "Trump's Truth public archive",
        "kind": "truth-social" if not archive_used else "truth-social-archive",
        "status": "ok" if not archive_used else "limited",
        "url": "https://truthsocial.com/@realDonaldTrump",
        "retrievedAtUtc": now.isoformat(),
        "message": (
            f"本人公開APIから市場関連 {len(output[:8])}件"
            if not archive_used else
            f"本人API拒否のため公開アーカイブ経由 {len(output[:8])}件"
        ),
    }


def deduplicate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for item in sorted(items, key=lambda row: (-int(row.get("priorityScore") or 0), row.get("title") or "")):
        url_key = normalize_url(item.get("url") or "")
        title_key = re.sub(r"[^a-z0-9一-龥ぁ-んァ-ン]+", "", (item.get("title") or "").lower())[:180]
        if not url_key or url_key in seen_urls or (title_key and title_key in seen_titles):
            continue
        seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        output.append(item)
    return output


def rank_briefing_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = deduplicate_items(items)
    topic_counts: dict[str, int] = {}
    for item in items:
        key = item.get("topicKey") or "policy"
        topic_counts[key] = topic_counts.get(key, 0) + 1
    for item in items:
        count = topic_counts.get(item.get("topicKey") or "policy", 1)
        engagement = int(item.get("engagementTotal") or 0)
        # An unknown publication time must not be ranked as if it were fresh.
        recency_component = 4 if item.get("ageHours") is None else max(0, 28 - min(72, item["ageHours"]) / 3)
        item["talkScore"] = min(
            100,
            round(18 + min(30, count * 5) + min(32, math.log10(engagement + 1) * 10) + recency_component),
        )
        item["priorityScore"] = int(item.get("priorityScore") or 0) + min(15, count * 2)
    items.sort(
        key=lambda row: (int(row.get("priorityScore") or 0), row.get("publishedAtUtc") or ""),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for key in ("fx-rates", "us-stocks", "japan-stocks", "ai-bubble", "policy"):
        candidate = next((row for row in items if row.get("topicKey") == key), None)
        if candidate and candidate["id"] not in selected_ids:
            selected.append(candidate)
            selected_ids.add(candidate["id"])
    for source_kind in ("official-us", "official-japan"):
        candidate = next((row for row in items if row.get("sourceKind") == source_kind), None)
        if candidate and candidate["id"] not in selected_ids:
            selected.append(candidate)
            selected_ids.add(candidate["id"])

    for kinds in (
        {"x-api", "x-index"},
        {"linkedin"},
        {"truth-social", "truth-social-archive"},
    ):
        candidate = next((row for row in items if row.get("sourceKind") in kinds), None)
        if candidate and candidate["id"] not in selected_ids:
            selected.append(candidate)
            selected_ids.add(candidate["id"])
    economist_candidate = next((
        row for row in items
        if any(
            name in ((row.get("title") or "") + " " + (row.get("summary") or "")).lower()
            for name in ECONOMIST_WATCH_NAMES
        )
    ), None)
    if economist_candidate and economist_candidate["id"] not in selected_ids:
        selected.append(economist_candidate)
        selected_ids.add(economist_candidate["id"])
    for stance in ("bullish", "bearish"):
        candidate = next((
            row for row in items
            if row.get("stance") == stance
            and row.get("topicKey") in {"us-stocks", "japan-stocks", "ai-bubble"}
        ), None)
        if candidate and candidate["id"] not in selected_ids:
            selected.append(candidate)
            selected_ids.add(candidate["id"])
    for item in items:
        if len(selected) >= BRIEFING_ITEM_LIMIT:
            break
        if item["id"] not in selected_ids:
            selected.append(item)
            selected_ids.add(item["id"])
    # Keep the first cards topic-diverse; the lead shock card already carries
    # the absolute top priority and each topic candidate is ranked internally.
    return selected[:BRIEFING_ITEM_LIMIT]


def channel_statuses(source_status: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for row in source_status:
        by_kind.setdefault(row.get("kind") or "other", []).append(row)

    def aggregate(
        key: str,
        label: str,
        kinds: tuple[str, ...],
        direct_url: str,
        limitation: str,
    ) -> dict[str, Any]:
        rows = [row for kind in kinds for row in by_kind.get(kind, [])]
        states = {row.get("status") for row in rows}
        if rows and states == {"ok"}:
            status = "ok"
        elif states.intersection({"ok", "limited"}):
            status = "limited"
        elif rows and states == {"not-configured"}:
            status = "not-configured"
        else:
            status = "failed"
        return {
            "key": key,
            "label": label,
            "status": status,
            "statusLabel": {
                "ok": "取得済み",
                "limited": "限定取得",
                "not-configured": "API未接続",
                "failed": "取得失敗",
            }[status],
            "directUrl": direct_url,
            "checkedAtUtc": now.isoformat(),
            "limitation": limitation,
            "messages": [row.get("message") for row in rows if row.get("message")][:3],
        }

    return [
        aggregate(
            "official",
            "日米の一次機関",
            ("official-us", "official-japan"),
            MOF_INTERVENTION_URL,
            "公表時刻と市場の値動きには時間差があります。",
        ),
        aggregate(
            "news",
            "海外ニュース・専門媒体",
            ("news-discovery", "news", "news-wire"),
            "https://www.bing.com/news",
            "記事本文の数値・引用は原文で確認します。",
        ),
        aggregate(
            "x",
            "X",
            ("x-api", "x-index"),
            "https://x.com/search?q=%28USDJPY%20OR%20%22AI%20bubble%22%20OR%20stocks%20OR%20rates%29&f=live",
            "API未接続時は公開検索索引のみで、全投稿・正確な投稿時刻・話題量を保証しません。",
        ),
        aggregate(
            "linkedin",
            "LinkedIn",
            ("linkedin",),
            "https://www.linkedin.com/search/results/content/?keywords=markets%20economy%20AI%20rates",
            "一般投稿の横断APIは使わず、公開ウェブ索引に現れた投稿だけを取得します。",
        ),
        aggregate(
            "other-social",
            "Bluesky・Truth Social",
            ("bluesky", "truth-social", "truth-social-archive"),
            "https://bsky.app/search",
            "本人の発言であることと、発言内容が正しいことを区別します。",
        ),
    ]


def build_briefing(
    items: list[dict[str, Any]],
    source_status: list[dict[str, Any]],
    shock: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    selected = rank_briefing_items(items)
    topic_counts: dict[str, int] = {}
    for item in selected:
        topic_counts[item["topicKey"]] = topic_counts.get(item["topicKey"], 0) + 1
    bull = [
        {
            "title": item["title"],
            "source": item["source"],
            "url": item["url"],
            "verification": item["verification"],
        }
        for item in selected
        if item["stance"] == "bullish"
        and item.get("topicKey") in {"us-stocks", "japan-stocks", "ai-bubble"}
    ][:4]
    bear = [
        {
            "title": item["title"],
            "source": item["source"],
            "url": item["url"],
            "verification": item["verification"],
        }
        for item in selected
        if item["stance"] == "bearish"
        and item.get("topicKey") in {"us-stocks", "japan-stocks", "ai-bubble"}
    ][:4]
    verification_counts: dict[str, int] = {}
    source_kind_counts: dict[str, int] = {}
    for item in selected:
        verification_counts[item["verification"]] = verification_counts.get(item["verification"], 0) + 1
        source_kind_counts[item["sourceKind"]] = source_kind_counts.get(item["sourceKind"], 0) + 1
    leading_topics = sorted(topic_counts.items(), key=lambda row: (-row[1], row[0]))
    focus = "、".join(f"{TOPICS[key]['label']} {count}件" for key, count in leading_topics[:3])
    summary = (
        f"直近の重要候補は{len(selected)}件。{focus or '新着候補なし'}です。"
        "話題度は反応数・新しさ・同テーマ件数の補助指標で、事実確認度や相場方向とは別です。"
    )
    suspected = [
        item for item in items
        if re.search(r"\bintervention\b|介入", (item.get("title") or "") + " " + (item.get("summary") or ""), re.I)
    ]
    return {
        "checkedAtUtc": now.isoformat(),
        "checkedAtJst": now.astimezone(JST).isoformat(),
        "summary": summary,
        "lead": {
            "id": "usd-jpy-shock",
            "topicKey": "fx-rates",
            "topic": "為替・金利",
            "title": shock["headline"],
            "summary": shock["summary"],
            "verification": "price-confirmed-official-unconfirmed",
            "interventionStatus": shock["interventionStatus"],
            "interventionLabel": shock["interventionLabel"],
            "talkScore": max([int(row.get("talkScore") or 0) for row in suspected] or [0]),
            "sourceCounts": {
                "official": sum(1 for row in suspected if str(row.get("sourceKind", "")).startswith("official")),
                "news": sum(1 for row in suspected if row.get("sourceKind") in {"news", "news-wire"}),
                "social": sum(1 for row in suspected if row.get("sourceKind") in {"x-api", "x-index", "linkedin", "bluesky", "truth-social", "truth-social-archive"}),
            },
            "primaryUrl": shock.get("priceSourceUrl"),
            "officialUrl": shock.get("officialVerificationUrl"),
        },
        "items": selected,
        "topicCounts": topic_counts,
        "topicLabels": {key: profile["label"] for key, profile in TOPICS.items()},
        "verificationCounts": verification_counts,
        "sourceKindCounts": source_kind_counts,
        "bullish": bull,
        "bearish": bear,
        "channels": channel_statuses(source_status, now),
        "unverifiedCount": sum(1 for row in selected if row["verification"] == "unverified"),
        "readingRule": (
            "一次機関は政策・公表内容の確認、通信社・専門媒体は速報の裏取り、SNSは論点発見に使います。"
            "XやLinkedInで多く反応されたことを、事実・確率・売買判断へ直接変換しません。"
        ),
    }


def carry_forward_if_needed(
    package: dict[str, Any],
    previous: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    current_items = ((package.get("briefing") or {}).get("items") or [])
    previous_items = ((previous.get("briefing") or {}).get("items") or [])
    if len(current_items) >= 4 or not previous_items:
        return package
    carried = []
    current_ids = {row.get("id") for row in current_items}
    for row in previous_items:
        if row.get("id") in current_ids:
            continue
        copy = dict(row)
        copy["carriedForward"] = True
        copy["staleReason"] = "今回の取得件数が不足したため前回候補を保持"
        carried.append(copy)
        if len(current_items) + len(carried) >= BRIEFING_ITEM_LIMIT:
            break
    package["briefing"]["items"] = current_items + carried
    package["dataHealth"]["carriedForwardItems"] = len(carried)
    package["dataHealth"]["status"] = "partial"
    package["dataHealth"]["message"] = (
        f"新規取得{len(current_items)}件。前回候補{len(carried)}件を時刻表示付きで保持しました。"
    )
    package["briefing"]["summary"] += f" 取得不足のため前回候補{len(carried)}件を保持しています。"
    package["fallbackAppliedAtUtc"] = now.isoformat()
    return package


def build_live_package(previous: dict[str, Any] | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    previous = previous or {}
    quotes, quote_status = fetch_intraday_quotes(now)
    source_status: list[dict[str, Any]] = list(quote_status)
    items: list[dict[str, Any]] = []
    jobs: list[tuple[str, Any, dict[str, str] | None]] = []
    for feed in OFFICIAL_FEEDS:
        jobs.append(("official", fetch_official_feed, feed))
    for query_def in NEWS_QUERIES:
        jobs.append(("news", fetch_bing_news, query_def))
        jobs.append(("news", fetch_google_news, query_def))
    for search_def in PUBLIC_SOCIAL_SEARCHES:
        jobs.append(("social-index", fetch_public_social_index, search_def))

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(function, definition, now): (job_type, definition)
            for job_type, function, definition in jobs
        }
        futures[executor.submit(fetch_x_api, now)] = ("x-api", None)
        futures[executor.submit(fetch_bluesky, now)] = ("bluesky", None)
        futures[executor.submit(fetch_truth_social, now)] = ("truth-social", None)
        for future in as_completed(futures):
            job_type, definition = futures[future]
            try:
                fetched_items, status = future.result()
                items.extend(fetched_items)
                source_status.append(status)
            except Exception as exc:
                name = (
                    (definition or {}).get("name")
                    or (definition or {}).get("key")
                    or job_type
                )
                source_status.append({
                    "name": str(name),
                    "kind": job_type,
                    "status": "failed",
                    "url": (definition or {}).get("url", ""),
                    "retrievedAtUtc": now.isoformat(),
                    "message": str(exc),
                })

    items.extend(audited_current_event_items(now))
    items.extend(audited_current_market_items(now))
    shock = build_market_shock(quotes, now)
    update_intervention_assessment(shock, items)
    premarket = build_premarket(quotes, now)
    briefing = build_briefing(items, source_status, shock, now)
    failed = sum(1 for row in source_status if row.get("status") == "failed")
    successful = sum(1 for row in source_status if row.get("status") in {"ok", "limited"})
    limited = sum(1 for row in source_status if row.get("status") == "limited")
    skipped = sum(1 for row in source_status if row.get("status") == "not-configured")
    health_status = "ok" if failed == 0 and limited == 0 and skipped == 0 else "partial"
    health_parts = []
    if failed:
        health_parts.append(f"取得失敗{failed}経路")
    if limited:
        health_parts.append(f"限定取得{limited}経路")
    if skipped:
        health_parts.append(f"API未接続{skipped}経路")
    package = {
        "schemaVersion": 1,
        "generatedAtUtc": now.isoformat(),
        "generatedAtJst": now.astimezone(JST).isoformat(),
        "refreshPolicy": {
            "targetIntervalMinutes": 15,
            "delivery": "GitHub Actions scheduled snapshot",
            "buttonBehavior": "公開版の更新ボタンは最後に配信済みのスナップショットを再読込",
            "warning": "GitHub Actionsの混雑・取得元障害で15分を超える場合があります。",
        },
        "dataHealth": {
            "status": health_status,
            "successfulSources": successful,
            "failedSources": failed,
            "limitedSources": limited,
            "skippedSources": skipped,
            "carriedForwardItems": 0,
            "message": "全取得経路を更新しました。" if not health_parts else "、".join(health_parts) + "。取得できた情報だけを表示します。",
        },
        "marketShock": shock,
        "premarket": premarket,
        "briefing": briefing,
        "sourceStatus": source_status,
        "methodology": {
            "intervention": (
                "価格急変と介入確認を分離。価格条件はアラートだけに使い、"
                "財務省の一次公表が確認できるまで officiallyConfirmed=false とする。"
            ),
            "talkScore": (
                "新しさ、同テーマ件数、取得できた公開反応数、出所種別から0–100へ正規化。"
                "媒体横断の全投稿数でも危険確率でもない。"
            ),
            "stance": (
                "見出し・投稿中の限定語彙から強気・弱気・混合・中立を分類。"
                "投資判断、著者の全体見解、記事本文の精読を代替しない。"
            ),
        },
    }
    return carry_forward_if_needed(package, previous, now)


def write_live_package(path: Path = OUTPUT) -> dict[str, Any]:
    previous: dict[str, Any] = {}
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    package = build_live_package(previous)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    return package


def main() -> None:
    package = write_live_package()
    briefing = package.get("briefing") or {}
    print(
        "Wrote "
        f"{OUTPUT} with {len(briefing.get('items') or [])} briefing items, "
        f"{len((package.get('premarket') or {}).get('quotes') or {})} live quotes, "
        f"{package['dataHealth']['failedSources']} failed sources"
    )


if __name__ == "__main__":
    main()
