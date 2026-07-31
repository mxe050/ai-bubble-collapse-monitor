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
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "live-intelligence.json"
USER_AGENT = "mxe050-ai-bubble-monitor-live/1.0 (https://github.com/mxe050)"
JST = timezone(timedelta(hours=9))
BRIEFING_ITEM_LIMIT = 24
LATEST_ITEM_RESERVE = 10
ORIGINAL_EXCERPT_LIMIT = 280
PUBLIC_SNAPSHOT_URL = (
    "https://mxe050.github.io/ai-bubble-collapse-monitor/data/live-intelligence.json"
)
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
DEEPL_BATCH_LIMIT = 50

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
    "SP500_CASH": {
        "symbol": "^GSPC",
        "label": "S&P 500（現物）",
        "shortLabel": "S&P現物",
        "group": "us",
        "currency": "INDEX",
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
    "DXY": {
        "symbol": "DX-Y.NYB",
        "label": "米ドル指数",
        "shortLabel": "DXY",
        "group": "fx",
        "currency": "INDEX",
        "role": "dollar-index",
    },
    "ACWI_CASH": {
        "symbol": "ACWI",
        "label": "ACWI（全世界株ETF）",
        "shortLabel": "ACWI",
        "group": "global",
        "currency": "USD",
        "role": "world-equity",
    },
    "KIOXIA": {
        "symbol": "285A.T",
        "label": "キオクシアHD",
        "shortLabel": "キオクシア",
        "group": "japan",
        "currency": "JPY",
        "role": "company-price",
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

# Keep the morning-strategy cards focused on the nine existing futures, FX,
# rates, and volatility cues.  The additional live cash quotes below are for
# overlays elsewhere in the monitor, not extra pre-market cards.
PREMARKET_DISPLAY_KEYS = (
    "NIKKEI_FUTURES_YEN", "NIKKEI_FUTURES_USD",
    "SP500_FUTURES", "NASDAQ100_FUTURES", "DOW_FUTURES", "RUSSELL2000_FUTURES",
    "USDJPY", "US10Y", "VIX",
)
MARKET_SUMMARY_OVERLAY_KEYS = (
    "NIKKEI_CASH", "SP500_CASH", "DXY", "ACWI_CASH", "KIOXIA",
)

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
    {
        "name": "U.S. Bureau of Labor Statistics",
        "url": "https://www.bls.gov/feed/bls_latest.rss",
        "kind": "official-us",
    },
    {
        "name": "U.S. Securities and Exchange Commission",
        "url": "https://www.sec.gov/news/pressreleases.rss",
        "kind": "official-us",
    },
)

COMPANY_DISCLOSURE_FEEDS = (
    {
        "name": "TDnet 適時開示（全上場会社）",
        "url": "https://www.release.tdnet.info/inbs/I_main_00.html",
        "kind": "official-company",
        "statusKind": "company-disclosure",
        "topic": "japan-stocks",
        "sourceCountry": "JP",
        # Continue only until the previous watermark is reached.  The cap
        # prevents unexpected HTML changes from creating unbounded traffic.
        "maxPages": 20,
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
        "key": "japan-stocks",
        "name": "日本株・決算サプライズ",
        "query": (
            "(決算 OR 業績予想 OR 上方修正 OR 下方修正 OR 自社株買い "
            "OR 株式分割 OR TOB) "
            "(急騰 OR 急落 OR 市場予想 OR サプライズ OR 株価 OR 日本株)"
        ),
        "providers": ("google", "bing"),
        "googleLocale": {"hl": "ja", "gl": "JP", "ceid": "JP:ja"},
        "bingLanguage": "ja-JP",
        "requiredAnyTerms": (
            "決算", "業績", "上方修正", "下方修正", "自社株買い",
            "自己株式", "株式分割", "tob",
        ),
        "maxAgeHours": 36,
        "acceptedLimit": 20,
    },
    {
        "key": "japan-stocks",
        "name": "日本株・適時開示の市場反応",
        "query": (
            "(日本株 OR 東証 OR 日経平均 OR TOPIX) "
            "(決算 OR ストップ高 OR ストップ安 OR 急騰 OR 急落 OR 売買代金)"
        ),
        "providers": ("google", "bing"),
        "googleLocale": {"hl": "ja", "gl": "JP", "ceid": "JP:ja"},
        "bingLanguage": "ja-JP",
        "requiredAnyTerms": (
            "日本株", "東証", "日経", "topix", "決算", "急騰", "急落",
            "ストップ高", "ストップ安", "売買代金",
        ),
        "maxAgeHours": 24,
        "acceptedLimit": 16,
    },
    {
        "key": "japan-stocks",
        "name": "Japan corporate earnings movers",
        "query": (
            '(Japan OR Japanese OR Tokyo OR Nikkei) '
            '(earnings OR results OR guidance OR buyback OR "stock split" OR "tender offer") '
            '(shares OR stock OR market)'
        ),
        "providers": ("google", "bing"),
        "googleLocale": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
        "bingLanguage": "en-US",
        "requiredAnyTerms": (
            "japan", "japanese", "tokyo", "nikkei", "earnings", "results",
            "guidance", "buyback", "stock split", "tender offer",
        ),
        "maxAgeHours": 36,
        "acceptedLimit": 16,
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

GDELT_QUERIES = (
    {
        "key": "markets",
        "query": (
            '("Wall Street" OR Nasdaq OR Nikkei OR TOPIX OR USDJPY OR yen OR '
            '"AI bubble" OR semiconductor OR "Treasury yield") sourcelang:english'
        ),
    },
    {
        "key": "policy",
        "query": (
            '("Federal Reserve" OR FOMC OR "U.S. Treasury" OR "White House" OR '
            '"Bank of Japan" OR intervention OR tariff) sourcelang:english'
        ),
    },
    {
        "key": "economists",
        "query": (
            '("Mohamed El-Erian" OR "Jason Furman" OR "Claudia Sahm" OR '
            '"Liz Ann Sonders" OR "Jim Bianco") sourcelang:english'
        ),
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

TRANSLATION_MODES = {
    "source-japanese",
    "editorial-summary",
    "deepl",
    "structured-gist",
    "unavailable",
}

REFERENCE_TRANSLATION_RULES = (
    (r"\bU\.?S\.?\b", "米国"),
    (r"\bWall Street\b", "米国株市場"),
    (r"\bFederal Reserve\b", "FRB"),
    (r"\bBank of Japan\b", "日本銀行"),
    (r"\bTreasury yields?\b", "米国債利回り"),
    (r"\binterest rates?\b", "金利"),
    (r"\brate cuts?\b", "利下げ"),
    (r"\brate hikes?\b", "利上げ"),
    (r"\bartificial intelligence\b", "AI"),
    (r"\bAI spending\b", "AI投資"),
    (r"\bAI expenses?\b", "AI関連費用"),
    (r"\bAI stocks?\b", "AI関連株"),
    (r"\bstocks?\b", "株式"),
    (r"\bequities\b", "株式"),
    (r"\bmarkets?\b", "市場"),
    (r"\bJapanese Yen\b", "円"),
    (r"\bJapan(?:'s|’s) yen\b", "円"),
    (r"\byen\b", "円"),
    (r"\bU\.?S\.? dollar\b", "米ドル"),
    (r"\bdollar\b", "ドル"),
    (r"\bintervention\b", "為替介入"),
    (r"\bsuspected\b", "疑いのある"),
    (r"\bspeculation\b", "観測"),
    (r"\banalysts?\b", "アナリスト"),
    (r"\btraders?\b", "市場参加者"),
    (r"\binvestors?\b", "投資家"),
    (r"\bearnings\b", "決算"),
    (r"\brevenue\b", "売上高"),
    (r"\bprofit\b", "利益"),
    (r"\binflation\b", "インフレ"),
    (r"\brecession\b", "景気後退"),
    (r"\btariffs?\b", "関税"),
    (r"\bvaluation\b", "バリュエーション"),
    (r"\bcapex\b", "設備投資"),
    (r"\bdata centers?\b", "データセンター"),
    (r"\bsemiconductors?\b", "半導体"),
    (r"\bbubble\b", "バブル"),
    (r"\brally\b", "上昇"),
    (r"\bsell[- ]?off\b", "売り"),
    (r"\bplung(?:e|es|ed|ing)\b", "急落"),
    (r"\bsurg(?:e|es|ed|ing)\b", "急伸"),
    (r"\bjumps?\b", "急伸"),
    (r"\brises?\b", "上昇"),
    (r"\bgains?\b", "上昇"),
    (r"\bfalls?\b", "下落"),
    (r"\bdrops?\b", "下落"),
    (r"\bslumps?\b", "下落"),
    (r"\bwarns?\b", "警告"),
    (r"\bwarning\b", "警戒"),
    (r"\bconcerns?\b", "懸念"),
    (r"\bworries\b", "懸念"),
    (r"\boutlook\b", "見通し"),
    (r"\bafter\b", "を受け"),
    (r"\bahead of\b", "を前に"),
    (r"\bamid\b", "を背景に"),
    (r"\bwhile\b", "一方で"),
    (r"\bas\b", "を受け"),
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
    data: bytes | None = None,
    method: str | None = None,
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
            req = urllib.request.Request(
                url,
                headers=base_headers,
                data=data,
                method=method,
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read(), response.geturl()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                if exc.code == 429:
                    retry_after = (
                        exc.headers.get("Retry-After")
                        if exc.headers is not None
                        else None
                    )
                    try:
                        delay = float(retry_after) if retry_after else 5.0
                    except (TypeError, ValueError):
                        delay = 5.0
                    time.sleep(max(5.0, min(delay, 30.0)))
                else:
                    time.sleep(0.7 * (attempt + 1))
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


def has_japanese(value: str) -> bool:
    return re.search(r"[ぁ-んァ-ン一-龥々〆ヶ]", value or "") is not None


def language_of(value: str) -> str:
    if has_japanese(value):
        return "ja"
    if re.search(r"[A-Za-z]", value or ""):
        return "en"
    return "und"


def normalized_comparison_text(value: str) -> str:
    return re.sub(
        r"[^a-z0-9一-龥ぁ-んァ-ン]+",
        "",
        unicodedata.normalize("NFKC", clean_text(value)).casefold(),
    )


def source_suffix_removed(value: str) -> str:
    return re.sub(
        r"\s+(?:[-–—|]\s*)?(?:Reuters|Bloomberg|Associated Press|AP News|"
        r"Financial Times|Wall Street Journal|WSJ|CNBC|Axios|Yahoo Finance|"
        r"Investing\.com|FXStreet)(?:\s*)$",
        "",
        clean_text(value),
        flags=re.I,
    ).strip(" -–—|")


def original_excerpt(title: str, summary: str) -> str:
    candidate = clean_text(summary)
    if not candidate:
        return ""
    left = normalized_comparison_text(source_suffix_removed(title))
    right = normalized_comparison_text(source_suffix_removed(candidate))
    if left and right and (
        left == right
        or SequenceMatcher(None, left, right).ratio() >= 0.88
        or left in right and len(right) <= len(left) + 32
    ):
        return ""
    return candidate[:ORIGINAL_EXCERPT_LIMIT].rstrip()


def structured_headline_subject(title: str) -> str:
    """Extract only a short named subject; never present a word-swapped headline."""

    cleaned = source_suffix_removed(clean_text(title))
    ticker_match = re.match(
        r"^(.{1,60}?)\s*\((?:NASDAQ|NYSE|AMEX|OTC|TSE|TYO):[A-Z0-9.:-]+\)",
        cleaned,
        re.I,
    )
    if ticker_match:
        subject = ticker_match.group(1).strip(" :,-–—|")
    else:
        known_subjects = (
            (r"\bUSD/?JPY\b", "ドル円"),
            (r"\bJapanese Yen\b|\bYen\b", "円相場"),
            (r"\bBank of Japan\b", "日本銀行"),
            (r"\bFederal Reserve\b|\bFOMC\b", "FRB"),
            (r"\bU\.?S\.? Treasury\b", "米財務省"),
            (r"\bWall Street\b", "米国株市場"),
            (r"\bS&P 500\b", "S&P 500"),
            (r"\bNasdaq\b", "Nasdaq"),
            (r"\bMicrosoft\b", "Microsoft"),
            (r"\bApple\b", "Apple"),
            (r"\bNvidia\b", "NVIDIA"),
            (r"\bGold\b", "金相場"),
            (r"\bMohamed El-Erian\b", "Mohamed El-Erian"),
        )
        subject = next(
            (
                label
                for pattern, label in known_subjects
                if re.search(pattern, cleaned, re.I)
            ),
            "",
        )
        if not subject:
            first = re.match(r"^([A-Z][A-Za-z0-9&.'-]{1,30})\b", cleaned)
            candidate = first.group(1) if first else ""
            disallowed = {
                "the", "a", "an", "less", "even", "does", "do", "why", "how",
                "what", "after", "as", "us", "u.s", "japan", "japanese",
            }
            subject = "" if candidate.casefold().rstrip(".") in disallowed else candidate
    aliases = {
        "yen": "円相場",
        "japanese yen": "円相場",
        "usd/jpy": "ドル円",
        "usdjpy": "ドル円",
        "federal reserve": "FRB",
        "wall street": "米国株市場",
        "gold": "金相場",
        "u.s.": "米国市場",
        "us": "米国市場",
    }
    subject = aliases.get(subject.casefold(), subject)
    if not subject or len(subject) > 44:
        return ""
    return subject


def structured_event_label(title: str, topic_label: str) -> str:
    lowered = title.casefold()
    rules = (
        (r"\binterven(?:e|ed|es|ing|tion|tions)\b|介入", "為替介入観測と円相場の急変"),
        (r"\bearnings?\b|\bresults?\b|\boutlook\b|\brevenue\b|\bsales\b|\bestimates?\b|\bq[1-4]\b|\bfull-year\b", "決算・業績見通し"),
        (r"\bfederal reserve\b|\bfomc\b|\brate\b|\byield\b|\bborrowing cost", "金融政策・金利"),
        (r"\bai\b|artificial intelligence|semiconductor|nvidia", "AI投資・評価"),
        (r"\btariffs?\b|trade policy|sanction", "関税・通商政策"),
        (r"\brally\b|\bsurge\b|\bgain\b|\bjump\b|\bhigher\b|\brebound\b", "相場上昇"),
        (r"\bselloff\b|\bplunge\b|\bdrop\b|\bslump\b|\blower\b|\bdecline\b", "相場下落"),
    )
    for pattern, label in rules:
        if re.search(pattern, lowered, re.I):
            return label
    return f"{topic_label}の新着材料"


def structured_japanese_title(title: str, topic_label: str, source: str) -> str:
    subject = structured_headline_subject(title)
    event_label = structured_event_label(title, topic_label)
    prefix = subject or topic_label
    if not subject and event_label == f"{topic_label}の新着材料":
        return f"{topic_label}：海外の新着材料"
    return f"{prefix}：{event_label}に関する海外速報"


def freshness_profile(
    effective_at: datetime | None,
    retrieved_at: datetime,
    timestamp_precision: str,
) -> dict[str, Any]:
    if effective_at is None or timestamp_precision == "unknown":
        return {
            "bucket": "unknown",
            "label": "時刻未確認",
            "ageMinutes": None,
        }
    age_minutes = max(0, round((retrieved_at - effective_at).total_seconds() / 60))
    if timestamp_precision == "date":
        bucket, label = "context", "日付のみ"
    elif age_minutes <= 30:
        bucket, label = "breaking", "30分以内"
    elif age_minutes <= 180:
        bucket, label = "developing", "3時間以内"
    elif age_minutes <= 1440:
        bucket, label = "today", "24時間以内"
    else:
        bucket, label = "context", "背景情報"
    return {
        "bucket": bucket,
        "label": label,
        "ageMinutes": age_minutes,
    }


def effect_profile(topic_key: str, text: str, stance: str) -> dict[str, str]:
    lowered = text.casefold()
    if topic_key == "ai-bubble":
        target = "AI関連株"
    elif topic_key == "us-stocks":
        target = "米国株"
    elif topic_key == "japan-stocks":
        target = "日本株"
    elif topic_key == "fx-rates" and re.search(r"\byen\b|円", lowered):
        target = "円"
        if any(term in lowered for term in ("surge", "jump", "strengthen", "gain", "急伸", "円高")):
            stance = "bullish"
        elif any(term in lowered for term in ("plunge", "weaken", "drop", "下落", "円安")):
            stance = "bearish"
    elif topic_key == "fx-rates":
        target = "為替・金利"
    else:
        target = "政策・市場"
    direction = {
        "bullish": "強気",
        "bearish": "弱気",
        "mixed": "強弱混在",
        "neutral": "方向なし",
    }.get(stance, "方向未分類")
    return {
        "target": target,
        "direction": stance,
        "label": f"{target}に{direction}",
    }


def translation_source_hash(title: str, excerpt: str) -> str:
    return hashlib.sha256((title + "\n" + excerpt).encode("utf-8")).hexdigest()


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
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
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        for key in ("url", "u", "target"):
            candidate = query.get(key, [None])[0]
            if candidate and candidate.startswith(("http://", "https://")):
                return normalize_url(urllib.parse.unquote(candidate))
        tracking_keys = {
            "fbclid",
            "gclid",
            "mc_cid",
            "mc_eid",
            "ref",
            "ref_src",
            "source",
        }
        kept_pairs = [
            (key, item)
            for key, values in query.items()
            if not key.casefold().startswith("utm_")
            and key.casefold() not in tracking_keys
            for item in values
        ]
        # The public package deliberately accepts only encrypted article links.
        # Upgrade discovery feeds that still publish an http URL instead of
        # letting one legacy link invalidate the otherwise complete snapshot.
        scheme = "https" if parsed.scheme.casefold() == "http" else parsed.scheme
        return urllib.parse.urlunparse((
            scheme,
            parsed.netloc.lower(),
            parsed.path,
            "",
            urllib.parse.urlencode(sorted(kept_pairs), doseq=True),
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


def timestamp_precision(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return "date"
    if re.search(r"(?:T|\s)\d{2}:\d{2}:\d{2}", text) or re.search(
        r"\b\d{2}:\d{2}:\d{2}\b", text
    ):
        return "second"
    if re.search(r"(?:T|\s)\d{2}:\d{2}", text) or re.search(
        r"\b\d{2}:\d{2}\b", text
    ):
        return "minute"
    return "date" if parse_datetime(text) else "unknown"


def publisher_domain(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def reporting_origin_group(source: str, url: str) -> str:
    text = f"{source} {publisher_domain(url)}".casefold()
    aliases = (
        ("reuters", "reuters"),
        ("associated press", "associated-press"),
        ("ap news", "associated-press"),
        ("bloomberg", "bloomberg"),
        ("financial times", "financial-times"),
        ("wall street journal", "wall-street-journal"),
        ("wsj", "wall-street-journal"),
        ("federal reserve", "federal-reserve"),
        ("treasury.gov", "us-treasury"),
        ("whitehouse.gov", "white-house"),
        ("boj.or.jp", "bank-of-japan"),
        ("mof.go.jp", "japan-mof"),
        ("release.tdnet.info", "tdnet-official"),
        ("bls.gov", "us-bls"),
        ("sec.gov", "us-sec"),
    )
    for needle, group in aliases:
        if needle in text:
            return group
    domain = publisher_domain(url)
    if domain in {
        "news.google.com",
        "bing.com",
        "www.bing.com",
    }:
        # RSS aggregators are discovery paths; the feed's source field names
        # the actual publisher used for independence counts.
        return normalized_comparison_text(source)[:80] or domain
    if domain.startswith("www."):
        domain = domain[4:]
    return domain or normalized_comparison_text(source)[:80] or "unknown"


def story_cluster_id(title: str, topic_key: str) -> str:
    normalized = normalized_comparison_text(source_suffix_removed(title))
    digest = hashlib.sha1(f"{topic_key}\n{normalized}".encode("utf-8")).hexdigest()
    return "cluster-" + digest[:14]


def japanese_payload(
    *,
    title: str,
    summary: str,
    excerpt: str,
    topic_label: str,
    source: str,
    effect: dict[str, str],
    retrieved_at: datetime,
) -> dict[str, Any]:
    source_hash = translation_source_hash(title, excerpt)
    if has_japanese(title):
        return {
            "title": title,
            "summary": summary,
            "mode": "source-japanese",
            "label": "日本語原文",
            "provider": None,
            "generatedAtUtc": retrieved_at.isoformat(),
            "sourceHash": source_hash,
        }
    if has_japanese(summary):
        return {
            "title": structured_japanese_title(title, topic_label, source),
            "summary": summary,
            "mode": "editorial-summary",
            "label": "編集要約",
            "provider": None,
            "generatedAtUtc": retrieved_at.isoformat(),
            "sourceHash": source_hash,
        }
    event_label = structured_event_label(title, topic_label)
    subject = structured_headline_subject(title)
    subject_text = f"{subject}について、" if subject else ""
    direction = {
        "bullish": "強気材料", "bearish": "弱気材料",
        "mixed": "強弱が混在する材料",
        "neutral": "方向性を特定しない材料",
    }.get(effect.get("direction"), "方向未分類の材料")
    return {
        "title": structured_japanese_title(title, topic_label, source),
        "summary": (
            f"{source or '海外媒体'}が{subject_text}{event_label}を報じています。"
            f"見出し分類は「{direction}」です。これは翻訳ではなく、"
            "数値・固有名詞・文脈は右側の原文で確認してください。"
        ),
        "mode": "structured-gist",
        "label": "構造化要旨（翻訳ではありません）",
        "provider": None,
        "generatedAtUtc": retrieved_at.isoformat(),
        "sourceHash": source_hash,
    }


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
    indexed_at: Any = None,
    first_seen_at: Any = None,
    timestamp_basis: str | None = None,
    timestamp_precision_value: str | None = None,
    discovery_provider: str = "direct",
    source_country: str = "",
) -> dict[str, Any]:
    clean_title = clean_text(title)
    clean_summary = clean_text(summary)
    topic_key, topic_label = classify_topic(clean_title + " " + clean_summary, topic_hint)
    published_at = iso_or_none(published)
    published_dt = parse_datetime(published_at)
    indexed_at_utc = iso_or_none(indexed_at)
    indexed_dt = parse_datetime(indexed_at_utc)
    effective_dt = published_dt or indexed_dt
    effective_at = effective_dt.astimezone(timezone.utc).isoformat() if effective_dt else None
    first_seen_dt = parse_datetime(first_seen_at) or retrieved_at
    first_seen_utc = first_seen_dt.astimezone(timezone.utc).isoformat()
    precision = timestamp_precision_value or timestamp_precision(published or indexed_at)
    basis = timestamp_basis or (
        "publisher-feed"
        if published_dt
        else "index-seen"
        if indexed_dt
        else "unknown"
    )
    age_hours = (
        max(0.0, (retrieved_at - effective_dt).total_seconds() / 3600.0)
        if effective_dt else None
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
    stance = classify_stance(clean_title + " " + clean_summary)
    effect = effect_profile(topic_key, clean_title + " " + clean_summary, stance)
    excerpt = original_excerpt(clean_title, clean_summary)
    original_language = language_of(clean_title)
    if original_language == "en" and has_japanese(excerpt):
        excerpt = ""
    japanese = japanese_payload(
        title=clean_title,
        summary=clean_summary,
        excerpt=excerpt,
        topic_label=topic_label,
        source=source,
        effect=effect,
        retrieved_at=retrieved_at,
    )
    freshness = freshness_profile(effective_dt, retrieved_at, precision)
    freshness["firstSeenAtUtc"] = first_seen_utc
    origin_group = reporting_origin_group(source, url)
    cluster_id = story_cluster_id(clean_title, topic_key)
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
        "stance": stance,
        "engagement": engagement,
        "engagementTotal": engagement_total,
        "priorityScore": priority,
        "talkScore": 0,
        "author": author,
        "identityNote": identity_note,
        "original": {
            "language": original_language,
            "title": clean_title,
            "excerpt": excerpt,
        },
        "japanese": japanese,
        "effectivePublishedAtUtc": effective_at,
        "indexedAtUtc": indexed_at_utc,
        "firstSeenAtUtc": first_seen_utc,
        "timestampBasis": basis,
        "timestampPrecision": precision,
        "freshness": freshness,
        "effect": [{
            **effect,
            "basis": "headline-keyword-classifier",
        }],
        "clusterId": cluster_id,
        "clusterSize": 1,
        "rankingClusterSize": 1,
        "independentSourceCount": 1,
        "corroborationState": "single-source",
        "relatedLinks": [],
        "originGroup": origin_group,
        "publisherDomain": publisher_domain(url),
        "sourceCountry": clean_text(source_country),
        "discoveryProvider": discovery_provider,
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


def _trough_to_peak(points: list[dict[str, Any]]) -> dict[str, Any]:
    if len(points) < 2:
        return {"points": None, "pct": None, "startUtc": None, "endUtc": None}
    trough = points[0]
    best = {
        "points": 0.0,
        "pct": 0.0,
        "startUtc": datetime.fromtimestamp(trough["timestamp"], timezone.utc).isoformat(),
        "endUtc": datetime.fromtimestamp(trough["timestamp"], timezone.utc).isoformat(),
    }
    for row in points[1:]:
        advance = row["value"] - trough["value"]
        if advance > best["points"]:
            best = {
                "points": advance,
                "pct": advance / trough["value"] * 100.0 if trough["value"] else None,
                "startUtc": datetime.fromtimestamp(trough["timestamp"], timezone.utc).isoformat(),
                "endUtc": datetime.fromtimestamp(row["timestamp"], timezone.utc).isoformat(),
            }
        if row["value"] < trough["value"]:
            trough = row
    return best


def _sample_weekly_sparkline(
    points: list[dict[str, Any]], max_points: int = 168
) -> list[dict[str, Any]]:
    """Keep a readable, evenly spaced view of the latest five trading days."""
    if len(points) <= max_points:
        return points
    last_index = len(points) - 1
    selected = {
        round(position * last_index / (max_points - 1))
        for position in range(max_points)
    }
    return [points[index] for index in sorted(selected)]


def _latest_trading_days(
    points: list[dict[str, Any]], exchange_timezone: str | None, days: int = 5
) -> list[dict[str, Any]]:
    """Return the newest market-calendar days that have intraday prices."""
    try:
        market_timezone = ZoneInfo(exchange_timezone) if exchange_timezone else timezone.utc
    except ZoneInfoNotFoundError:
        market_timezone = timezone.utc

    dates: set[Any] = set()
    for row in reversed(points):
        market_date = datetime.fromtimestamp(
            row["timestamp"], timezone.utc
        ).astimezone(market_timezone).date()
        dates.add(market_date)
        if len(dates) == days:
            break

    return [
        row
        for row in points
        if datetime.fromtimestamp(
            row["timestamp"], timezone.utc
        ).astimezone(market_timezone).date() in dates
    ]


def fetch_intraday_quote(key: str, profile: dict[str, str], now: datetime) -> dict[str, Any]:
    symbol = profile["symbol"]
    encoded = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
        "?range=14d&interval=5m&includePrePost=true&events=div%2Csplits"
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
    # A delayed or closed-market quote is still useful as a reference price, but
    # its old five-minute candles are not current short-term market evidence.
    # Do not let them create false intraday moves or intervention alerts.
    short_term_points = recent_points if stale_minutes <= 30 * 60 else []
    # The longer source window makes the display resilient to weekends and
    # holidays. It is deliberately separate from the 30-hour short-term move
    # metrics: the chart shows only the newest five trading days.
    spark = _sample_weekly_sparkline(
        _latest_trading_days(points, meta.get("exchangeTimezoneName"))
    )
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
        "move5m": _max_window_move(short_term_points, 5),
        "move15m": _max_window_move(short_term_points, 15),
        "move30m": _max_window_move(short_term_points, 30),
        "peakToTrough": _peak_to_trough(short_term_points),
        "troughToPeak": _trough_to_peak(short_term_points),
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
    trough_to_peak = finite((fx.get("troughToPeak") or {}).get("pct"))
    move_pcts = [
        finite((fx.get(key) or {}).get("pct"))
        for key in ("move5m", "move15m", "move30m")
    ]
    move_points = [
        finite((fx.get(key) or {}).get("points"))
        for key in ("move5m", "move15m", "move30m")
    ]
    signed_moves = [value for value in [day_change, *move_pcts] if value is not None]
    down_score = max(
        [max(0.0, peak_to_trough or 0.0)]
        + [abs(value) for value in signed_moves if value < 0]
    )
    up_score = max(
        [max(0.0, trough_to_peak or 0.0)]
        + [value for value in signed_moves if value > 0]
    )
    if not fx:
        shock_direction = "unknown"
    elif down_score > up_score + 1e-9:
        shock_direction = "yen-strengthening"
    elif up_score > down_score + 1e-9:
        shock_direction = "yen-weakening"
    else:
        shock_direction = "mixed"
    magnitude = max(
        abs(day_change or 0.0),
        abs(range_pct or 0.0),
        abs(peak_to_trough or 0.0),
        abs(trough_to_peak or 0.0),
        *(abs(value or 0.0) for value in move_pcts),
    )
    directional_points = max(
        abs(finite((fx.get("peakToTrough") or {}).get("points")) or 0.0),
        abs(finite((fx.get("troughToPeak") or {}).get("points")) or 0.0),
    )
    move30_points = abs(finite((fx.get("move30m") or {}).get("points")) or 0.0)
    if magnitude >= 2.0 or directional_points >= 3.0:
        severity = "critical"
        severity_label = "重大な急変"
    elif magnitude >= 1.0 or move30_points >= 1.5:
        severity = "warning"
        severity_label = "急変を監視"
    elif fx:
        severity = "normal"
        severity_label = "通常範囲"
    else:
        severity = "unknown"
        severity_label = "取得不能"
    if severity in {"critical", "warning"} and shock_direction == "yen-strengthening":
        intervention_status = "price-shock-only"
        intervention_label = "円高方向の急変・介入は公式未確認"
        headline = "USD/JPYで円高方向の急変を検知。介入実施はまだ確定できません"
        summary = (
            "価格データから大幅な円高方向の動きを即時検知しました。値動きだけでは為替介入、"
            "要人発言、金利材料、ポジション解消を区別できないため、財務省の公表と会見を待って確認します。"
        )
    elif severity in {"critical", "warning"} and shock_direction == "yen-weakening":
        intervention_status = "yen-weakening-shock"
        intervention_label = "円安方向の急変・円買い介入判定対象外"
        headline = "USD/JPYで円安方向の急変を検知。実施済み円買い介入の価格証拠ではありません"
        summary = (
            "ドル円の上昇は円安方向です。円買い介入が実施された直後に想定する円高方向とは逆なので、"
            "この値動きだけを介入観測として扱いません。介入警戒や要人発言とは分けて表示します。"
        )
    elif severity in {"critical", "warning"}:
        intervention_status = "price-shock-only"
        intervention_label = "方向混在の急変・介入判定保留"
        headline = "USD/JPYで方向の混在する急変を検知。介入判定は保留します"
        summary = (
            "複数の観測窓で上昇と下落が混在しています。方向が定まらないため、"
            "値動きだけから円買い介入を推測せず、一次公表と主要報道を待ちます。"
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
        "shockDirection": shock_direction,
        "directionMetrics": {
            "yenStrengtheningScorePct": round(down_score, 4),
            "yenWeakeningScorePct": round(up_score, 4),
        },
        "headline": headline,
        "summary": summary,
        "interventionStatus": intervention_status,
        "interventionLabel": intervention_label,
        "officiallyConfirmed": False,
        "assessmentRule": (
            "前日比、5・15・30分の符号付き変化、高値→安値、安値→高値を比較して方向を判定。"
            "変化率1%以上または30分1.5円以上を監視、2%以上または方向別3円以上を重大とする。"
            "円高方向だけを円買い介入の価格観測候補にし、報道は方向別急変終了後3時間以内で照合。"
            "閾値だけでは介入認定しない。"
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
        "troughToPeak": fx.get("troughToPeak"),
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

    direction = shock.get("shockDirection")
    candidates: list[tuple[tuple[float, float], datetime, datetime]] = []
    extreme_key = (
        "peakToTrough"
        if direction == "yen-strengthening"
        else "troughToPeak"
        if direction == "yen-weakening"
        else None
    )
    for key in tuple(
        candidate
        for candidate in (extreme_key, "move5m", "move15m", "move30m")
        if candidate
    ):
        move = shock.get(key) or {}
        start = parse_datetime(move.get("startUtc"))
        end = parse_datetime(move.get("endUtc"))
        if start is None or end is None or end < start:
            continue
        signed_pct = finite(move.get("pct"))
        signed_points = finite(move.get("points"))
        if key.startswith("move"):
            if direction == "yen-strengthening" and (signed_pct or 0.0) >= 0:
                continue
            if direction == "yen-weakening" and (signed_pct or 0.0) <= 0:
                continue
        score = (
            abs(signed_pct or 0.0),
            abs(signed_points or 0.0),
        )
        candidates.append((score, start, end))
    reference = (
        parse_datetime(shock.get("observedAtUtc"))
        or parse_datetime(shock.get("checkedAtUtc"))
    )
    if reference is not None:
        recent_candidates = [
            candidate
            for candidate in candidates
            if -300
            <= (reference - candidate[2]).total_seconds()
            <= 180 * 60
        ]
        if recent_candidates:
            candidates = recent_candidates
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
    event_reference = (
        parse_datetime(shock.get("observedAtUtc"))
        or parse_datetime(shock.get("checkedAtUtc"))
    )
    event_lag_seconds = (
        (event_reference - event_end).total_seconds()
        if event_reference is not None and event_end is not None
        else None
    )
    recent_directional_shock = (
        event_lag_seconds is not None
        and -300 <= event_lag_seconds <= 180 * 60
    )
    shock["recentDirectionalShock"] = recent_directional_shock
    shock["directionalShockEventEndUtc"] = event_end.isoformat() if event_end else None
    eligible_directional_shock = (
        shock.get("severity") in {"critical", "warning"}
        and shock.get("shockDirection") == "yen-strengthening"
        and recent_directional_shock
    )
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
    if not eligible_directional_shock:
        evidence = []
    if evidence and eligible_directional_shock:
        shock["interventionStatus"] = "reported-unconfirmed"
        shock["interventionLabel"] = "主要報道が介入観測・公式確認なし"
        shock["headline"] = "USD/JPYの急変で介入観測。主要報道あり、公式確認はまだありません"
        shock["summary"] = (
            "価格の規模と速度から複数の主要報道・アナリストが介入を疑っています。"
            "ただし財務省・日銀の公式確認はなく、月末フロー、米金利材料、広範なドル安も候補です。"
        )
    if (
        shock.get("severity") in {"critical", "warning"}
        and not recent_directional_shock
        and event_end is not None
    ):
        event_time = event_end.astimezone(JST).strftime("%m月%d日 %H:%M")
        direction_label = {
            "yen-strengthening": "円高方向",
            "yen-weakening": "円安方向",
            "mixed": "方向混在",
        }.get(str(shock.get("shockDirection")), "方向未確認")
        shock["headline"] = (
            f"USD/JPYは当日{direction_label}の急変を記録。直近3時間の新規急変は未検知"
        )
        shock["summary"] = (
            f"最も大きい確認済みの動きは{event_time}（JST）までの当日履歴です。"
            "現在値の観測時刻とは分けて表示します。値動きだけでは介入を確定できず、"
            "財務省の公表と主要報道を継続確認します。"
        )
        if shock.get("shockDirection") == "yen-strengthening":
            shock["interventionLabel"] = "当日の円高急変・介入は公式未確認"
    shock["reportedEvidence"] = evidence[:6]
    shock["reportedEvidenceCount"] = len(evidence)
    shock["officiallyConfirmed"] = False
    july_event_start = datetime(2026, 7, 30, 13, 0, tzinfo=timezone.utc)
    july_event_end = datetime(2026, 7, 30, 15, 30, tzinfo=timezone.utc)
    is_july_event = (
        eligible_directional_shock
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
    display_quote_keys = tuple(key for key in PREMARKET_DISPLAY_KEYS if key in INTRADAY_INSTRUMENTS)
    active = sum(1 for quote in quotes.values() if quote.get("marketState") == "updating")
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
        "displayQuoteKeys": list(display_quote_keys),
        "marketSummaryOverlayKeys": list(MARKET_SUMMARY_OVERLAY_KEYS),
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


def retrieval_count_fields(
    received_count: int,
    accepted: list[dict[str, Any]],
) -> dict[str, Any]:
    effective_times = [
        item.get("effectivePublishedAtUtc")
        for item in accepted
        if item.get("effectivePublishedAtUtc")
    ]
    return {
        "receivedCount": max(0, int(received_count)),
        "acceptedCount": len(accepted),
        "newestEffectiveAtUtc": max(effective_times) if effective_times else None,
    }


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
                "published": dates[-1] + "T00:00:00Z" if dates else "",
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
            timestamp_basis="publisher-feed" if feed.get("format") != "html-links" else "publisher-page-date",
            timestamp_precision_value="date" if feed.get("format") == "html-links" else None,
            discovery_provider="official-direct",
        )
        if item["ageHours"] is None or item["ageHours"] <= 336:
            output.append(item)
    accepted = output[:10]
    return accepted, {
        "name": feed["name"],
        "kind": feed["kind"],
        "status": "ok" if accepted else "limited",
        "url": feed["url"],
        "retrievedAtUtc": now.isoformat(),
        "message": (
            f"市場関連 {len(accepted)}件"
            if accepted
            else "接続成功・該当新着0件"
        ),
        **retrieval_count_fields(len(feed_rows), accepted),
    }


def _fetch_legacy_company_disclosures(
    feed: dict[str, Any],
    now: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read a company's TDnet-backed disclosure page with exact release times."""

    raw, resolved_url = request(feed["url"])
    page = raw.decode("utf-8", errors="replace")
    blocks = re.findall(r"<article\b[^>]*>.*?</article>", page, flags=re.I | re.S)
    if not blocks:
        # Keep a narrow fallback for server-rendered variants that omit article.
        blocks = re.findall(r"<li\b[^>]*>.*?</li>", page, flags=re.I | re.S)

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    event_terms = tuple(str(term) for term in feed.get("eventTerms") or ())
    for block in blocks:
        title_match = re.search(r"<h3\b[^>]*>(.*?)</h3>", block, flags=re.I | re.S)
        time_match = re.search(
            r"<time\b[^>]*\bdatetime=[\"']([^\"']+)[\"'][^>]*>",
            block,
            flags=re.I | re.S,
        )
        link_matches = re.findall(
            r"<a\b[^>]*\bhref=[\"']([^\"']+)[\"'][^>]*>",
            block,
            flags=re.I | re.S,
        )
        if not title_match or not time_match or not link_matches:
            continue
        title = clean_text(title_match.group(1))
        published = clean_text(time_match.group(1))
        link = next(
            (
                candidate
                for candidate in link_matches
                if ".pdf" in urllib.parse.urlparse(
                    html.unescape(candidate)
                ).path.casefold()
            ),
            "",
        )
        if not title or not link:
            continue
        if event_terms and not any(contains_term(title, term) for term in event_terms):
            continue
        direct_url = normalize_url(
            urllib.parse.urljoin(resolved_url, html.unescape(link))
        )
        if not direct_url.startswith("https://"):
            continue
        dedupe_key = (direct_url, published)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rows.append({
            "title": title,
            "link": direct_url,
            "published": published,
        })

    output: list[dict[str, Any]] = []
    for row in rows:
        published_dt = parse_datetime(row["published"])
        if published_dt is None:
            continue
        age = now - published_dt.astimezone(timezone.utc)
        if age < timedelta(minutes=-2) or age > timedelta(days=14):
            continue
        output.append(build_item(
            title=row["title"],
            url=row["link"],
            source=feed["name"],
            source_kind=feed["kind"],
            published=row["published"],
            retrieved_at=now,
            summary="",
            topic_hint=feed.get("topic"),
            verification="primary",
            identity_note=(
                "TDnet掲載時刻を持つ企業開示ページから検知。"
                f"企業IR一覧: {feed.get('companyUrl') or ''}"
            ),
            timestamp_basis="tdnet-disclosure-time",
            timestamp_precision_value="minute",
            discovery_provider="tdnet-direct",
            source_country=feed.get("sourceCountry") or "JP",
        ))
    accepted = sorted(
        output,
        key=lambda item: item.get("effectivePublishedAtUtc") or "",
        reverse=True,
    )[:12]
    return accepted, {
        "name": feed["name"],
        "kind": feed.get("statusKind") or feed["kind"],
        "status": "ok" if accepted else "limited",
        "url": feed["url"],
        "retrievedAtUtc": now.isoformat(),
        "message": (
            f"TDnet時刻付き開示 {len(accepted)}件"
            if accepted
            else "接続成功・直近14日の重要開示0件"
        ),
        **retrieval_count_fields(len(rows), accepted),
    }


DISCLOSURE_CATEGORY_RULES: tuple[tuple[str, int, str], ...] = (
    (
        "delisting-supervision",
        100,
        r"監理銘柄|整理銘柄|上場廃止|上場維持基準.*(?:不適合|抵触)",
    ),
    (
        "m-and-a-tob",
        99,
        r"公開買付|\bTOB\b|\bMBO\b|経営統合|株式交換|株式移転|合併契約",
    ),
    (
        "accounting-governance",
        98,
        r"第三者委員会|特別調査委員会|不適切会計|不正会計|監査意見|"
        r"内部統制.*重要な不備|有価証券報告書.*提出期限",
    ),
    (
        "guidance-revision",
        96,
        r"業績予想.*(?:修正|公表|取下げ|未定)|(?:上方|下方)修正|"
        r"(?:通期|中間期|第[１２３４1-4]四半期).*業績.*(?:見通し|予想).*修正|"
        r"guidance|business outlook",
    ),
    (
        "financial-results",
        93,
        r"決算短信|決算発表|決算速報|(?:第[１２３４1-4]四半期|通期|中間期)決算(?!説明)|"
        r"\b(?:earnings|financial results?|quarterly results?)\b",
    ),
    (
        "material-loss-gain",
        92,
        r"特別損失|特別利益|減損損失|債務超過|継続企業の前提|"
        r"訴訟.*(?:判決|評決)|巨額損失",
    ),
    (
        "buyback",
        89,
        r"自己株式(?:の)?(?:取得|買付)|自社株買い|"
        r"\b(?:share repurchase|buyback|acquisition of own shares)\b",
    ),
    (
        "disaster-operational",
        88,
        r"(?:地震|災害|台風|豪雨|火災).*影響|操業停止|生産停止|"
        r"サイバー攻撃|ランサムウェア",
    ),
    (
        "capital-raising",
        87,
        r"第三者割当増資|公募増資|新株予約権.*発行|転換社債.*発行|"
        r"資本増強|資金調達",
    ),
    (
        "stock-split",
        86,
        r"株式分割|株式併合|\bstock split\b",
    ),
    (
        "dividend",
        81,
        r"配当予想.*(?:修正|増配|減配|無配|取下げ)|剰余金の配当|"
        r"記念配当|復配|\bdividend\b",
    ),
)

DISCLOSURE_CATEGORY_LABELS = {
    "financial-results": "決算",
    "guidance-revision": "業績予想・修正",
    "dividend": "配当",
    "buyback": "自己株式取得",
    "stock-split": "株式分割・併合",
    "m-and-a-tob": "M&A・公開買付け",
    "capital-raising": "資本調達",
    "accounting-governance": "会計・ガバナンス",
    "material-loss-gain": "重要損益・訴訟",
    "delisting-supervision": "上場維持・監理",
    "disaster-operational": "災害・操業影響",
}


def company_disclosure_category(value: str) -> tuple[str, int]:
    """Classify a material company event without relying on an issuer name."""

    text = unicodedata.normalize("NFKC", clean_text(value))
    # A compensation notice containing 業績連動 is not an earnings release.
    if re.search(r"業績連動型?(?:株式)?報酬", text) and not re.search(
        r"決算短信|決算発表|業績予想.*(?:修正|公表|取下げ)",
        text,
    ):
        return "", 0
    # Presentation-only material follows an already captured result and must
    # not consume the guaranteed financial-results slot on its own.
    if re.search(r"決算(?:説明会?|補足)(?:資料|動画)|決算Q[＆&]A", text):
        return "", 0
    for category, score, pattern in DISCLOSURE_CATEGORY_RULES:
        if re.search(pattern, text, re.I):
            return category, score
    return "", 0


def _tdnet_security_code(raw_code: str) -> str:
    code = unicodedata.normalize("NFKC", clean_text(raw_code)).upper()
    if re.fullmatch(r"[0-9A-Z]{5}", code) and code.endswith("0"):
        return code[:-1]
    return code


def _tdnet_cell(block: str, class_name: str) -> str:
    match = re.search(
        rf"<td\b[^>]*\bclass=[\"'][^\"']*\b{re.escape(class_name)}\b[^\"']*[\"'][^>]*>"
        r"(.*?)</td>",
        block,
        flags=re.I | re.S,
    )
    return match.group(1) if match else ""


def _parse_tdnet_page(
    page: str,
    resolved_url: str,
    disclosure_date: str,
) -> tuple[list[dict[str, Any]], int, int]:
    rows: list[dict[str, Any]] = []
    for block in re.findall(r"<tr\b[^>]*>.*?</tr>", page, flags=re.I | re.S):
        time_text = clean_text(_tdnet_cell(block, "kjTime"))
        tdnet_code = clean_text(_tdnet_cell(block, "kjCode"))
        company_name = clean_text(_tdnet_cell(block, "kjName"))
        title_cell = _tdnet_cell(block, "kjTitle")
        link_match = re.search(
            r"<a\b[^>]*\bhref=[\"']([^\"']+\.pdf(?:\?[^\"']*)?)[\"'][^>]*>(.*?)</a>",
            title_cell,
            flags=re.I | re.S,
        )
        if (
            not re.fullmatch(r"\d{2}:\d{2}", time_text)
            or not tdnet_code
            or not company_name
            or not link_match
        ):
            continue
        title = clean_text(link_match.group(2))
        pdf_url = normalize_url(
            urllib.parse.urljoin(resolved_url, html.unescape(link_match.group(1)))
        )
        disclosure_id = Path(urllib.parse.urlparse(pdf_url).path).stem
        if not title or not disclosure_id or not pdf_url.startswith("https://"):
            continue
        xbrl_cell = _tdnet_cell(block, "kjXbrl")
        xbrl_match = re.search(
            r"<a\b[^>]*\bhref=[\"']([^\"']+\.zip(?:\?[^\"']*)?)[\"']",
            xbrl_cell,
            flags=re.I | re.S,
        )
        published = f"{disclosure_date}T{time_text}:00+09:00"
        rows.append({
            "disclosureId": disclosure_id,
            "tdnetCode": tdnet_code,
            "issuerCode": _tdnet_security_code(tdnet_code),
            "issuerName": company_name,
            "title": title,
            "published": published,
            "pdfUrl": pdf_url,
            "xbrlUrl": (
                normalize_url(
                    urllib.parse.urljoin(
                        resolved_url,
                        html.unescape(xbrl_match.group(1)),
                    )
                )
                if xbrl_match
                else ""
            ),
            "exchange": clean_text(_tdnet_cell(block, "kjPlace")),
        })
    total_match = re.search(r"全\s*([\d,]+)件", page)
    total_count = int(total_match.group(1).replace(",", "")) if total_match else len(rows)
    page_numbers = [
        int(value)
        for value in re.findall(
            rf"I_list_(\d{{3}})_{re.escape(disclosure_date.replace('-', ''))}\.html",
            page,
            flags=re.I,
        )
    ]
    return rows, total_count, max(page_numbers or [1])


def _tdnet_required_page_count(
    page: str,
    rows: list[dict[str, Any]],
    total_count: int,
    listed_pages: int,
) -> int:
    """Calculate every required page even when the pager hides later links."""

    display_text = unicodedata.normalize("NFKC", clean_text(page))
    range_match = re.search(
        r"([\d,]+)\s*[~〜～\-–—]\s*([\d,]+)\s*件\s*/?\s*全\s*[\d,]+\s*件",
        display_text,
    )
    page_capacity = len(rows)
    if range_match:
        first = int(range_match.group(1).replace(",", ""))
        last = int(range_match.group(2).replace(",", ""))
        if last >= first:
            page_capacity = max(page_capacity, last - first + 1)
    if total_count <= 0:
        return max(1, listed_pages)
    return max(
        1,
        listed_pages,
        math.ceil(total_count / max(1, page_capacity)),
    )


def _tdnet_main_state(
    page: str,
    resolved_url: str,
) -> tuple[str, str, str]:
    list_match = re.search(
        r"value=[\"'](I_list_001_(\d{8})\.html)[\"']",
        page,
        flags=re.I,
    )
    if not list_match:
        raise RuntimeError("TDnet public viewer did not expose a current list page")
    yyyymmdd = list_match.group(2)
    disclosure_date = (
        f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
    )
    update_match = re.search(
        r"最終更新日時\s*[:：]\s*(\d{4})年(\d{2})月(\d{2})日\s*(\d{2}):(\d{2})",
        page,
    )
    last_update = ""
    if update_match:
        last_update = (
            f"{update_match.group(1)}-{update_match.group(2)}-{update_match.group(3)}"
            f"T{update_match.group(4)}:{update_match.group(5)}:00+09:00"
        )
    return (
        normalize_url(urllib.parse.urljoin(resolved_url, list_match.group(1))),
        disclosure_date,
        last_update,
    )


def fetch_company_disclosures(
    feed: dict[str, Any],
    now: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Incrementally scan the official TDnet list for every listed company."""

    main_raw, main_url = request(feed["url"])
    list_url, disclosure_date, last_update_jst = _tdnet_main_state(
        main_raw.decode("utf-8", errors="replace"),
        main_url,
    )
    first_raw, first_url = request(list_url)
    first_page = first_raw.decode("utf-8", errors="replace")
    first_rows, total_count, listed_pages = _parse_tdnet_page(
        first_page,
        first_url,
        disclosure_date,
    )
    previous_state = feed.get("previousState") or {}
    previous_id = str(previous_state.get("newestDisclosureId") or "")
    page_limit = max(1, int(feed.get("maxPages") or 20))
    required_pages = _tdnet_required_page_count(
        first_page, first_rows, total_count, listed_pages
    )
    max_pages = min(page_limit, required_pages)
    pagination_truncated = required_pages > max_pages
    backfill_failed_dates = 0
    rows = list(first_rows)
    scanned_pages = 1
    scanned_dates = 1
    total_available_count = total_count
    found_watermark = bool(
        previous_id
        and any(row["disclosureId"] == previous_id for row in first_rows)
    )
    scan_mode = "head-only" if found_watermark else "incremental" if previous_id else "full"
    if not found_watermark:
        for page_number in range(2, max_pages + 1):
            page_url = re.sub(
                r"I_list_001_",
                f"I_list_{page_number:03d}_",
                list_url,
            )
            raw, resolved = request(page_url)
            page_rows, _, _ = _parse_tdnet_page(
                raw.decode("utf-8", errors="replace"),
                resolved,
                disclosure_date,
            )
            rows.extend(page_rows)
            scanned_pages += 1
            if previous_id and any(
                row["disclosureId"] == previous_id for row in page_rows
            ):
                found_watermark = True
                break

    # A missing snapshot or a watermark not present on today's pages must not
    # make intervening dates disappear.  Scan each calendar date intersecting
    # the exact trailing 48h; the age filter below enforces the rolling edge.
    if not previous_id or not found_watermark:
        current_date = datetime.strptime(disclosure_date, "%Y-%m-%d").date()
        earliest_date = (now - timedelta(hours=48)).astimezone(JST).date()
        historical_date = current_date - timedelta(days=1)
        while historical_date >= earliest_date:
            yyyymmdd = historical_date.strftime("%Y%m%d")
            historical_list_url = re.sub(
                r"I_list_001_\d{8}\.html",
                f"I_list_001_{yyyymmdd}.html",
                list_url,
            )
            try:
                raw, resolved = request(historical_list_url)
            except (OSError, RuntimeError):
                backfill_failed_dates += 1
                historical_date -= timedelta(days=1)
                continue
            historical_page = raw.decode("utf-8", errors="replace")
            historical_rows, historical_total, historical_listed = (
                _parse_tdnet_page(
                    historical_page,
                    resolved,
                    historical_date.isoformat(),
                )
            )
            historical_required = _tdnet_required_page_count(
                historical_page,
                historical_rows,
                historical_total,
                historical_listed,
            )
            historical_max = min(page_limit, historical_required)
            pagination_truncated = (
                pagination_truncated
                or historical_required > historical_max
            )
            rows.extend(historical_rows)
            scanned_pages += 1
            scanned_dates += 1
            total_available_count += historical_total
            if previous_id and any(
                row["disclosureId"] == previous_id
                for row in historical_rows
            ):
                found_watermark = True
            for page_number in range(2, historical_max + 1):
                if found_watermark:
                    break
                page_url = re.sub(
                    r"I_list_001_",
                    f"I_list_{page_number:03d}_",
                    historical_list_url,
                )
                raw, resolved = request(page_url)
                page_rows, _, _ = _parse_tdnet_page(
                    raw.decode("utf-8", errors="replace"),
                    resolved,
                    historical_date.isoformat(),
                )
                rows.extend(page_rows)
                scanned_pages += 1
                if previous_id and any(
                    row["disclosureId"] == previous_id
                    for row in page_rows
                ):
                    found_watermark = True
                    break
            if found_watermark:
                break
            historical_date -= timedelta(days=1)

    # Deduplicate page-boundary movement.  A later run will close any race if
    # new disclosures arrived while multiple pages were being traversed.
    unique_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in rows:
        disclosure_id = str(row["disclosureId"])
        if disclosure_id in seen_ids:
            continue
        seen_ids.add(disclosure_id)
        unique_rows.append(row)
    rows = unique_rows

    bundle_counts: dict[tuple[str, str], int] = {}
    for row in rows:
        bundle_key = (str(row["issuerCode"]), str(row["published"]))
        bundle_counts[bundle_key] = bundle_counts.get(bundle_key, 0) + 1

    output: list[dict[str, Any]] = []
    for row in rows:
        category, base_materiality = company_disclosure_category(row["title"])
        if not category:
            continue
        published_dt = parse_datetime(row["published"])
        if published_dt is None:
            continue
        age = now - published_dt.astimezone(timezone.utc)
        if age < timedelta(minutes=-2) or age > timedelta(hours=48):
            continue
        bundle_size = bundle_counts.get(
            (str(row["issuerCode"]), str(row["published"])),
            1,
        )
        materiality = min(100, base_materiality + min(9, (bundle_size - 1) * 3))
        category_label = DISCLOSURE_CATEGORY_LABELS.get(category, category)
        display_title = (
            f"{row['issuerName']}（{row['issuerCode']}）｜{row['title']}"
        )
        item = build_item(
            title=display_title,
            url=row["pdfUrl"],
            source=f"TDnet / {row['issuerName']}",
            source_kind=feed["kind"],
            published=row["published"],
            retrieved_at=now,
            summary=(
                f"{row['issuerName']}（{row['issuerCode']}）がTDnetで"
                f"「{category_label}」を開示。公式PDFへ直接移動できます。"
            ),
            topic_hint=feed.get("topic"),
            verification="primary",
            identity_note=(
                "JPX/TDnetの全上場会社一覧から企業名を指定せず検知。"
                f"開示種別={category_label}、TDnetコード={row['tdnetCode']}、"
                f"同時刻の同社開示={bundle_size}件。"
            ),
            timestamp_basis="tdnet-official-disclosure-time",
            timestamp_precision_value="minute",
            discovery_provider="tdnet-public-viewer",
            source_country=feed.get("sourceCountry") or "JP",
        )
        item.update({
            "disclosureId": row["disclosureId"],
            "issuerCode": row["issuerCode"],
            "issuerName": row["issuerName"],
            "disclosureCategory": category,
            "materialityScore": materiality,
        })
        output.append(item)
    accepted = sorted(
        output,
        key=lambda item: (
            int(item.get("materialityScore") or 0),
            item.get("effectivePublishedAtUtc") or "",
        ),
        reverse=True,
    )
    newest_id = str(first_rows[0]["disclosureId"]) if first_rows else ""
    incomplete = bool(
        pagination_truncated
        or backfill_failed_dates
        or (previous_id and not found_watermark)
    )
    status = "limited" if incomplete or not accepted else "ok"
    message = (
        (
            f"全上場会社TDnetを{scanned_dates}日・"
            f"{scanned_pages}ページ走査し、"
            f"重要開示{len(accepted)}件を抽出"
            + ("（走査上限・取得失敗または前回位置に未到達）" if incomplete else "")
        )
        if accepted
        else "接続成功・該当新着0件"
    )
    return accepted, {
        "name": feed["name"],
        "kind": feed.get("statusKind") or feed["kind"],
        "status": status,
        "url": feed["url"],
        "retrievedAtUtc": now.isoformat(),
        "message": message,
        **retrieval_count_fields(len(rows), accepted),
        "newestDisclosureId": newest_id,
        "lastViewerUpdateJst": last_update_jst,
        "scannedPages": scanned_pages,
        "scannedDates": scanned_dates,
        "coverageVersion": TDNET_SCAN_COVERAGE_VERSION,
        "coverageComplete": not incomplete,
        "backfillFailedDates": backfill_failed_dates,
        "totalAvailableCount": total_available_count,
        "scanMode": scan_mode,
    }


COMPANY_DISCLOSURE_CACHE_HOURS = 48
COMPANY_DISCLOSURE_CACHE_LIMIT = 2000
TDNET_SCAN_COVERAGE_VERSION = 2


def build_company_disclosure_cache(
    items: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    """Persist compact TDnet candidates, including those outside the final six."""

    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        if item.get("sourceKind") != "official-company":
            continue
        disclosure_id = str(item.get("disclosureId") or "")
        published = item_effective_datetime(item)
        if not disclosure_id or published is None:
            continue
        age = now - published
        if age < timedelta(minutes=-2) or age > timedelta(
            hours=COMPANY_DISCLOSURE_CACHE_HOURS
        ):
            continue
        url = normalize_url(str(item.get("url") or ""))
        if publisher_domain(url) != "www.release.tdnet.info":
            continue
        by_id[disclosure_id] = {
            "disclosureId": disclosure_id,
            "issuerCode": str(item.get("issuerCode") or ""),
            "issuerName": clean_text(item.get("issuerName")),
            "disclosureCategory": str(
                item.get("disclosureCategory") or ""
            ),
            "materialityScore": int(item.get("materialityScore") or 0),
            "title": clean_text(item.get("title")),
            "url": url,
            "publishedAtUtc": published.astimezone(timezone.utc).isoformat(),
        }
    return sorted(
        by_id.values(),
        key=lambda row: str(row["publishedAtUtc"]),
        reverse=True,
    )[:COMPANY_DISCLOSURE_CACHE_LIMIT]


def restore_company_disclosure_cache(
    rows: Any,
    now: datetime,
    existing_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Rehydrate recent official candidates for cross-run buzz re-evaluation."""

    existing_ids = set(existing_ids or set())
    restored: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        disclosure_id = str(row.get("disclosureId") or "")
        if not disclosure_id or disclosure_id in existing_ids:
            continue
        published = parse_datetime(row.get("publishedAtUtc"))
        if published is None:
            continue
        age = now - published.astimezone(timezone.utc)
        if age < timedelta(minutes=-2) or age > timedelta(
            hours=COMPANY_DISCLOSURE_CACHE_HOURS
        ):
            continue
        url = normalize_url(str(row.get("url") or ""))
        if publisher_domain(url) != "www.release.tdnet.info":
            continue
        category = str(row.get("disclosureCategory") or "")
        if category not in DISCLOSURE_CATEGORY_LABELS:
            continue
        issuer_code = str(row.get("issuerCode") or "")
        issuer_name = clean_text(row.get("issuerName"))
        title = clean_text(row.get("title"))
        if not issuer_code or not issuer_name or not title:
            continue
        category_label = DISCLOSURE_CATEGORY_LABELS[category]
        item = build_item(
            title=title,
            url=url,
            source=f"TDnet / {issuer_name}",
            source_kind="official-company",
            published=published.astimezone(timezone.utc).isoformat(),
            retrieved_at=now,
            summary=(
                f"{issuer_name}（{issuer_code}）がTDnetで"
                f"「{category_label}」を開示。公式PDFへ直接移動できます。"
            ),
            topic_hint="japan-stocks",
            verification="primary",
            identity_note=(
                "JPX/TDnet全社走査で取得した直近48時間の公式開示を再評価。"
                "前回の最終表示枠に入らなかった開示も対象です。"
            ),
            timestamp_basis="tdnet-official-disclosure-time",
            timestamp_precision_value="minute",
            discovery_provider="tdnet-recent-cache",
            source_country="JP",
        )
        item.update({
            "disclosureId": disclosure_id,
            "issuerCode": issuer_code,
            "issuerName": issuer_name,
            "disclosureCategory": category,
            "materialityScore": max(
                0, min(100, int(row.get("materialityScore") or 0))
            ),
        })
        restored.append(item)
        existing_ids.add(disclosure_id)
    return restored


def build_dynamic_company_news_queries(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Seed provider searches from current high-impact disclosures, not a watchlist."""

    annotate_company_news_signals(items)
    by_issuer: dict[str, dict[str, Any]] = {}
    for item in items:
        code = str(item.get("issuerCode") or "")
        name = clean_text(item.get("issuerName"))
        if not code or not name:
            continue
        row = by_issuer.setdefault(code, {
            "code": code,
            "name": name,
            "score": 0,
            "categories": set(),
            "newsMentions": 0,
            "independentNewsSources": 0,
            "buzzScore": 0,
            "latest": None,
        })
        row["score"] = max(
            int(row["score"]),
            int(item.get("materialityScore") or 0),
        )
        row["categories"].add(str(item.get("disclosureCategory") or ""))
        row["newsMentions"] = max(
            int(row["newsMentions"]),
            int(item.get("issuerNewsMentionCount") or 0),
        )
        row["independentNewsSources"] = max(
            int(row["independentNewsSources"]),
            int(item.get("issuerIndependentNewsSourceCount") or 0),
        )
        row["buzzScore"] = max(
            int(row["buzzScore"]),
            int(item.get("issuerBuzzScore") or 0),
        )
        effective = item_effective_datetime(item)
        if effective is not None and (
            row["latest"] is None or effective > row["latest"]
        ):
            row["latest"] = effective
    ranked = sorted(
        by_issuer.values(),
        key=lambda row: (
            int(row["score"])
            + min(12, (len(row["categories"]) - 1) * 4)
            + int(row["buzzScore"]),
            int(row["independentNewsSources"]),
            int(row["newsMentions"]),
            row["latest"] or datetime.min.replace(tzinfo=timezone.utc),
            str(row["code"]),
        ),
        reverse=True,
    )[:6]
    definitions: list[dict[str, Any]] = []
    for index in range(0, len(ranked), 3):
        chunk = ranked[index:index + 3]
        issuer_terms = [
            term
            for row in chunk
            for term in (
                str(row["name"]),
                str(row["code"]) if re.search(r"[A-Za-z]", str(row["code"])) else "",
            )
            if term
        ]
        quoted = " OR ".join(
            f'"{term}"' if re.search(r"\s", term) else term
            for term in issuer_terms
        )
        definitions.append({
            "key": "japan-stocks",
            "name": "TDnet重要開示・媒体反応 " + " / ".join(
                str(row["code"]) for row in chunk
            ),
            "query": (
                f"({quoted}) "
                "(決算 OR 業績 OR 自社株買い OR 株式分割 OR TOB OR 急騰 OR 急落)"
            ),
            "googleLocale": {"hl": "ja", "gl": "JP", "ceid": "JP:ja"},
            "bingLanguage": "ja-JP",
            "requiredAnyTerms": tuple(issuer_terms),
            "maxAgeHours": 36,
            "acceptedLimit": 12,
            "discoveryProvider": "issuer-dynamic",
        })
    return definitions


def news_query_label(query_def: dict[str, Any]) -> str:
    return str(
        query_def.get("name")
        or TOPICS.get(
            str(query_def.get("key") or ""),
            {"label": query_def.get("key") or "markets"},
        )["label"]
    )


def news_query_row_allowed(
    row: dict[str, str],
    query_def: dict[str, Any],
) -> bool:
    required = tuple(
        str(term)
        for term in query_def.get("requiredAnyTerms") or ()
        if str(term).strip()
    )
    if not required:
        return True
    text = clean_text(f"{row.get('title') or ''} {row.get('summary') or ''}")
    return any(contains_term(text, term) for term in required)


def fetch_bing_news(query_def: dict[str, Any], now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = urllib.parse.urlencode({
        "q": query_def["query"],
        "format": "rss",
        "setlang": str(query_def.get("bingLanguage") or "en-US"),
    })
    url = "https://www.bing.com/news/search?" + params
    raw, _ = request(url)
    output: list[dict[str, Any]] = []
    feed_rows = parse_feed_items(raw)[:12]
    for row in feed_rows:
        if (
            not row["title"]
            or not row["link"]
            or not news_query_row_allowed(row, query_def)
        ):
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
            indexed_at=row["published"],
            timestamp_basis="discovery-feed",
            discovery_provider=str(
                query_def.get("discoveryProvider") or "bing-news"
            ),
        )
        max_age_hours = float(query_def.get("maxAgeHours") or 168)
        if item["ageHours"] is None or item["ageHours"] <= max_age_hours:
            output.append(item)
    accepted = output[:int(query_def.get("acceptedLimit") or 8)]
    return accepted, {
        "name": f"Bing News / {news_query_label(query_def)}",
        "kind": "news-discovery",
        "status": "ok" if accepted else "limited",
        "url": url,
        "retrievedAtUtc": now.isoformat(),
        "message": (
            f"{len(accepted)}件" if accepted else "接続成功・該当新着0件"
        ),
        **retrieval_count_fields(len(feed_rows), accepted),
    }


def fetch_google_news(query_def: dict[str, Any], now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Use a second public news index so one empty provider does not hide a story."""

    locale = query_def.get("googleLocale") or {}
    params = urllib.parse.urlencode({
        "q": query_def["query"],
        "hl": str(locale.get("hl") or "en-US"),
        "gl": str(locale.get("gl") or "US"),
        "ceid": str(locale.get("ceid") or "US:en"),
    })
    url = "https://news.google.com/rss/search?" + params
    raw, _ = request(url)
    output: list[dict[str, Any]] = []
    feed_rows = parse_feed_items(raw)[:16]
    for row in feed_rows:
        if (
            not row["title"]
            or not row["link"]
            or not news_query_row_allowed(row, query_def)
        ):
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
            indexed_at=row["published"],
            timestamp_basis="discovery-feed",
            discovery_provider=str(
                query_def.get("discoveryProvider") or "google-news"
            ),
        )
        max_age_hours = float(query_def.get("maxAgeHours") or 168)
        if item["ageHours"] is None or item["ageHours"] <= max_age_hours:
            output.append(item)
    accepted = output[:int(query_def.get("acceptedLimit") or 8)]
    return accepted, {
        "name": f"Google News / {news_query_label(query_def)}",
        "kind": "news-discovery",
        "status": "ok" if accepted else "limited",
        "url": url,
        "retrievedAtUtc": now.isoformat(),
        "message": (
            f"{len(accepted)}件" if accepted else "接続成功・該当新着0件"
        ),
        **retrieval_count_fields(len(feed_rows), accepted),
    }


def fetch_gdelt_news(
    query_def: dict[str, str],
    now: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch the newest global article metadata from the keyless GDELT DOC API."""

    params = urllib.parse.urlencode({
        "query": query_def["query"],
        "mode": "ArtList",
        "format": "json",
        "sort": "DateDesc",
        "timespan": "2h",
        "maxrecords": "75",
    })
    url = GDELT_DOC_URL + "?" + params
    raw, _ = request(url)
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    rows = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("GDELT response did not contain an articles array")
    output: list[dict[str, Any]] = []
    for row in rows[:75]:
        if not isinstance(row, dict):
            continue
        title = clean_text(row.get("title"))
        direct_url = normalize_url(str(row.get("url") or ""))
        indexed = row.get("seendate")
        if not title or not direct_url.startswith("https://"):
            continue
        domain = clean_text(row.get("domain")) or publisher_domain(direct_url)
        lowered_domain = domain.casefold()
        kind = (
            "news-wire"
            if any(
                needle in lowered_domain
                for needle in ("reuters.", "apnews.", "bloomberg.")
            )
            else "news"
        )
        hint = query_def["key"] if query_def["key"] in TOPICS else None
        item = build_item(
            title=title,
            url=direct_url,
            source=domain or "GDELT discovery",
            source_kind=kind,
            published=None,
            indexed_at=indexed,
            retrieved_at=now,
            summary="",
            topic_hint=hint,
            verification="reported",
            identity_note=(
                "GDELT DOC 2.0の公開索引で検知。時刻は索引時刻として扱い、"
                "詳細と発表時刻はリンク先で確認します。"
            ),
            timestamp_basis="index-seen",
            timestamp_precision_value="minute",
            discovery_provider="gdelt-doc",
            source_country=clean_text(row.get("sourcecountry")),
        )
        if item["ageHours"] is None or item["ageHours"] <= 6:
            output.append(item)
    output = sorted(
        output,
        key=lambda item: item.get("effectivePublishedAtUtc") or "",
        reverse=True,
    )[:40]
    return output, {
        "name": f"GDELT / {query_def['key']}",
        "kind": "news-discovery",
        "status": "ok" if output else "limited",
        "url": url,
        "retrievedAtUtc": now.isoformat(),
        "message": (
            f"直近2時間 {len(output)}件"
            if output
            else "接続成功・該当新着0件"
        ),
        **retrieval_count_fields(len(rows[:75]), output),
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


def item_effective_datetime(item: dict[str, Any]) -> datetime | None:
    return (
        parse_datetime(item.get("effectivePublishedAtUtc"))
        or parse_datetime(item.get("publishedAtUtc"))
        or parse_datetime(item.get("indexedAtUtc"))
    )


def inherit_previous_item_state(
    items: list[dict[str, Any]],
    previous: dict[str, Any],
    now: datetime,
) -> None:
    previous_items = ((previous.get("briefing") or {}).get("items") or [])
    by_id: dict[str, dict[str, Any]] = {}
    by_url: dict[str, dict[str, Any]] = {}
    by_hash: dict[str, dict[str, Any]] = {}
    for previous_item in previous_items:
        if not isinstance(previous_item, dict):
            continue
        if previous_item.get("id"):
            by_id[str(previous_item["id"])] = previous_item
        normalized_url = normalize_url(str(previous_item.get("url") or ""))
        if normalized_url:
            by_url[normalized_url] = previous_item
        source_hash = ((previous_item.get("japanese") or {}).get("sourceHash"))
        if source_hash:
            by_hash[str(source_hash)] = previous_item

    for item in items:
        source_hash = ((item.get("japanese") or {}).get("sourceHash"))
        match = (
            by_id.get(str(item.get("id") or ""))
            or by_url.get(normalize_url(str(item.get("url") or "")))
            or by_hash.get(str(source_hash or ""))
        )
        if match:
            inherited_first_seen = (
                match.get("firstSeenAtUtc")
                or ((match.get("freshness") or {}).get("firstSeenAtUtc"))
            )
            inherited_first_seen_dt = parse_datetime(inherited_first_seen)
            effective_dt = item_effective_datetime(item)
            if inherited_first_seen_dt:
                # A source can later correct its published timestamp.  Keep the
                # original discovery time only when it is consistent with that
                # corrected timestamp; otherwise show the confirmed publication
                # time rather than claiming discovery before publication.
                if effective_dt and inherited_first_seen_dt < effective_dt - timedelta(minutes=10):
                    inherited_first_seen_dt = effective_dt
                item["firstSeenAtUtc"] = inherited_first_seen_dt.astimezone(timezone.utc).isoformat()
            if match.get("clusterId"):
                item["clusterId"] = match["clusterId"]
            previous_japanese = match.get("japanese") or {}
            current_japanese = item.get("japanese") or {}
            if (
                previous_japanese.get("mode") == "deepl"
                and previous_japanese.get("sourceHash")
                and previous_japanese.get("sourceHash")
                == current_japanese.get("sourceHash")
            ):
                # A translation is immutable for the same source hash, so reuse
                # the published result instead of spending another API call.
                item["japanese"] = dict(previous_japanese)
        effective = item_effective_datetime(item)
        profile = freshness_profile(
            effective,
            now,
            str(item.get("timestampPrecision") or "unknown"),
        )
        profile["firstSeenAtUtc"] = item.get("firstSeenAtUtc") or now.isoformat()
        item["freshness"] = profile


def _title_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize(
        "NFKC",
        source_suffix_removed(clean_text(value)).casefold(),
    )
    return set(re.findall(r"[a-z0-9]+|[一-龥ぁ-んァ-ン]{2,}", normalized))


def _title_numbers(value: str) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?%?", value or ""))


def title_similarity(left: str, right: str) -> float:
    left_normalized = normalized_comparison_text(source_suffix_removed(left))
    right_normalized = normalized_comparison_text(source_suffix_removed(right))
    if not left_normalized or not right_normalized:
        return 0.0
    if left_normalized == right_normalized:
        return 1.0
    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    return max(jaccard, sequence)


def _issuer_aliases(item: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    code = normalized_comparison_text(str(item.get("issuerCode") or ""))
    if len(code) >= 3:
        aliases.add(code)
    name = unicodedata.normalize(
        "NFKC",
        clean_text(item.get("issuerName")),
    ).casefold()
    name = re.sub(r"^(?:g|r|a|p)[－-]", "", name)
    name = re.sub(r"(?:株式会社|\(株\)|（株）)", "", name)
    compact = normalized_comparison_text(name)
    if len(compact) >= 3:
        aliases.add(compact)
    stem = re.sub(
        r"(?:ホー?ルディングス|holdings|グルー?プ|group|hldgs|hd)$",
        "",
        compact,
        flags=re.I,
    )
    if len(stem) >= 3:
        aliases.add(stem)
    return aliases


def _issuer_is_mentioned(
    official_item: dict[str, Any],
    other_item: dict[str, Any],
) -> bool:
    raw_text = unicodedata.normalize(
        "NFKC",
        " ".join(
            str(other_item.get(key) or "")
            for key in ("title", "summary")
        ),
    ).casefold()
    other_text = normalized_comparison_text(raw_text)
    code = normalized_comparison_text(
        str(official_item.get("issuerCode") or "")
    )
    name_aliases = _issuer_aliases(official_item) - ({code} if code else set())
    if any(
        _issuer_alias_is_mentioned(alias, raw_text, other_text)
        for alias in name_aliases
    ):
        return True
    return _issuer_code_is_mentioned(code, raw_text)


def _issuer_alias_is_mentioned(
    alias: str,
    raw_text: str,
    comparison_text: str,
) -> bool:
    if not alias or alias not in comparison_text:
        return False
    company_context = bool(re.search(
        r"株|決算|業績|配当|買収|公開買付|銘柄|東証|企業|"
        r"shares?|stocks?|earnings|results?|guidance|buyback|"
        r"tender offer|tse|tyo|tokyo-listed",
        raw_text,
        re.I,
    ))
    if re.fullmatch(r"[a-z0-9]+", alias, re.I):
        # Short English issuer names frequently equal ordinary words (ACCESS,
        # NOTE, BASE).  Require an explicit code for aliases under 8 chars.
        return len(alias) >= 8
    if len(alias) >= 5:
        return True
    return company_context


def _issuer_code_is_mentioned(code: str, raw_text: str) -> bool:
    if not code:
        return False
    # Bare four-digit numbers are often years or amounts.  Count a numeric
    # security code only when the headline gives an explicit market context.
    escaped_code = re.escape(code)
    if re.search(rf"[（(\[]\s*{escaped_code}\s*[）)\]]", raw_text, re.I):
        return True
    if re.search(
        rf"(?:証券|銘柄|会社|ティッカー|code|ticker|tse|tyo|東証)"
        rf"[^0-9a-z]{{0,10}}{escaped_code}(?![0-9a-z])",
        raw_text,
        re.I,
    ):
        return True
    return bool(
        re.search(r"[a-z]", code, re.I)
        and re.search(
            rf"(?<![0-9a-z]){escaped_code}(?:\.t)?(?![0-9a-z])",
            raw_text,
            re.I,
        )
    )


def company_news_signals(
    items: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Count comparable issuer buzz from the same general discovery pool."""

    issuers: dict[str, dict[str, Any]] = {}
    for item in items:
        if item.get("sourceKind") != "official-company":
            continue
        code = str(item.get("issuerCode") or "")
        if code and item.get("issuerName"):
            issuers.setdefault(code, item)
    alias_owners: dict[str, set[str]] = {}
    issuer_aliases: dict[str, set[str]] = {}
    for code, issuer in issuers.items():
        normalized_code = normalized_comparison_text(code)
        aliases = _issuer_aliases(issuer) - (
            {normalized_code} if normalized_code else set()
        )
        issuer_aliases[code] = aliases
        for alias in aliases:
            alias_owners.setdefault(alias, set()).add(code)
    reports = [
        item for item in items
        if item.get("sourceKind") in {"news", "news-wire"}
        and item.get("discoveryProvider") != "issuer-dynamic"
    ]
    mention_keys: dict[str, set[str]] = {
        code: set() for code in issuers
    }
    origins: dict[str, set[str]] = {
        code: set() for code in issuers
    }
    for report in reports:
        raw_text = unicodedata.normalize(
            "NFKC",
            " ".join(
                str(report.get(key) or "")
                for key in ("title", "summary")
            ),
        ).casefold()
        comparison_text = normalized_comparison_text(raw_text)
        matched_codes: list[str] = []
        for code in issuers:
            normalized_code = normalized_comparison_text(code)
            name_match = any(
                len(alias_owners.get(alias, set())) == 1
                and _issuer_alias_is_mentioned(
                    alias, raw_text, comparison_text
                )
                for alias in issuer_aliases.get(code, set())
            )
            if name_match or _issuer_code_is_mentioned(
                normalized_code, raw_text
            ):
                matched_codes.append(code)
        # Market roundups listing many issuers are discovery context, not a
        # comparable measure of issuer-specific attention.
        if not matched_codes or len(matched_codes) > 2:
            continue
        story_key = normalized_comparison_text(
            source_suffix_removed(str(report.get("title") or ""))
        ) or normalize_url(str(report.get("url") or ""))
        origin = str(
            report.get("originGroup")
            or reporting_origin_group(
                str(report.get("source") or ""),
                str(report.get("url") or ""),
            )
        )
        for code in matched_codes:
            if story_key:
                mention_keys[code].add(story_key)
            if origin:
                origins[code].add(origin)
    signals: dict[str, dict[str, int]] = {}
    for code in issuers:
        story_count = len(mention_keys[code])
        origin_count = len(origins[code])
        signals[code] = {
            "mentions": story_count,
            "independentSources": origin_count,
            "buzzScore": min(
                12,
                origin_count * 3 + max(0, story_count - origin_count),
            ),
        }
    return signals


def annotate_company_news_signals(items: list[dict[str, Any]]) -> None:
    """Attach issuer-wide discussion evidence, separate from event corroboration."""

    signals = company_news_signals(items)
    for item in items:
        if item.get("sourceKind") != "official-company":
            continue
        signal = signals.get(str(item.get("issuerCode") or ""), {})
        item["issuerNewsMentionCount"] = int(signal.get("mentions") or 0)
        item["issuerIndependentNewsSourceCount"] = int(
            signal.get("independentSources") or 0
        )
        item["issuerBuzzScore"] = int(signal.get("buzzScore") or 0)


def event_signature(item: dict[str, Any]) -> str:
    """Return a conservative event key for materially different headlines."""

    issuer_code = str(item.get("issuerCode") or "")
    category = str(item.get("disclosureCategory") or "")
    if issuer_code and category:
        return f"company-{issuer_code.casefold()}-{category}"
    text = " ".join(
        str(item.get(key) or "") for key in ("title", "summary", "source")
    ).casefold()
    if item.get("topicKey") != "fx-rates":
        return ""
    if (
        re.search(r"\binterven(?:e|ed|es|ing|tion|tions)\b|介入", text, re.I)
        and re.search(r"\byen\b|japanese yen|usd/?jpy|円", text, re.I)
    ):
        return "fx-yen-intervention"
    return ""


def should_cluster_items(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_url = normalize_url(str(left.get("url") or ""))
    right_url = normalize_url(str(right.get("url") or ""))
    if left_url and left_url == right_url:
        return True
    if left.get("topicKey") != right.get("topicKey"):
        return False
    left_social = left.get("sourceKind") in {
        "x-api", "x-index", "linkedin", "bluesky",
        "truth-social", "truth-social-archive",
    }
    right_social = right.get("sourceKind") in {
        "x-api", "x-index", "linkedin", "bluesky",
        "truth-social", "truth-social-archive",
    }
    if left_social != right_social:
        return False
    left_time = item_effective_datetime(left)
    right_time = item_effective_datetime(right)
    if left_time and right_time and abs((left_time - right_time).total_seconds()) > 12 * 3600:
        return False
    left_company = (
        left.get("sourceKind") == "official-company"
        and bool(left.get("issuerCode"))
    )
    right_company = (
        right.get("sourceKind") == "official-company"
        and bool(right.get("issuerCode"))
    )
    if left_company and right_company:
        if left.get("issuerCode") != right.get("issuerCode"):
            return False
        if left.get("disclosureCategory") != right.get("disclosureCategory"):
            return False
        return bool(
            left_time
            and right_time
            and abs((left_time - right_time).total_seconds()) <= 8 * 3600
        )
    if left_company != right_company:
        official = left if left_company else right
        report = right if left_company else left
        if _issuer_is_mentioned(official, report):
            report_category, _ = company_disclosure_category(
                " ".join(
                    str(report.get(key) or "")
                    for key in ("title", "summary")
                )
            )
            official_category = str(
                official.get("disclosureCategory") or ""
            )
            if report_category and report_category != official_category:
                return False
            if report_category == official_category:
                return bool(
                    left_time
                    and right_time
                    and abs((left_time - right_time).total_seconds()) <= 12 * 3600
                )
    left_event = event_signature(left)
    right_event = event_signature(right)
    if left_event and left_event == right_event:
        if left_time is None or right_time is None:
            return False
        return abs((left_time - right_time).total_seconds()) <= 8 * 3600
    left_numbers = _title_numbers(str(left.get("title") or ""))
    right_numbers = _title_numbers(str(right.get("title") or ""))
    if left_numbers and right_numbers and left_numbers != right_numbers:
        return False
    return title_similarity(
        str(left.get("title") or ""),
        str(right.get("title") or ""),
    ) >= 0.86


def related_link(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item.get("title") or "",
        "url": item.get("url") or "",
        "source": item.get("source") or "",
        "sourceKind": item.get("sourceKind") or "news",
        "publishedAtUtc": item.get("publishedAtUtc"),
        "originGroup": item.get("originGroup") or reporting_origin_group(
            str(item.get("source") or ""),
            str(item.get("url") or ""),
        ),
        "verification": item.get("verification") or "reported",
        "rankingEvidence": item.get("discoveryProvider") != "issuer-dynamic",
    }


def cluster_story_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issuer_aliases: dict[str, set[str]] = {}
    alias_owners: dict[str, set[str]] = {}
    for company_item in items:
        if company_item.get("sourceKind") != "official-company":
            continue
        code = normalized_comparison_text(
            str(company_item.get("issuerCode") or "")
        )
        if not code:
            continue
        aliases = _issuer_aliases(company_item) - {code}
        issuer_aliases.setdefault(code, set()).update(aliases)
        for alias in aliases:
            alias_owners.setdefault(alias, set()).add(code)

    company_match_cache: dict[int, set[str]] = {}

    def company_item_code(item: dict[str, Any]) -> str:
        if item.get("sourceKind") != "official-company":
            return ""
        return normalized_comparison_text(str(item.get("issuerCode") or ""))

    def company_item_category(item: dict[str, Any]) -> str:
        if item.get("sourceKind") != "official-company":
            return ""
        return str(item.get("disclosureCategory") or "")

    def reported_company_category(item: dict[str, Any]) -> str:
        category, _ = company_disclosure_category(
            " ".join(str(item.get(key) or "") for key in ("title", "summary"))
        )
        return category

    def matched_company_codes(item: dict[str, Any]) -> set[str]:
        cache_key = id(item)
        if cache_key in company_match_cache:
            return company_match_cache[cache_key]
        item_code = company_item_code(item)
        if item_code:
            matched = {item_code}
            company_match_cache[cache_key] = matched
            return matched
        raw_text = unicodedata.normalize(
            "NFKC",
            " ".join(
                str(item.get(key) or "") for key in ("title", "summary")
            ),
        ).casefold()
        comparison_text = normalized_comparison_text(raw_text)
        matched: set[str] = set()
        for code, aliases in issuer_aliases.items():
            name_match = any(
                len(alias_owners.get(alias, set())) == 1
                and _issuer_alias_is_mentioned(
                    alias,
                    raw_text,
                    comparison_text,
                )
                for alias in aliases
            )
            if name_match or _issuer_code_is_mentioned(code, raw_text):
                matched.add(code)
        company_match_cache[cache_key] = matched
        return matched

    def company_safe_cluster(
        cluster: list[dict[str, Any]],
        item: dict[str, Any],
    ) -> bool:
        cluster_codes = {
            code
            for member in cluster
            if (code := company_item_code(member))
        }
        if len(cluster_codes) > 1:
            return False
        cluster_categories = {
            category
            for member in cluster
            if (category := company_item_category(member))
        }
        if len(cluster_categories) > 1:
            return False
        item_code = company_item_code(item)
        item_category = company_item_category(item)
        if cluster_codes:
            fixed_code = next(iter(cluster_codes))
            fixed_category = next(iter(cluster_categories), "")
            if item_code:
                return (
                    item_code == fixed_code
                    and bool(fixed_category)
                    and item_category == fixed_category
                )
            return (
                matched_company_codes(item) == {fixed_code}
                and bool(fixed_category)
                and reported_company_category(item) == fixed_category
            )
        if item_code:
            # Every member must independently identify the same issuer and
            # event category before a news-only cluster becomes a company one.
            return all(
                matched_company_codes(member) == {item_code}
                and bool(item_category)
                and reported_company_category(member) == item_category
                for member in cluster
            )
        return True

    ordered = sorted(
        items,
        key=lambda item: (
            item_effective_datetime(item) or datetime.min.replace(tzinfo=timezone.utc),
            int(item.get("priorityScore") or 0),
        ),
        reverse=True,
    )
    clusters: list[list[dict[str, Any]]] = []
    for item in ordered:
        target = next(
            (
                cluster
                for cluster in clusters
                if company_safe_cluster(cluster, item)
                and any(should_cluster_items(member, item) for member in cluster)
            ),
            None,
        )
        if target is None:
            clusters.append([item])
        else:
            target.append(item)

    representatives: list[dict[str, Any]] = []
    for members in clusters:
        official_members = [
            member
            for member in members
            if str(member.get("sourceKind") or "").startswith("official")
        ]
        representative = (
            max(
                official_members,
                key=lambda member: (
                    has_japanese(str(member.get("title") or "")),
                    item_effective_datetime(member)
                    or datetime.min.replace(tzinfo=timezone.utc),
                    int(member.get("priorityScore") or 0),
                ),
            )
            if official_members
            else next(
                (
                    member for member in members
                    if member.get("discoveryProvider") != "issuer-dynamic"
                ),
                members[0],
            )
        )
        # Canonicalize every URL before both display-link and ranking-evidence
        # selection.  Prefer the chosen lead for its URL and prefer a general
        # discovery result over issuer-dynamic when both resolve to the same
        # article.  Thus the label shown to readers matches the evidence that
        # was actually counted.
        member_by_url: dict[str, dict[str, Any]] = {}
        url_order: list[str] = []
        for member in [representative, *members]:
            member_url = normalize_url(str(member.get("url") or ""))
            if not member_url:
                continue
            current = member_by_url.get(member_url)
            if current is None:
                member_by_url[member_url] = member
                url_order.append(member_url)
            elif member is representative or (
                current.get("discoveryProvider") == "issuer-dynamic"
                and member.get("discoveryProvider") != "issuer-dynamic"
            ):
                member_by_url[member_url] = member
        visible_members = [member_by_url[url] for url in url_order]

        # Issuer-specific follow-up searches remain directly openable links,
        # but excluding them from rank evidence prevents query self-reward.
        ranking_members = [
            member for member in visible_members
            if member.get("discoveryProvider") != "issuer-dynamic"
        ] or [representative]
        origin_groups = {
            str(
                member.get("originGroup")
                or reporting_origin_group(
                    str(member.get("source") or ""),
                    str(member.get("url") or ""),
                )
            )
            for member in ranking_members
        }
        related: list[dict[str, Any]] = []
        for member in visible_members:
            if member is representative:
                continue
            related.append(related_link(member))
        representative["clusterSize"] = max(1, len(visible_members))
        representative["rankingClusterSize"] = max(1, len(ranking_members))
        representative["independentSourceCount"] = len(origin_groups)
        representative["corroborationState"] = (
            "official-primary"
            if str(representative.get("sourceKind") or "").startswith("official")
            else "multi-source"
            if len(origin_groups) >= 2
            else "single-source"
        )
        representative["relatedLinks"] = related[:20]
        representatives.append(representative)
    return representatives


def deduplicate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return cluster_story_candidates(items)


RESULT_BUNDLE_ANCILLARY_CATEGORIES = {
    "buyback",
    "stock-split",
    "dividend",
    "capital-raising",
}


def same_bundle_financial_result(
    candidate: dict[str, Any],
    company_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the issuer's core result released within the same 15-minute bundle."""

    # Preserve M&A, accounting and guidance as independent major events.  The
    # core-first rule is only for capital actions commonly announced alongside
    # results and liable to receive more headline pickup than the result itself.
    if candidate.get("disclosureCategory") not in RESULT_BUNDLE_ANCILLARY_CATEGORIES:
        return None
    issuer = str(candidate.get("issuerCode") or "")
    candidate_time = item_effective_datetime(candidate)
    if not issuer or candidate_time is None:
        return None
    matches = [
        row for row in company_items
        if isinstance(row, dict)
        and row.get("sourceKind") == "official-company"
        and str(row.get("issuerCode") or "") == issuer
        and row.get("disclosureCategory") == "financial-results"
        and (row_time := item_effective_datetime(row)) is not None
        and abs((row_time - candidate_time).total_seconds()) <= 15 * 60
    ]
    return max(
        matches,
        key=lambda row: (
            int(row.get("materialityScore") or 0),
            item_effective_datetime(row) or datetime.min.replace(tzinfo=timezone.utc),
        ),
    ) if matches else None


def rank_briefing_items(
    items: list[dict[str, Any]],
    *,
    already_clustered: bool = False,
) -> list[dict[str, Any]]:
    items = list(items) if already_clustered else cluster_story_candidates(items)
    topic_counts: dict[str, int] = {}
    for item in items:
        key = item.get("topicKey") or "policy"
        topic_counts[key] = topic_counts.get(key, 0) + 1
    for item in items:
        engagement = int(item.get("engagementTotal") or 0)
        independent_sources = max(1, int(item.get("independentSourceCount") or 1))
        ranking_cluster_size = max(
            1, int(item.get("rankingClusterSize") or item.get("clusterSize") or 1)
        )
        # An unknown publication time must not be ranked as if it were fresh.
        recency_component = (
            4
            if item.get("ageHours") is None
            else max(0, 30 - min(72, item["ageHours"]) / 3)
        )
        item["talkScore"] = min(
            100,
            round(
                12
                + min(30, independent_sources * 12)
                + min(12, math.log2(ranking_cluster_size + 1) * 4)
                + min(20, math.log10(engagement + 1) * 8)
                + recency_component
            ),
        )
    news_kinds = {
        "official-us",
        "official-japan",
        "official-company",
        "news",
        "news-wire",
    }
    news_items = [item for item in items if item.get("sourceKind") in news_kinds]
    social_items = [item for item in items if item.get("sourceKind") not in news_kinds]

    def newest_key(item: dict[str, Any]) -> tuple[Any, ...]:
        return (
            item_effective_datetime(item) or datetime.min.replace(tzinfo=timezone.utc),
            source_weight(str(item.get("sourceKind") or "")),
            int(item.get("priorityScore") or 0),
        )

    live_news = sorted(
        [
            item
            for item in news_items
            if (item.get("freshness") or {}).get("bucket")
            in {"breaking", "developing", "today"}
            and item_effective_datetime(item) is not None
            and not item.get("carriedForward")
        ],
        key=newest_key,
        reverse=True,
    )
    context_news = sorted(
        [item for item in news_items if item not in live_news],
        key=newest_key,
        reverse=True,
    )
    latest_market_news = [
        item for item in live_news
        if item.get("sourceKind") != "official-company"
    ]
    company_news = [
        item for item in live_news + context_news
        if item.get("sourceKind") == "official-company"
    ]

    def company_impact_key(item: dict[str, Any]) -> tuple[Any, ...]:
        return (
            int(item.get("materialityScore") or 0)
            + min(60, int(item.get("independentSourceCount") or 1) * 16)
            + min(36, int(item.get("rankingClusterSize") or item.get("clusterSize") or 1) * 3)
            + int(item.get("talkScore") or 0)
            + int(item.get("issuerBuzzScore") or 0),
            int(item.get("issuerBuzzScore") or 0),
            int(item.get("independentSourceCount") or 1),
            int(item.get("rankingClusterSize") or item.get("clusterSize") or 1),
            item_effective_datetime(item)
            or datetime.min.replace(tzinfo=timezone.utc),
        )

    company_news.sort(key=company_impact_key, reverse=True)
    social_items.sort(key=newest_key, reverse=True)

    # A same-time disclosure bundle often contains the core earnings release
    # plus ancillary capital actions.  When an ancillary item would enter the
    # display, insert that issuer's results first without naming or watching a
    # particular company.  This prevents stronger media pickup for a split or
    # buyback from hiding the earnings release that explains the bundle.
    prioritized_company_news: list[dict[str, Any]] = []
    for candidate in company_news:
        core = same_bundle_financial_result(candidate, company_news)
        if core is not None:
            prioritized_company_news.append(core)
        prioritized_company_news.append(candidate)
    company_news = prioritized_company_news

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    def select(candidate: dict[str, Any] | None) -> bool:
        if not candidate or candidate["id"] in selected_ids:
            return False
        selected.append(candidate)
        selected_ids.add(candidate["id"])
        return True

    # Keep a strict latest-news lane for macro, policy, market and media
    # updates.  The separate company lane below prevents an earnings-day flood
    # from either dominating the briefing or hiding major corporate events.
    for candidate in latest_market_news[:LATEST_ITEM_RESERVE]:
        select(candidate)

    for source_kind in ("official-us", "official-japan"):
        candidate = next(
            (
                row for row in live_news + context_news
                if row.get("sourceKind") == source_kind
            ),
            None,
        )
        select(candidate)

    # Reserve up to six material company disclosures.  The rules use event
    # type, independent reporting and same-time disclosure bundles; no issuer
    # name, code, watchlist or market-cap gate is required.
    issuer_counts: dict[str, int] = {}
    for category in (
        "financial-results",
        "guidance-revision",
        "m-and-a-tob",
        "accounting-governance",
    ):
        candidate = next(
            (
                row for row in company_news
                if row.get("disclosureCategory") == category
                and (
                    not row.get("issuerCode")
                    or issuer_counts.get(str(row.get("issuerCode")), 0) < 3
                )
            ),
            None,
        )
        if select(candidate):
            issuer = str(candidate.get("issuerCode") or "")
            issuer_counts[issuer] = issuer_counts.get(issuer, 0) + 1
    company_slots = sum(
        1 for row in selected
        if row.get("sourceKind") == "official-company"
    )
    for candidate in company_news:
        if company_slots >= 6:
            break
        issuer = str(candidate.get("issuerCode") or "")
        if issuer and issuer_counts.get(issuer, 0) >= 3:
            continue
        if select(candidate):
            company_slots += 1
            issuer_counts[issuer] = issuer_counts.get(issuer, 0) + 1

    # Enforce the bundle invariant after every selection route: if a selected
    # capital action has a same-time result but the result is absent, replace
    # the first such ancillary selection with the core result.
    for index, candidate in enumerate(list(selected)):
        if candidate.get("sourceKind") != "official-company":
            continue
        core = same_bundle_financial_result(candidate, company_news)
        if core is None or core.get("id") in selected_ids:
            continue
        candidate_id = str(candidate.get("id") or "")
        if candidate_id:
            selected_ids.discard(candidate_id)
        selected[index] = core
        selected_ids.add(str(core.get("id") or ""))

    for kinds in (
        {"x-api", "x-index"},
        {"linkedin"},
        {"truth-social", "truth-social-archive"},
    ):
        candidate = next((row for row in items if row.get("sourceKind") in kinds), None)
        select(candidate)
    economist_candidate = next((
        row for row in items
        if row.get("sourceKind") != "official-company"
        and any(
            name in ((row.get("title") or "") + " " + (row.get("summary") or "")).lower()
            for name in ECONOMIST_WATCH_NAMES
        )
    ), None)
    select(economist_candidate)
    for stance in ("bullish", "bearish"):
        candidate = next((
            row for row in live_news + context_news
            if row.get("stance") == stance
            and row.get("topicKey") in {"us-stocks", "japan-stocks", "ai-bubble"}
            and row.get("sourceKind") != "official-company"
        ), None)
        select(candidate)
    for item in latest_market_news + company_news + context_news + social_items:
        if len(selected) >= BRIEFING_ITEM_LIMIT:
            break
        if item.get("sourceKind") == "official-company":
            issuer = str(item.get("issuerCode") or "")
            if company_slots >= 6:
                continue
            if issuer and issuer_counts.get(issuer, 0) >= 3:
                continue
            if select(item):
                company_slots += 1
                issuer_counts[issuer] = issuer_counts.get(issuer, 0) + 1
            continue
        select(item)
    selected.sort(key=newest_key, reverse=True)
    return selected[:BRIEFING_ITEM_LIMIT]


def _translation_fidelity_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value or "")
    numeric = [
        token.replace(",", "")
        for token in re.findall(r"(?<![A-Za-z])[-+]?\d[\d,.]*%?", normalized)
    ]
    protected = [
        token.upper().replace(" ", "")
        for token in re.findall(
            r"USD\s*/\s*JPY|S&P\s*500|(?<![A-Za-z0-9])[A-Z]{2,5}(?![A-Za-z0-9])|[$¥€£]",
            normalized,
        )
    ]
    return sorted(numeric + protected)


def apply_optional_deepl_translations(
    items: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Translate a bounded selected batch, while keeping a no-key fallback."""

    cached_count = sum(
        1
        for item in items
        if (item.get("japanese") or {}).get("mode") == "deepl"
    )
    api_key = (
        os.environ.get("DEEPL_AUTH_KEY")
        or os.environ.get("DEEPL_API_KEY")
        or ""
    ).strip()
    if not api_key:
        return {
            "status": "cache-only" if cached_count else "not-configured",
            "label": (
                "前回のDeepL翻訳を再利用"
                if cached_count
                else "DeepL未設定・構造化要旨を表示"
            ),
            "translatedItems": 0,
            "cachedItems": cached_count,
        }

    slots: list[tuple[dict[str, Any], str, str]] = []
    for item in items:
        original = item.get("original") or {}
        japanese = item.get("japanese") or {}
        if (
            original.get("language") != "en"
            or japanese.get("mode") != "structured-gist"
        ):
            continue
        for field in ("title", "excerpt"):
            source_text = clean_text(original.get(field))
            if not source_text or len(slots) >= DEEPL_BATCH_LIMIT:
                continue
            slots.append((item, field, source_text))
        if len(slots) >= DEEPL_BATCH_LIMIT:
            break
    if not slots:
        return {
            "status": "no-candidates",
            "label": "翻訳対象なし",
            "translatedItems": 0,
            "cachedItems": cached_count,
        }

    endpoint = os.environ.get("DEEPL_API_URL", "").strip()
    if not endpoint:
        endpoint = (
            "https://api-free.deepl.com/v2/translate"
            if api_key.endswith(":fx")
            else "https://api.deepl.com/v2/translate"
        )
    body = json.dumps({
        "text": [source_text for _, _, source_text in slots],
        "source_lang": "EN",
        "target_lang": "JA",
        "split_sentences": "nonewlines",
        "preserve_formatting": True,
    }).encode("utf-8")
    try:
        raw, _ = request(
            endpoint,
            timeout=15,
            attempts=1,
            data=body,
            method="POST",
            headers={
                "Authorization": f"DeepL-Auth-Key {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        translated_rows = json.loads(raw.decode("utf-8")).get("translations") or []
        if len(translated_rows) != len(slots):
            raise RuntimeError("DeepL returned an unexpected translation count")
    except Exception as exc:
        return {
            "status": "failed",
            "label": "DeepL失敗・構造化要旨を表示",
            "translatedItems": 0,
            "cachedItems": cached_count,
            "message": str(exc)[:240],
        }

    updates: dict[int, dict[str, str]] = {}
    references: dict[int, dict[str, Any]] = {}
    rejected_references: set[int] = set()
    for (item, field, source_text), translated_row in zip(slots, translated_rows):
        reference = id(item)
        references[reference] = item
        translated = clean_text(translated_row.get("text"))
        if (
            not translated
            or not has_japanese(translated)
            or _translation_fidelity_tokens(source_text)
            != _translation_fidelity_tokens(translated)
        ):
            rejected_references.add(reference)
            continue
        updates.setdefault(reference, {})[field] = translated

    translated_count = 0
    for reference, fields in updates.items():
        if reference in rejected_references or not fields.get("title"):
            continue
        item = references[reference]
        previous_japanese = item.get("japanese") or {}
        item["japanese"] = {
            "title": fields["title"],
            "summary": fields.get("excerpt") or previous_japanese.get("summary") or "",
            "mode": "deepl",
            "label": "自動参考訳（DeepL・未校閲）",
            "provider": "DeepL",
            "generatedAtUtc": now.isoformat(),
            "sourceHash": previous_japanese.get("sourceHash"),
        }
        translated_count += 1
    return {
        "status": "limited" if rejected_references else "ok",
        "label": (
            "DeepL短文バッチ"
            if not rejected_references
            else "DeepL結果の一部を品質ゲートで不採用・構造化要旨を表示"
        ),
        "translatedItems": translated_count,
        "cachedItems": cached_count,
        "rejectedItems": len(rejected_references),
        "requestedTexts": len(slots),
    }


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
            "日米の一次機関・企業開示",
            ("official-us", "official-japan", "company-disclosure"),
            MOF_INTERVENTION_URL,
            "政策公表・企業開示の時刻と市場の値動きには時間差があります。",
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
    *,
    items_clustered: bool = False,
) -> dict[str, Any]:
    selected = rank_briefing_items(items, already_clustered=items_clustered)
    translation_status = apply_optional_deepl_translations(selected, now)
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
        "取得範囲の注目度は、鮮度・独立出所数・クラスタ規模・取得できた反応数の補助指標で、事実確認度や相場方向とは別です。"
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
            "shockDirection": shock.get("shockDirection") or "unknown",
            "recentDirectionalShock": bool(shock.get("recentDirectionalShock")),
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
        "translationStatus": translation_status,
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


def upgrade_previous_item(
    row: Any,
    now: datetime,
    *,
    allow_breaking: bool = False,
) -> dict[str, Any] | None:
    """Normalize a previous public item before it can be carried forward."""

    if not isinstance(row, dict):
        return None
    title = clean_text(row.get("title"))
    url = normalize_url(str(row.get("url") or ""))
    source = clean_text(row.get("source"))
    if (
        not title
        or not source
        or urllib.parse.urlparse(url).scheme != "https"
        or not publisher_domain(url)
    ):
        return None

    current_required = {
        "original",
        "japanese",
        "effectivePublishedAtUtc",
        "indexedAtUtc",
        "firstSeenAtUtc",
        "timestampBasis",
        "timestampPrecision",
        "freshness",
        "effect",
        "clusterId",
        "clusterSize",
        "rankingClusterSize",
        "independentSourceCount",
        "corroborationState",
        "relatedLinks",
        "originGroup",
        "publisherDomain",
        "sourceCountry",
        "discoveryProvider",
    }
    if current_required.issubset(row):
        upgraded = dict(row)
        effective = item_effective_datetime(upgraded)
        first_seen = (
            parse_datetime(upgraded.get("firstSeenAtUtc"))
            or effective
            or now
        )
        if effective and first_seen < effective - timedelta(minutes=10):
            first_seen = effective
        if first_seen > now + timedelta(minutes=2):
            first_seen = now
        upgraded["retrievedAtUtc"] = now.isoformat()
        upgraded["firstSeenAtUtc"] = first_seen.astimezone(timezone.utc).isoformat()
        age_hours = (
            max(0.0, (now - effective).total_seconds() / 3600.0)
            if effective
            else None
        )
        upgraded["ageHours"] = round(age_hours, 2) if age_hours is not None else None
        freshness = freshness_profile(
            effective,
            now,
            str(upgraded.get("timestampPrecision") or "unknown"),
        )
        freshness["firstSeenAtUtc"] = upgraded["firstSeenAtUtc"]
        upgraded["freshness"] = freshness
    else:
        source_kind = str(row.get("sourceKind") or "news")
        verification = row.get("verification")
        engagement = row.get("engagement")
        upgraded = build_item(
            title=title,
            url=url,
            source=source,
            source_kind=source_kind,
            published=row.get("publishedAtUtc"),
            retrieved_at=now,
            summary=clean_text(row.get("summary")),
            topic_hint=row.get("topicKey"),
            verification=str(verification) if verification else None,
            engagement=engagement if isinstance(engagement, dict) else None,
            author=clean_text(row.get("author")),
            identity_note=clean_text(row.get("identityNote")),
            indexed_at=row.get("indexedAtUtc"),
            first_seen_at=(
                row.get("firstSeenAtUtc")
                or row.get("retrievedAtUtc")
                or row.get("publishedAtUtc")
            ),
            timestamp_basis=row.get("timestampBasis"),
            timestamp_precision_value=row.get("timestampPrecision"),
            discovery_provider=str(
                row.get("discoveryProvider") or "previous-public-snapshot"
            ),
            source_country=clean_text(row.get("sourceCountry")),
        )
        previous_japanese = row.get("japanese") or {}
        if (
            previous_japanese.get("mode") == "deepl"
            and previous_japanese.get("sourceHash")
            == (upgraded.get("japanese") or {}).get("sourceHash")
        ):
            upgraded["japanese"] = dict(previous_japanese)
        previous_talk_score = row.get("talkScore")
        if isinstance(previous_talk_score, int) and 0 <= previous_talk_score <= 100:
            upgraded["talkScore"] = previous_talk_score

        # Preserve generic company metadata when upgrading a pre-schema
        # snapshot.  No issuer-specific values are introduced here.
        for key in (
            "disclosureId",
            "issuerCode",
            "issuerName",
            "disclosureCategory",
            "materialityScore",
            "issuerNewsMentionCount",
            "issuerIndependentNewsSourceCount",
            "issuerBuzzScore",
        ):
            if key in row:
                upgraded[key] = row[key]

    if (
        not allow_breaking
        and (upgraded.get("freshness") or {}).get("bucket") == "breaking"
    ):
        # A fallback item must never enter the current breaking lane.
        return None
    return upgraded


def carry_forward_if_needed(
    package: dict[str, Any],
    previous: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    current_items = ((package.get("briefing") or {}).get("items") or [])
    previous_items = ((previous.get("briefing") or {}).get("items") or [])
    if len(current_items) >= 4 or not previous_items:
        return package
    prioritized_previous_items: list[dict[str, Any]] = []
    for row in previous_items:
        if isinstance(row, dict):
            core = same_bundle_financial_result(row, previous_items)
            if core is not None:
                prioritized_previous_items.append(core)
        prioritized_previous_items.append(row)
    previous_items = prioritized_previous_items
    carried = []
    current_ids = {row.get("id") for row in current_items}
    company_slots = sum(
        row.get("sourceKind") == "official-company"
        for row in current_items
    )
    issuer_counts: dict[str, int] = {}
    for current in current_items:
        if current.get("sourceKind") == "official-company":
            issuer = str(current.get("issuerCode") or "")
            issuer_counts[issuer] = issuer_counts.get(issuer, 0) + 1
    for row in previous_items:
        copy = upgrade_previous_item(row, now)
        if copy is None or copy.get("id") in current_ids:
            continue
        if copy.get("sourceKind") == "official-company":
            issuer = str(copy.get("issuerCode") or "")
            if company_slots >= 6:
                continue
            if issuer and issuer_counts.get(issuer, 0) >= 3:
                continue
        copy["carriedForward"] = True
        copy["staleReason"] = "今回の取得件数が不足したため前回候補を保持"
        carried.append(copy)
        current_ids.add(copy.get("id"))
        if copy.get("sourceKind") == "official-company":
            company_slots += 1
            issuer = str(copy.get("issuerCode") or "")
            issuer_counts[issuer] = issuer_counts.get(issuer, 0) + 1
        if len(current_items) + len(carried) >= BRIEFING_ITEM_LIMIT:
            break
    combined_items = sorted(
        current_items,
        key=lambda item: item_effective_datetime(item)
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    ) + carried
    briefing = package["briefing"]
    briefing["items"] = combined_items
    topic_counts: dict[str, int] = {}
    verification_counts: dict[str, int] = {}
    source_kind_counts: dict[str, int] = {}
    for item in combined_items:
        topic_key = str(item["topicKey"])
        verification = str(item["verification"])
        source_kind = str(item["sourceKind"])
        topic_counts[topic_key] = topic_counts.get(topic_key, 0) + 1
        verification_counts[verification] = verification_counts.get(verification, 0) + 1
        source_kind_counts[source_kind] = source_kind_counts.get(source_kind, 0) + 1

    def direction_rows(stance: str) -> list[dict[str, str]]:
        return [
            {
                "title": item["title"],
                "source": item["source"],
                "url": item["url"],
                "verification": item["verification"],
            }
            for item in combined_items
            if item["stance"] == stance
            and item.get("topicKey") in {"us-stocks", "japan-stocks", "ai-bubble"}
        ][:4]

    briefing["topicCounts"] = topic_counts
    briefing["verificationCounts"] = verification_counts
    briefing["sourceKindCounts"] = source_kind_counts
    briefing["bullish"] = direction_rows("bullish")
    briefing["bearish"] = direction_rows("bearish")
    briefing["unverifiedCount"] = sum(
        item["verification"] == "unverified" for item in combined_items
    )
    leading_topics = sorted(topic_counts.items(), key=lambda row: (-row[1], row[0]))
    focus = "、".join(
        f"{TOPICS[key]['label']} {count}件"
        for key, count in leading_topics[:3]
    )
    briefing["summary"] = (
        f"直近の重要候補は{len(combined_items)}件。{focus or '新着候補なし'}です。"
        "取得範囲の注目度は、鮮度・独立出所数・クラスタ規模・取得できた反応数の補助指標で、"
        "事実確認度や相場方向とは別です。"
        f" 取得不足のため前回候補{len(carried)}件を保持しています。"
    )
    package["dataHealth"]["carriedForwardItems"] = len(carried)
    package["dataHealth"]["status"] = "partial"
    package["dataHealth"]["message"] = (
        f"新規取得{len(current_items)}件。前回候補{len(carried)}件を時刻表示付きで保持しました。"
    )
    package["fallbackAppliedAtUtc"] = now.isoformat()
    return package


def build_live_package(previous: dict[str, Any] | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    previous = previous or {}
    quotes, quote_status = fetch_intraday_quotes(now)
    source_status: list[dict[str, Any]] = list(quote_status)
    items: list[dict[str, Any]] = []
    previous_cache = previous.get("companyDisclosureCache")
    cache_available = (
        "companyDisclosureCache" in previous
        and isinstance(previous_cache, list)
        and bool(previous_cache)
    )
    previous_tdnet_state = next(
        (
            row for row in (previous.get("sourceStatus") or [])
            if isinstance(row, dict)
            and row.get("kind") == "company-disclosure"
        ),
        {},
    ) if cache_available else {}
    # Rebuild once after a coverage algorithm upgrade.  A legacy cache may be
    # internally valid yet contain only the current TDnet calendar day.
    incremental_tdnet_state = (
        previous_tdnet_state
        if previous_tdnet_state.get("coverageVersion")
        == TDNET_SCAN_COVERAGE_VERSION
        and previous_tdnet_state.get("coverageComplete") is True
        else {}
    )
    jobs: list[tuple[str, Any, dict[str, Any] | None]] = []
    for feed in OFFICIAL_FEEDS:
        jobs.append((feed["kind"], fetch_official_feed, feed))
    for feed in COMPANY_DISCLOSURE_FEEDS:
        definition = {
            **feed,
            "previousState": incremental_tdnet_state,
        }
        jobs.append((
            str(feed.get("statusKind") or feed["kind"]),
            fetch_company_disclosures,
            definition,
        ))
    for query_def in NEWS_QUERIES:
        providers = {
            str(provider).casefold()
            for provider in query_def.get("providers") or ("bing", "google")
        }
        if "bing" in providers:
            jobs.append(("news", fetch_bing_news, query_def))
        if "google" in providers:
            jobs.append(("news", fetch_google_news, query_def))
    gdelt_terms = [
        re.sub(
            r"\s+sourcelang:english\s*$",
            "",
            query_def["query"],
            flags=re.I,
        )
        for query_def in GDELT_QUERIES
    ]
    jobs.append(("news-discovery", fetch_gdelt_news, {
        "key": "integrated",
        "name": "GDELT / integrated",
        "url": GDELT_DOC_URL,
        "query": "(" + " OR ".join(f"({term})" for term in gdelt_terms) + ") sourcelang:english",
    }))
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

    current_disclosure_ids = {
        str(item.get("disclosureId") or "")
        for item in items
        if item.get("sourceKind") == "official-company"
        and item.get("disclosureId")
    }
    items.extend(restore_company_disclosure_cache(
        previous_cache,
        now,
        current_disclosure_ids,
    ))

    # The company names are derived from this run's official TDnet candidates.
    # Provider queries therefore follow whatever is material today instead of
    # relying on a permanent issuer watchlist.
    dynamic_queries = build_dynamic_company_news_queries(items)
    if dynamic_queries:
        dynamic_jobs: list[tuple[Any, dict[str, Any]]] = []
        for query_def in dynamic_queries:
            dynamic_jobs.append((fetch_google_news, query_def))
            dynamic_jobs.append((fetch_bing_news, query_def))
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(function, definition, now): (
                    function,
                    definition,
                )
                for function, definition in dynamic_jobs
            }
            for future in as_completed(futures):
                function, definition = futures[future]
                try:
                    fetched_items, status = future.result()
                    items.extend(fetched_items)
                    source_status.append(status)
                except Exception as exc:
                    provider = (
                        "Google News"
                        if function is fetch_google_news
                        else "Bing News"
                    )
                    source_status.append({
                        "name": f"{provider} / {definition['name']}",
                        "kind": "news-discovery",
                        "status": "failed",
                        "url": "",
                        "retrievedAtUtc": now.isoformat(),
                        "message": str(exc),
                    })

    # The official PDF remains valid after it leaves the first TDnet page.
    # Re-evaluate previously selected official disclosures for 48 hours so a
    # story that becomes widely discussed later does not disappear merely
    # because hundreds of newer routine filings arrived.
    current_urls = {
        normalize_url(str(item.get("url") or ""))
        for item in items
    }
    for previous_item in ((previous.get("briefing") or {}).get("items") or []):
        if (
            not isinstance(previous_item, dict)
            or previous_item.get("sourceKind") != "official-company"
            or publisher_domain(str(previous_item.get("url") or ""))
            != "www.release.tdnet.info"
        ):
            continue
        effective = item_effective_datetime(previous_item)
        if effective is None or now - effective > timedelta(hours=48):
            continue
        url = normalize_url(str(previous_item.get("url") or ""))
        if url in current_urls:
            continue
        cached = upgrade_previous_item(
            previous_item,
            now,
            allow_breaking=True,
        )
        if cached is None:
            continue
        cached["identityNote"] = (
            clean_text(cached.get("identityNote"))
            + " 直近48時間の公式開示を前回スナップショットから再評価。"
        ).strip()
        cached["discoveryProvider"] = "tdnet-recent-cache"
        cached.pop("carriedForward", None)
        cached.pop("staleReason", None)
        items.append(cached)
        current_urls.add(url)

    items.extend(audited_current_event_items(now))
    items.extend(audited_current_market_items(now))
    inherit_previous_item_state(items, previous, now)
    annotate_company_news_signals(items)
    company_disclosure_cache = build_company_disclosure_cache(items, now)
    items = cluster_story_candidates(items)
    shock = build_market_shock(quotes, now)
    update_intervention_assessment(shock, items)
    premarket = build_premarket(quotes, now)
    briefing = build_briefing(items, source_status, shock, now, items_clustered=True)
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
            "targetIntervalMinutes": 5,
            "delivery": "GitHub Actions scheduled snapshot",
            "buttonBehavior": "公開版の更新ボタンは最後に配信済みのスナップショットを再読込",
            "warning": (
                "5分間隔を目標にしますが、GitHub Actionsの開始時刻と配信時刻は保証されず、"
                "混雑・取得元障害・CDNキャッシュにより遅延する場合があります。"
            ),
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
        "companyDisclosureCache": company_disclosure_cache,
        "sourceStatus": source_status,
        "methodology": {
            "intervention": (
                "価格急変と介入確認を分離。価格条件はアラートだけに使い、"
                "財務省の一次公表が確認できるまで officiallyConfirmed=false とする。"
            ),
            "talkScore": (
                "取得範囲の注目度として、鮮度、クラスタ内の独立出所数と記事数、取得できた公開反応数を"
                "0–100に整理。会社開示は全社共通の一般ニュース検索における企業名・明示的な証券コードの"
                "言及と独立配信元も別の会社話題度として集計する。媒体横断の全投稿数でも危険確率でもない。"
            ),
            "stance": (
                "見出し・投稿中の限定語彙から強気・弱気・混合・中立を分類。"
                "投資判断、著者の全体見解、記事本文の精読を代替しない。"
            ),
        },
    }
    return carry_forward_if_needed(package, previous, now)


def load_previous_snapshot(path: Path = OUTPUT) -> dict[str, Any]:
    """Choose the newest valid local or last-published public snapshot."""

    now = datetime.now(timezone.utc)
    candidates: list[dict[str, Any]] = []

    def add_candidate(value: Any) -> None:
        if not isinstance(value, dict):
            return
        generated = parse_datetime(value.get("generatedAtUtc"))
        if generated is not None and generated > now + timedelta(minutes=2):
            return
        candidates.append(value)

    if path.exists():
        try:
            add_candidate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass

    skip_public = os.environ.get("LIVE_SKIP_PUBLIC_SNAPSHOT", "").strip().casefold()
    if skip_public not in {"1", "true", "yes", "on"}:
        public_url = (
            os.environ.get("LIVE_PREVIOUS_URL", "").strip()
            or PUBLIC_SNAPSHOT_URL
        )
        parsed_public_url = urllib.parse.urlparse(public_url)
        if parsed_public_url.scheme == "https" and parsed_public_url.hostname:
            separator = "&" if parsed_public_url.query else "?"
            cache_busted_url = f"{public_url}{separator}v={int(now.timestamp())}"
            try:
                raw, _ = request(
                    cache_busted_url,
                    timeout=8,
                    attempts=1,
                    headers={
                        "Accept": "application/json",
                        "Cache-Control": "no-cache",
                        "Pragma": "no-cache",
                    },
                )
                add_candidate(json.loads(raw.decode("utf-8")))
            except (RuntimeError, UnicodeDecodeError, json.JSONDecodeError):
                pass

    if not candidates:
        return {}
    return max(
        candidates,
        key=lambda value: parse_datetime(value.get("generatedAtUtc"))
        or datetime.min.replace(tzinfo=timezone.utc),
    )


def write_live_package(path: Path = OUTPUT) -> dict[str, Any]:
    previous = load_previous_snapshot(path)
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
