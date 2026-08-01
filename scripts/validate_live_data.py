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
BRIEFING_ITEM_LIMIT = 24
LATEST_ITEM_RESERVE = 10

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

PREMARKET_DISPLAY_KEYS = (
    "NIKKEI_FUTURES_YEN", "NIKKEI_FUTURES_USD",
    "SP500_FUTURES", "NASDAQ100_FUTURES", "DOW_FUTURES", "RUSSELL2000_FUTURES",
    "USDJPY", "US10Y", "VIX",
)
MARKET_SUMMARY_OVERLAY_KEYS = (
    "NIKKEI_CASH", "SP500_CASH", "DXY", "ACWI_CASH", "KIOXIA",
)

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
    "official-company",
    "news",
    "news-wire",
    "x-api",
    "x-index",
    "linkedin",
    "bluesky",
    "truth-social",
    "truth-social-archive",
}
OFFICIAL_SOURCE_HOSTS = {
    "official-us": {
        "federalreserve.gov",
        "whitehouse.gov",
        "treasury.gov",
        "bls.gov",
        "sec.gov",
    },
    "official-japan": {"boj.or.jp", "mof.go.jp"},
    "official-company": {
        "kioxia-holdings.com",
        "ssl4.eir-parts.net",
        "release.tdnet.info",
        "finance-frontend-pc-dist.west.edge.storage-yahoo.jp",
    },
}
DISCLOSURE_CATEGORIES = {
    "financial-results",
    "guidance-revision",
    "dividend",
    "buyback",
    "stock-split",
    "m-and-a-tob",
    "capital-raising",
    "accounting-governance",
    "material-loss-gain",
    "delisting-supervision",
    "disaster-operational",
}
DISCLOSURE_SCAN_MODES = {"full", "incremental", "head-only"}
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
TRANSLATION_MODES = {
    "source-japanese",
    "editorial-summary",
    "deepl",
    "structured-gist",
    "unavailable",
}
FRESHNESS_BUCKETS = {"breaking", "developing", "today", "context", "unknown"}
TIMESTAMP_PRECISIONS = {"second", "minute", "date", "unknown"}
DIRECTION_LABELS = {
    "bullish": "強気",
    "bearish": "弱気",
    "mixed": "強弱混在",
    "neutral": "方向なし",
}
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
        return urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path,
            "",
            urllib.parse.urlencode(sorted(kept_pairs), doseq=True),
            "",
        ))
    except Exception:
        return value


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


def has_japanese(value: str) -> bool:
    return re.search(r"[ぁ-んァ-ン一-龥々〆ヶ]", value or "") is not None


def normalized_comparison_text(value: str) -> str:
    return re.sub(r"[^a-z0-9一-龥ぁ-んァ-ン]+", "", (value or "").casefold())


def expected_translation_source_hash(title: str, excerpt: str) -> str:
    return hashlib.sha256((title + "\n" + excerpt).encode("utf-8")).hexdigest()


def parse_nullable_utc_timestamp(value: Any, context: str) -> datetime | None:
    if value is None:
        return None
    return parse_timestamp(value, context, expected_offset=timedelta(0))


def validate_localized_fields(
    item: dict[str, Any],
    context: str,
    generated: datetime,
    published: datetime | None,
    retrieved: datetime,
    carried: bool,
) -> None:
    """Validate the additive bilingual/freshness contract while retaining legacy keys."""

    original = require_dict(item["original"], f"{context}.original")
    require_keys(original, {"language", "title", "excerpt"}, f"{context}.original")
    language = require_string(original["language"], f"{context}.original.language")
    require(language in {"ja", "en", "und"}, f"{context}.original.language is invalid")
    original_title = require_string(original["title"], f"{context}.original.title")
    original_excerpt = require_string(
        original["excerpt"], f"{context}.original.excerpt", allow_empty=True
    )
    require(len(original_title) <= 1000, f"{context}.original.title is unexpectedly long")
    require(len(original_excerpt) <= 280, f"{context}.original.excerpt exceeds 280 characters")
    require(
        original_title == item["title"],
        f"{context}.original.title must preserve the legacy title exactly",
    )
    if original_excerpt:
        require(
            normalized_comparison_text(original_excerpt)
            != normalized_comparison_text(original_title),
            f"{context}.original.excerpt repeats the title",
        )
    if language == "ja":
        require(has_japanese(original_title), f"{context} marks a non-Japanese title as ja")
    if language == "en":
        require(re.search(r"[A-Za-z]", original_title), f"{context} English title lacks Latin text")
        require(
            not has_japanese(original_excerpt),
            f"{context}.original.excerpt contains a Japanese editorial summary",
        )

    japanese = require_dict(item["japanese"], f"{context}.japanese")
    require_keys(
        japanese,
        {
            "title",
            "summary",
            "mode",
            "label",
            "provider",
            "generatedAtUtc",
            "sourceHash",
        },
        f"{context}.japanese",
    )
    ja_title = require_string(japanese["title"], f"{context}.japanese.title")
    ja_summary = require_string(
        japanese["summary"], f"{context}.japanese.summary", allow_empty=True
    )
    mode = require_string(japanese["mode"], f"{context}.japanese.mode")
    label = require_string(japanese["label"], f"{context}.japanese.label")
    provider = japanese["provider"]
    require(
        provider is None or isinstance(provider, str),
        f"{context}.japanese.provider must be a string or null",
    )
    require(mode in TRANSLATION_MODES, f"{context}.japanese.mode is invalid: {mode}")
    generated_at = parse_timestamp(
        japanese["generatedAtUtc"],
        f"{context}.japanese.generatedAtUtc",
        expected_offset=timedelta(0),
    )
    require(
        generated_at <= generated + timedelta(minutes=2),
        f"{context}.japanese.generatedAtUtc is after package generation",
    )
    source_hash = require_string(
        japanese["sourceHash"], f"{context}.japanese.sourceHash"
    )
    require(
        re.fullmatch(r"[0-9a-f]{64}", source_hash) is not None,
        f"{context}.japanese.sourceHash is malformed",
    )
    require(
        source_hash == expected_translation_source_hash(original_title, original_excerpt),
        f"{context}.japanese.sourceHash does not match the original",
    )

    if mode == "source-japanese":
        require(language == "ja", f"{context} source-japanese requires a Japanese original")
        require(ja_title == original_title, f"{context} Japanese source title was altered")
        require("原文" in label or "日本語" in label, f"{context} source label is unclear")
    elif mode == "editorial-summary":
        require(
            has_japanese(ja_title + ja_summary),
            f"{context} editorial-summary has no Japanese text",
        )
        require("編集" in label or "要旨" in label, f"{context} editorial label is unclear")
    elif mode == "deepl":
        require(language != "ja", f"{context} must not send a Japanese original to DeepL")
        require(has_japanese(ja_title + ja_summary), f"{context} DeepL result has no Japanese")
        require(
            isinstance(provider, str) and "deepl" in provider.casefold(),
            f"{context} DeepL provider is not disclosed",
        )
        require("DeepL" in label, f"{context} DeepL label is not disclosed")
    elif mode == "structured-gist":
        require(
            has_japanese(ja_title + ja_summary),
            f"{context} structured-gist has no Japanese text",
        )
        require(
            "構造化" in label or "要旨" in label or "要点" in label,
            f"{context} structured-gist label is unclear",
        )
        require(
            "翻訳ではありません" in label,
            f"{context} structured-gist must explicitly say it is not a translation",
        )
    else:
        require("未取得" in label, f"{context} unavailable translation is not disclosed")

    indexed = parse_nullable_utc_timestamp(item["indexedAtUtc"], f"{context}.indexedAtUtc")
    effective = parse_timestamp(
        item["effectivePublishedAtUtc"],
        f"{context}.effectivePublishedAtUtc",
        expected_offset=timedelta(0),
    )
    expected_effective = published or indexed
    require(
        expected_effective is not None and same_instant(effective, expected_effective),
        f"{context}.effectivePublishedAtUtc must use publishedAtUtc, or indexedAtUtc when publication time is unavailable",
    )
    if indexed is not None:
        require(
            indexed <= retrieved + timedelta(minutes=10),
            f"{context}.indexedAtUtc is after retrieval",
        )
    if published is None:
        require(indexed is not None, f"{context} lacks both publication and index timestamps")
        require(
            item["timestampBasis"] == "index-seen",
            f"{context}.timestampBasis must disclose index-seen when publishedAtUtc is unavailable",
        )
    first_seen = parse_timestamp(
        item["firstSeenAtUtc"],
        f"{context}.firstSeenAtUtc",
        expected_offset=timedelta(0),
    )
    require(
        first_seen <= retrieved + timedelta(minutes=2),
        f"{context}.firstSeenAtUtc is after retrieval",
    )
    require(
        first_seen >= effective - timedelta(minutes=10),
        f"{context}.firstSeenAtUtc predates publication",
    )
    basis = require_string(item["timestampBasis"], f"{context}.timestampBasis")
    require(len(basis) <= 120, f"{context}.timestampBasis is unexpectedly long")
    precision = require_string(item["timestampPrecision"], f"{context}.timestampPrecision")
    require(
        precision in TIMESTAMP_PRECISIONS,
        f"{context}.timestampPrecision is invalid: {precision}",
    )

    freshness = require_dict(item["freshness"], f"{context}.freshness")
    require_keys(
        freshness,
        {"bucket", "label", "ageMinutes", "firstSeenAtUtc"},
        f"{context}.freshness",
    )
    bucket = require_string(freshness["bucket"], f"{context}.freshness.bucket")
    require(bucket in FRESHNESS_BUCKETS, f"{context}.freshness.bucket is invalid")
    freshness_label = require_string(
        freshness["label"], f"{context}.freshness.label"
    )
    require(
        freshness["firstSeenAtUtc"] == item["firstSeenAtUtc"],
        f"{context}.freshness.firstSeenAtUtc differs from the item",
    )
    expected_age_minutes = max(
        0, round((retrieved - effective).total_seconds() / 60)
    )
    age_minutes = freshness["ageMinutes"]
    if precision == "unknown":
        require(age_minutes is None, f"{context} unknown timestamp must have null age")
        require((bucket, freshness_label) == ("unknown", "時刻未確認"), f"{context} unknown freshness mismatch")
    else:
        require_int(age_minutes, f"{context}.freshness.ageMinutes", low=0)
        require(
            age_minutes == expected_age_minutes,
            f"{context}.freshness.ageMinutes mismatch",
        )
        if precision == "date":
            expected_bucket, expected_label = "context", "日付のみ"
        elif expected_age_minutes <= 30:
            expected_bucket, expected_label = "breaking", "30分以内"
        elif expected_age_minutes <= 180:
            expected_bucket, expected_label = "developing", "3時間以内"
        elif expected_age_minutes <= 1440:
            expected_bucket, expected_label = "today", "24時間以内"
        else:
            expected_bucket, expected_label = "context", "背景情報"
        require(
            (bucket, freshness_label) == (expected_bucket, expected_label),
            f"{context}.freshness bucket/label mismatch",
        )
    if carried:
        require(bucket != "breaking", f"{context} carried item must not appear as breaking")

    effects = require_list(item["effect"], f"{context}.effect")
    require(effects, f"{context}.effect must not be empty")
    for effect_index, raw_effect in enumerate(effects):
        effect_context = f"{context}.effect[{effect_index}]"
        effect = require_dict(raw_effect, effect_context)
        require_keys(
            effect,
            {"target", "direction", "label", "basis"},
            effect_context,
        )
        target = require_string(effect["target"], f"{effect_context}.target")
        direction = require_string(effect["direction"], f"{effect_context}.direction")
        require(direction in STANCE_VALUES, f"{effect_context}.direction is invalid")
        expected_label = f"{target}に{DIRECTION_LABELS[direction]}"
        require(effect["label"] == expected_label, f"{effect_context}.label mismatch")
        require_string(effect["basis"], f"{effect_context}.basis")
    combined_original = (original_title + " " + original_excerpt).casefold()
    if item["topicKey"] == "fx-rates" and re.search(r"\byen\b|円", combined_original):
        if re.search(r"\b(surge|jump|strengthen|gain)(?:s|ed|ing)?\b|円高|急伸", combined_original):
            require(
                any(row["target"] == "円" and row["direction"] == "bullish" for row in effects),
                f"{context} strengthening yen lacks a JPY-bullish effect",
            )
        elif re.search(r"\b(weaken|deprecat|fall|drop|plunge)(?:s|ed|ing)?\b|円安", combined_original):
            require(
                any(row["target"] == "円" and row["direction"] == "bearish" for row in effects),
                f"{context} weakening yen lacks a JPY-bearish effect",
            )


def validate_cluster_fields(
    item: dict[str, Any],
    context: str,
    retrieved: datetime,
) -> None:
    cluster_id = require_string(item["clusterId"], f"{context}.clusterId")
    require(
        re.fullmatch(r"cluster-[0-9a-f]{14}", cluster_id) is not None,
        f"{context}.clusterId is malformed",
    )
    cluster_size = require_int(
        item["clusterSize"], f"{context}.clusterSize", low=1
    )
    ranking_cluster_size = require_int(
        item["rankingClusterSize"], f"{context}.rankingClusterSize", low=1
    )
    require(
        ranking_cluster_size <= cluster_size,
        f"{context}.rankingClusterSize exceeds visible clusterSize",
    )
    independent_count = require_int(
        item["independentSourceCount"],
        f"{context}.independentSourceCount",
        low=1,
    )
    require(
        independent_count <= ranking_cluster_size,
        f"{context}.independentSourceCount exceeds rankingClusterSize",
    )
    state = require_string(
        item["corroborationState"], f"{context}.corroborationState"
    )
    require(
        state in {"single-source", "multi-source", "official-primary"},
        f"{context}.corroborationState is invalid",
    )
    if item["sourceKind"].startswith("official"):
        require(state == "official-primary", f"{context} official lead state mismatch")
    elif independent_count >= 2:
        require(state == "multi-source", f"{context} multi-source state mismatch")
    else:
        require(state == "single-source", f"{context} single-source state mismatch")

    origin_group = require_string(item["originGroup"], f"{context}.originGroup")
    require(len(origin_group) <= 100, f"{context}.originGroup is unexpectedly long")
    publisher_domain = require_string(
        item["publisherDomain"], f"{context}.publisherDomain"
    )
    require(
        "." in publisher_domain and not re.search(r"\s", publisher_domain),
        f"{context}.publisherDomain is malformed",
    )
    require_string(
        item["sourceCountry"], f"{context}.sourceCountry", allow_empty=True
    )
    require_string(item["discoveryProvider"], f"{context}.discoveryProvider")

    related = require_list(item["relatedLinks"], f"{context}.relatedLinks")
    require(len(related) <= 20, f"{context}.relatedLinks exceeds its display cap")
    require(
        cluster_size >= 1 + len(related),
        f"{context}.clusterSize is smaller than visible cluster members",
    )
    if cluster_size == 1:
        require(not related, f"{context} singleton cluster has related links")
        require(independent_count == 1, f"{context} singleton cluster has multiple origins")
    if ranking_cluster_size == 1:
        require(independent_count == 1, f"{context} singleton ranking cluster has multiple origins")
    ranking_visible_origins = {origin_group}
    ranking_related_count = 0
    related_urls = {normalize_url(item["url"])}
    for related_index, raw_related in enumerate(related):
        related_context = f"{context}.relatedLinks[{related_index}]"
        row = require_dict(raw_related, related_context)
        require_keys(
            row,
            {
                "title",
                "url",
                "source",
                "sourceKind",
                "publishedAtUtc",
                "originGroup",
                "verification",
                "rankingEvidence",
            },
            related_context,
        )
        require_string(row["title"], f"{related_context}.title")
        related_url = require_https_url(row["url"], f"{related_context}.url")
        normalized_url = normalize_url(related_url)
        require(
            normalized_url not in related_urls,
            f"{related_context}.url duplicates a cluster member",
        )
        related_urls.add(normalized_url)
        require_string(row["source"], f"{related_context}.source")
        require(
            row["sourceKind"] in SOURCE_KINDS,
            f"{related_context}.sourceKind is invalid",
        )
        if row["publishedAtUtc"] is not None:
            related_published = parse_timestamp(
                row["publishedAtUtc"],
                f"{related_context}.publishedAtUtc",
                expected_offset=timedelta(0),
            )
            require(
                related_published <= retrieved + timedelta(minutes=10),
                f"{related_context}.publishedAtUtc is after retrieval",
            )
        related_origin = require_string(
            row["originGroup"], f"{related_context}.originGroup"
        )
        require(
            isinstance(row["rankingEvidence"], bool),
            f"{related_context}.rankingEvidence must be boolean",
        )
        if row["rankingEvidence"]:
            ranking_related_count += 1
            ranking_visible_origins.add(related_origin)
        require(
            row["verification"] in VERIFICATION_VALUES,
            f"{related_context}.verification is invalid",
        )
    require(
        ranking_cluster_size >= 1 + ranking_related_count,
        f"{context}.rankingClusterSize is smaller than visible ranking evidence",
    )
    require(
        len(ranking_visible_origins) <= independent_count,
        f"{context}.independentSourceCount is below visible independent origins",
    )


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
    target_interval = require_int(
        policy["targetIntervalMinutes"],
        "refreshPolicy.targetIntervalMinutes",
        low=1,
        high=60,
    )
    require(
        target_interval == 5,
        "refreshPolicy.targetIntervalMinutes must match the five-minute workflow target",
    )
    for key in ("delivery", "buttonBehavior", "warning"):
        require_string(policy[key], f"refreshPolicy.{key}")
    require(
        "再読込" in policy["buttonBehavior"],
        "refreshPolicy.buttonBehavior must honestly describe snapshot reload",
    )
    require(
        "保証" in policy["warning"]
        and re.search(r"遅延|ずれ|超える", policy["warning"]),
        "refreshPolicy.warning must disclose that the five-minute target is not guaranteed",
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
            optional={
                "receivedCount",
                "acceptedCount",
                "newestEffectiveAtUtc",
                "newestDisclosureId",
                "lastViewerUpdateJst",
                "scannedPages",
                "scannedDates",
                "coverageVersion",
                "coverageComplete",
                "backfillFailedDates",
                "totalAvailableCount",
                "scanMode",
            },
        )
        metric_keys = {"receivedCount", "acceptedCount", "newestEffectiveAtUtc"}
        present_metrics = metric_keys.intersection(row)
        require(
            not present_metrics or present_metrics == metric_keys,
            f"{context} discovery counters must be supplied together",
        )
        name = require_string(row["name"], f"{context}.name")
        kind = require_string(row["kind"], f"{context}.kind")
        status = require_string(row["status"], f"{context}.status")
        require(status in SOURCE_STATUS_VALUES, f"{context}.status is invalid: {status}")
        if present_metrics:
            received = require_int(row["receivedCount"], f"{context}.receivedCount", low=0)
            accepted = require_int(row["acceptedCount"], f"{context}.acceptedCount", low=0)
            require(accepted <= received, f"{context}.acceptedCount exceeds receivedCount")
            newest = parse_nullable_utc_timestamp(
                row["newestEffectiveAtUtc"], f"{context}.newestEffectiveAtUtc"
            )
            if newest is not None:
                require(
                    newest <= generated + timedelta(minutes=10),
                    f"{context}.newestEffectiveAtUtc is after package generation",
                )
            if accepted == 0:
                require(newest is None, f"{context}.newestEffectiveAtUtc requires an accepted item")
                require(status == "limited", f"{context} zero accepted items must be limited")
                require(
                    row["message"] == "接続成功・該当新着0件",
                    f"{context} zero-new-item state is not clearly disclosed",
                )
        tdnet_metric_keys = {
            "newestDisclosureId",
            "lastViewerUpdateJst",
            "scannedPages",
            "scannedDates",
            "coverageVersion",
            "coverageComplete",
            "backfillFailedDates",
            "totalAvailableCount",
            "scanMode",
        }
        tdnet_metrics = tdnet_metric_keys.intersection(row)
        require(
            not tdnet_metrics or tdnet_metrics == tdnet_metric_keys,
            f"{context} TDnet scan metrics must be supplied together",
        )
        if tdnet_metrics:
            require(
                kind == "company-disclosure",
                f"{context} TDnet scan metrics require company-disclosure kind",
            )
            require_string(
                row["newestDisclosureId"],
                f"{context}.newestDisclosureId",
                allow_empty=True,
            )
            if row["lastViewerUpdateJst"]:
                parse_timestamp(
                    row["lastViewerUpdateJst"],
                    f"{context}.lastViewerUpdateJst",
                    expected_offset=timedelta(hours=9),
                )
            scanned_dates = require_int(
                row["scannedDates"], f"{context}.scannedDates", low=1, high=3
            )
            coverage_version = require_int(
                row["coverageVersion"], f"{context}.coverageVersion", low=1
            )
            require(
                coverage_version == 2, f"{context}.coverageVersion is unsupported"
            )
            coverage_complete = row["coverageComplete"]
            require(
                isinstance(coverage_complete, bool),
                f"{context}.coverageComplete must be boolean",
            )
            backfill_failed_dates = require_int(
                row["backfillFailedDates"],
                f"{context}.backfillFailedDates", low=0, high=2,
            )
            scanned_pages = require_int(
                row["scannedPages"], f"{context}.scannedPages", low=1, high=60
            )
            total_available = require_int(
                row["totalAvailableCount"],
                f"{context}.totalAvailableCount",
                low=0,
            )
            require(
                scanned_dates <= scanned_pages <= scanned_dates * 20
                and total_available >= 0,
                f"{context} TDnet metrics invalid",
            )
            require(
                not coverage_complete or backfill_failed_dates == 0,
                f"{context} complete TDnet coverage cannot include failed dates",
            )
            require(row["scanMode"] in DISCLOSURE_SCAN_MODES, f"{context}.scanMode is invalid")
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
    extreme_direction: str = "down",
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
            (
                start_value - end_value
                if extreme_direction == "down"
                else end_value - start_value
            )
            if minutes is None
            else end_value - start_value
        )
        expected_pct = (
            (
                (start_value - end_value) / start_value * 100
                if extreme_direction == "down"
                else (end_value - start_value) / start_value * 100
            )
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
            "quoteDate",
            "previousCloseDate",
            "referenceKind",
            "referenceLabel",
            "referenceSourceUrl",
            "referenceValidationStatus",
            "rawMetaPreviousClose",
            "metaReferenceDifferencePct",
            "referenceError",
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
            "troughToPeak",
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
    reference_status = require_string(
        quote["referenceValidationStatus"],
        f"{context}.referenceValidationStatus",
    )
    require(
        reference_status in {"verified", "unavailable"},
        f"{context}.referenceValidationStatus is invalid",
    )
    reference_kind = require_string(quote["referenceKind"], f"{context}.referenceKind")
    require_string(quote["referenceLabel"], f"{context}.referenceLabel")
    quote_date_text = require_string(quote["quoteDate"], f"{context}.quoteDate")
    try:
        quote_market_date = date.fromisoformat(quote_date_text)
    except ValueError as exc:
        raise ValidationError(f"{context}.quoteDate must be YYYY-MM-DD") from exc
    raw_meta_previous = number(
        quote["rawMetaPreviousClose"],
        f"{context}.rawMetaPreviousClose",
        nullable=True,
    )
    meta_difference = number(
        quote["metaReferenceDifferencePct"],
        f"{context}.metaReferenceDifferencePct",
        nullable=True,
    )
    require(
        quote["referenceError"] is None or isinstance(quote["referenceError"], str),
        f"{context}.referenceError must be a string or null",
    )
    if reference_status == "verified":
        previous_date_text = require_string(
            quote["previousCloseDate"], f"{context}.previousCloseDate"
        )
        try:
            previous_market_date = date.fromisoformat(previous_date_text)
        except ValueError as exc:
            raise ValidationError(
                f"{context}.previousCloseDate must be YYYY-MM-DD"
            ) from exc
        require(
            previous_market_date < quote_market_date,
            f"{context}.previousCloseDate must precede quoteDate",
        )
        require(
            previous is not None and change is not None and change_points is not None,
            f"{context} verified reference must include a directional calculation",
        )
        require(
            reference_kind != "unavailable",
            f"{context}.referenceKind cannot be unavailable when verified",
        )
        reference_hosts = (
            {"indexes.nikkei.co.jp"}
            if key == "NIKKEI_CASH"
            else {"finance.yahoo.com"}
        )
        require_https_url(
            quote["referenceSourceUrl"],
            f"{context}.referenceSourceUrl",
            hosts=reference_hosts,
        )
        if raw_meta_previous is not None:
            require(
                close_enough(meta_difference, pct_change(raw_meta_previous, previous)),
                f"{context}.metaReferenceDifferencePct identity failed",
            )
    else:
        require(
            previous is None and change is None and change_points is None,
            f"{context} unavailable reference must not publish a directional calculation",
        )
        require(
            quote["previousCloseDate"] is None and quote["referenceSourceUrl"] is None,
            f"{context} unavailable reference must not claim a dated source",
        )
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
    require(quote_utc <= generated + timedelta(minutes=2), f"{context} quote is future-dated")
    require(generated - quote_utc <= timedelta(days=5), f"{context} quote is older than five days")
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
    source_hosts = (
        {"indexes.nikkei.co.jp"} if key == "NIKKEI_CASH" else {"finance.yahoo.com"}
    )
    require_https_url(quote["sourceUrl"], f"{context}.sourceUrl", hosts=source_hosts)

    spark = require_list(quote["sparkline"], f"{context}.sparkline")
    require(1 <= len(spark) <= 168, f"{context}.sparkline must contain 1..168 points")
    spark_by_time: dict[str, float] = {}
    first_time: datetime | None = None
    previous_time: datetime | None = None
    for index, raw_point in enumerate(spark):
        point_context = f"{context}.sparkline[{index}]"
        point = require_dict(raw_point, point_context)
        require_keys(point, {"timeUtc", "value"}, point_context)
        point_time = parse_timestamp(
            point["timeUtc"], f"{point_context}.timeUtc", expected_offset=timedelta(0)
        )
        if first_time is None:
            first_time = point_time
        point_value = number(point["value"], f"{point_context}.value")
        require(point_value > 0, f"{point_context}.value must be positive")
        if previous_time is not None:
            require(point_time > previous_time, f"{context}.sparkline times must be strictly increasing")
        previous_time = point_time
        require(point["timeUtc"] not in spark_by_time, f"{context}.sparkline has duplicate times")
        spark_by_time[point["timeUtc"]] = point_value
    if first_time is not None and previous_time is not None and len(spark) >= 2:
        require(
            previous_time - first_time >= timedelta(hours=96),
            f"{context}.sparkline must cover the latest trading week",
        )
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
    validate_move(
        quote["troughToPeak"],
        f"{context}.troughToPeak",
        minutes=None,
        generated=generated,
        spark_by_time=spark_by_time,
        extreme_direction="up",
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
            "displayQuoteKeys",
            "marketSummaryOverlayKeys",
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
    display_quote_keys = require_list(premarket["displayQuoteKeys"], "premarket.displayQuoteKeys")
    overlay_quote_keys = require_list(premarket["marketSummaryOverlayKeys"], "premarket.marketSummaryOverlayKeys")
    require(tuple(display_quote_keys) == PREMARKET_DISPLAY_KEYS, "pre-market display keys must remain the nine strategy series")
    require(tuple(overlay_quote_keys) == MARKET_SUMMARY_OVERLAY_KEYS, "market-summary overlay keys changed")
    require(not set(display_quote_keys).intersection(overlay_quote_keys), "pre-market display and market-summary overlay keys must remain separate")
    require(set(display_quote_keys).issubset(EXPECTED_INSTRUMENTS), "pre-market display key is not configured")
    require(set(overlay_quote_keys).issubset(EXPECTED_INSTRUMENTS), "market-summary overlay key is not configured")
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
        move = require_dict(shock[key], f"marketShock.{key}")
        if move.get("startUtc") is None or move.get("endUtc") is None:
            continue
        start = parse_timestamp(
            move["startUtc"], f"marketShock.{key}.startUtc", expected_offset=timedelta(0)
        )
        end = parse_timestamp(
            move["endUtc"], f"marketShock.{key}.endUtc", expected_offset=timedelta(0)
        )
        signed_pct = number(
            move.get("pct"), f"marketShock.{key}.pct", nullable=True
        )
        if key.startswith("move"):
            if direction == "yen-strengthening" and (signed_pct or 0.0) >= 0:
                continue
            if direction == "yen-weakening" and (signed_pct or 0.0) <= 0:
                continue
        score = (
            abs(signed_pct or 0.0),
            abs(number(move.get("points"), f"marketShock.{key}.points", nullable=True) or 0.0),
        )
        candidates.append((score, start, end))
    reference_text = shock.get("observedAtUtc") or shock.get("checkedAtUtc")
    reference = (
        parse_timestamp(reference_text, "marketShock event reference")
        if reference_text is not None
        else None
    )
    if reference is not None:
        recent = [
            candidate
            for candidate in candidates
            if -300 <= (reference - candidate[2]).total_seconds() <= 180 * 60
        ]
        if recent:
            candidates = recent
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
            "shockDirection",
            "directionMetrics",
            "recentDirectionalShock",
            "directionalShockEventEndUtc",
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
            "troughToPeak",
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
        "troughToPeak": "troughToPeak",
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
    trough_pct = number(
        require_dict(shock["troughToPeak"], "marketShock.troughToPeak").get("pct"),
        "marketShock.troughToPeak.pct",
        nullable=True,
    )
    move_pcts = [
        number(
            require_dict(shock[key], f"marketShock.{key}").get("pct"),
            f"marketShock.{key}.pct",
            nullable=True,
        )
        for key in ("move5m", "move15m", "move30m")
    ]
    peak_points = number(
        shock["peakToTrough"].get("points"),
        "marketShock.peakToTrough.points",
        nullable=True,
    )
    trough_points = number(
        shock["troughToPeak"].get("points"),
        "marketShock.troughToPeak.points",
        nullable=True,
    )
    move30_points = number(
        shock["move30m"].get("points"), "marketShock.move30m.points", nullable=True
    )
    signed_moves = [value for value in [day_change, *move_pcts] if value is not None]
    strengthening_score = max(
        [max(0.0, peak_pct or 0.0)]
        + [abs(value) for value in signed_moves if value < 0]
    )
    weakening_score = max(
        [max(0.0, trough_pct or 0.0)]
        + [value for value in signed_moves if value > 0]
    )
    if not fx:
        expected_direction = "unknown"
    elif strengthening_score > weakening_score + 1e-9:
        expected_direction = "yen-strengthening"
    elif weakening_score > strengthening_score + 1e-9:
        expected_direction = "yen-weakening"
    else:
        expected_direction = "mixed"
    magnitude = max(
        abs(day_change or 0),
        abs(range_pct or 0),
        abs(peak_pct or 0),
        abs(trough_pct or 0),
        *(abs(value or 0) for value in move_pcts),
    )
    directional_points = max(
        abs(peak_points or 0),
        abs(trough_points or 0),
    )
    if magnitude >= 2 or directional_points >= 3:
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

    shock_direction = require_string(
        shock["shockDirection"], "marketShock.shockDirection"
    )
    require(
        shock_direction
        in {"yen-strengthening", "yen-weakening", "mixed", "unknown"},
        "marketShock.shockDirection is invalid",
    )
    require(
        shock_direction == expected_direction,
        "marketShock.shockDirection formula failed",
    )
    metrics = require_dict(shock["directionMetrics"], "marketShock.directionMetrics")
    require_keys(
        metrics,
        {"yenStrengtheningScorePct", "yenWeakeningScorePct"},
        "marketShock.directionMetrics",
    )
    actual_strengthening = number(
        metrics["yenStrengtheningScorePct"],
        "marketShock.directionMetrics.yenStrengtheningScorePct",
    )
    actual_weakening = number(
        metrics["yenWeakeningScorePct"],
        "marketShock.directionMetrics.yenWeakeningScorePct",
    )
    require(
        close_enough(actual_strengthening, round(strengthening_score, 4)),
        "marketShock yen-strengthening score mismatch",
    )
    require(
        close_enough(actual_weakening, round(weakening_score, 4)),
        "marketShock yen-weakening score mismatch",
    )

    event_start, event_end = expected_intervention_event_window(shock)
    require(
        isinstance(shock["recentDirectionalShock"], bool),
        "marketShock.recentDirectionalShock must be boolean",
    )
    if event_end is None:
        require(
            shock["directionalShockEventEndUtc"] is None,
            "marketShock directional event end exists without an event",
        )
        expected_recent_directional = False
    else:
        directional_end = parse_timestamp(
            shock["directionalShockEventEndUtc"],
            "marketShock.directionalShockEventEndUtc",
            expected_offset=timedelta(0),
        )
        require(
            same_instant(directional_end, event_end),
            "marketShock.directionalShockEventEndUtc differs from event window",
        )
        reference = (
            parse_timestamp(shock["observedAtUtc"], "marketShock.observedAtUtc")
            if shock["observedAtUtc"] is not None
            else checked
        )
        lag_seconds = (reference - event_end).total_seconds()
        expected_recent_directional = -300 <= lag_seconds <= 180 * 60
    require(
        shock["recentDirectionalShock"] is expected_recent_directional,
        "marketShock.recentDirectionalShock formula failed",
    )
    evidence_rows, evidence_count = validate_evidence(
        shock["reportedEvidence"],
        shock["reportedEvidenceCount"],
        event_start,
        event_end,
        briefing_items,
    )
    if expected_severity in {"critical", "warning"}:
        if shock_direction == "yen-strengthening":
            expected_interventions = {
                "reported-unconfirmed" if evidence_count else "price-shock-only"
            }
        elif shock_direction == "yen-weakening":
            expected_interventions = {"yen-weakening-shock"}
        else:
            expected_interventions = {
                "direction-unclear-shock",
                "price-shock-only",
            }
    elif expected_severity == "normal":
        expected_interventions = {"no-shock-observed"}
    else:
        expected_interventions = {"unknown"}
    require(
        shock["interventionStatus"] in expected_interventions,
        "marketShock.interventionStatus does not follow evidence state",
    )
    expected_intervention = shock["interventionStatus"]
    if shock_direction != "yen-strengthening":
        require(not evidence_rows, "non-strengthening USDJPY move retained intervention evidence")
    if not expected_recent_directional:
        require(
            not evidence_rows and expected_intervention != "reported-unconfirmed",
            "stale directional shock was promoted by current intervention reporting",
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
        "介入認定条件ではない" in shock["assessmentRule"]
        or "閾値だけでは介入認定しない" in shock["assessmentRule"],
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
        and shock_direction == "yen-strengthening"
        and expected_recent_directional
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
        not evidence_rows
        or (
            expected_severity in {"critical", "warning"}
            and shock_direction == "yen-strengthening"
            and expected_recent_directional
        ),
        "intervention evidence must require a recent yen-strengthening shock",
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
            "relatedLinks",
            "corroborationState",
            "originGroup",
            "publisherDomain",
            "sourceCountry",
            "discoveryProvider",
        },
        context,
        optional={
            "carriedForward",
            "staleReason",
            "disclosureId",
            "issuerCode",
            "issuerName",
            "disclosureCategory",
            "materialityScore",
            "issuerNewsMentionCount",
            "issuerIndependentNewsSourceCount",
            "issuerBuzzScore",
        },
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
        require_https_url(
            url,
            f"{context}.url",
            hosts=OFFICIAL_SOURCE_HOSTS[source_kind],
        )
        disclosure_keys = {
            "disclosureId",
            "issuerCode",
            "issuerName",
            "disclosureCategory",
            "materialityScore",
            "issuerNewsMentionCount",
            "issuerIndependentNewsSourceCount",
            "issuerBuzzScore",
        }
        present_disclosure_keys = disclosure_keys.intersection(item)
        require(
            not present_disclosure_keys
            or present_disclosure_keys == disclosure_keys,
            f"{context} disclosure metadata must be supplied together",
        )
        if present_disclosure_keys:
            disclosure_id = require_string(
                item["disclosureId"], f"{context}.disclosureId"
            )
            require(
                re.fullmatch(r"[0-9A-Za-z_-]{8,80}", disclosure_id) is not None,
                f"{context}.disclosureId is malformed",
            )
            issuer_code = require_string(
                item["issuerCode"], f"{context}.issuerCode"
            )
            require(
                re.fullmatch(r"[0-9A-Z]{4,6}", issuer_code) is not None,
                f"{context}.issuerCode is malformed",
            )
            require_string(item["issuerName"], f"{context}.issuerName")
            require(
                item["disclosureCategory"] in DISCLOSURE_CATEGORIES,
                f"{context}.disclosureCategory is invalid",
            )
            require_int(
                item["materialityScore"],
                f"{context}.materialityScore",
                low=0,
                high=100,
            )
            require_int(
                item["issuerNewsMentionCount"],
                f"{context}.issuerNewsMentionCount",
                low=0,
                high=10000,
            )
            require_int(
                item["issuerIndependentNewsSourceCount"],
                f"{context}.issuerIndependentNewsSourceCount",
                low=0,
                high=10000,
            )
            require_int(
                item["issuerBuzzScore"],
                f"{context}.issuerBuzzScore",
                low=0,
                high=12,
            )
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

    published = parse_nullable_utc_timestamp(
        item["publishedAtUtc"], f"{context}.publishedAtUtc"
    )
    retrieved = parse_timestamp(
        item["retrievedAtUtc"], f"{context}.retrievedAtUtc", expected_offset=timedelta(0)
    )
    indexed = parse_nullable_utc_timestamp(item["indexedAtUtc"], f"{context}.indexedAtUtc")
    effective_for_age = published or indexed
    require(effective_for_age is not None, f"{context} lacks an effective timestamp")
    require(effective_for_age <= retrieved + timedelta(minutes=10), f"{context} is future-published")
    require(retrieved <= generated + timedelta(minutes=2), f"{context} retrieval is after generation")
    require(generated - effective_for_age <= timedelta(days=7), f"{context} is older than seven days")
    expected_age = round(max(0.0, (retrieved - effective_for_age).total_seconds() / 3600.0), 2)
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
    validate_localized_fields(
        item,
        context,
        generated,
        published,
        retrieved,
        carried,
    )
    validate_cluster_fields(item, context, retrieved)
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
        recency_component = max(0, 30 - min(72, age) / 3)
        independent_sources = item["independentSourceCount"]
        ranking_cluster_size = item["rankingClusterSize"]
        expected_talk_score = min(
            100,
            round(
                12
                + min(30, independent_sources * 12)
                + min(12, math.log2(ranking_cluster_size + 1) * 4)
                + min(20, math.log10(engagement_total + 1) * 8)
                + recency_component
            ),
        )
        require(
            talk_score == expected_talk_score,
            f"{context}.talkScore does not match the documented cluster-aware formula",
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
        "official": ("official-us", "official-japan", "company-disclosure"),
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


def validate_translation_status(
    raw: Any,
    items: list[dict[str, Any]],
) -> None:
    context = "briefing.translationStatus"
    status = require_dict(raw, context)
    require_keys(
        status,
        {"status", "label", "translatedItems", "cachedItems"},
        context,
        optional={"message", "rejectedItems", "requestedTexts"},
    )
    state = require_string(status["status"], f"{context}.status")
    require(
        state
        in {
            "not-configured",
            "cache-only",
            "no-candidates",
            "failed",
            "ok",
            "limited",
        },
        f"{context}.status is invalid: {state}",
    )
    label = require_string(status["label"], f"{context}.label")
    translated = require_int(
        status["translatedItems"], f"{context}.translatedItems", low=0
    )
    cached = require_int(status["cachedItems"], f"{context}.cachedItems", low=0)
    if "message" in status:
        require_string(status["message"], f"{context}.message")
    rejected = (
        require_int(status["rejectedItems"], f"{context}.rejectedItems", low=0)
        if "rejectedItems" in status
        else 0
    )
    requested = (
        require_int(status["requestedTexts"], f"{context}.requestedTexts", low=0)
        if "requestedTexts" in status
        else 0
    )
    deepl_items = sum(
        1 for item in items if (item.get("japanese") or {}).get("mode") == "deepl"
    )
    require(
        deepl_items == translated + cached,
        f"{context} counts do not match published DeepL items",
    )
    if state in {"not-configured", "cache-only", "no-candidates", "failed"}:
        require(translated == 0, f"{context} non-success state translated items")
    if state == "not-configured":
        require(cached == 0, f"{context} not-configured state has cached items")
        require("未設定" in label, f"{context} does not disclose missing configuration")
    if state == "cache-only":
        require(cached > 0, f"{context} cache-only state has no cached items")
    if state in {"ok", "limited"}:
        require(requested > 0, f"{context} API result lacks requestedTexts")
    if state == "limited":
        require(rejected > 0, f"{context} limited state lacks rejectedItems")
    serialized = json.dumps(status, ensure_ascii=False).casefold()
    require(
        not any(token in serialized for token in ("deepl-auth-key", "authorization", ":fx")),
        f"{context} may expose authentication material",
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
            "translationStatus",
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
    validate_translation_status(briefing["translationStatus"], items)
    live_news = [
        item
        for item in items
        if item["sourceKind"]
        in {"official-us", "official-japan", "official-company", "news", "news-wire"}
        and item["freshness"]["bucket"] in {"breaking", "developing", "today"}
        and not item.get("carriedForward")
    ]
    latest_market_news = [
        item for item in live_news
        if item["sourceKind"] != "official-company"
    ]
    market_times = [
        parse_timestamp(
            item["effectivePublishedAtUtc"],
            f"briefing latest-market item {item['id']}.effectivePublishedAtUtc",
            expected_offset=timedelta(0),
        )
        for item in latest_market_news
    ]
    require(
        all(
            market_times[index] >= market_times[index + 1]
            for index in range(len(market_times) - 1)
        ),
        "briefing latest-market lane is not in descending publication order",
    )
    company_items = [
        item for item in items
        if item["sourceKind"] == "official-company"
    ]
    require(
        len(company_items) <= 6,
        "briefing company-disclosure reservation exceeds six cards",
    )
    company_issuer_counts = Counter(
        str(item.get("issuerCode") or "") for item in company_items
    )
    require(
        all(issuer_code and count <= 3 for issuer_code, count in company_issuer_counts.items()),
        "briefing company-disclosure issuer cap exceeds three cards",
    )
    for item in company_items:
        if "materialityScore" in item:
            require(
                item["disclosureCategory"] in DISCLOSURE_CATEGORIES
                and item["materialityScore"] >= 0,
                "briefing company disclosure lacks generic importance metadata",
            )
    non_carried = [item for item in items if not item.get("carriedForward")]
    non_carried_times = [
        parse_timestamp(
            item["effectivePublishedAtUtc"],
            f"briefing current item {item['id']}.effectivePublishedAtUtc",
            expected_offset=timedelta(0),
        )
        for item in non_carried
    ]
    require(
        all(
            non_carried_times[index] >= non_carried_times[index + 1]
            for index in range(len(non_carried_times) - 1)
        ),
        "briefing current items are not in descending publication order",
    )
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
            "shockDirection",
            "recentDirectionalShock",
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
        ("shockDirection", "shockDirection"),
        ("recentDirectionalShock", "recentDirectionalShock"),
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

    weakening_quote = json.loads(json.dumps(quote))
    weakening_quote.update({
        "value": 165.0,
        "previousClose": 161.0,
        "changePct": pct_change(165.0, 161.0),
        "sessionHigh": 165.2,
        "sessionLow": 160.8,
        "sessionRangePct": pct_change(165.2, 160.8),
    })
    for key, points, percent in (
        ("move5m", 1.8, 1.11),
        ("move15m", 2.5, 1.54),
        ("move30m", 4.0, 2.48),
    ):
        weakening_quote[key]["points"] = points
        weakening_quote[key]["pct"] = percent
    weakening_quote["peakToTrough"].update({
        "points": 0.0,
        "pct": 0.0,
        "startUtc": "2026-07-30T14:00:00+00:00",
        "endUtc": "2026-07-30T14:00:00+00:00",
    })
    weakening_shock = producer.build_market_shock(
        {"USDJPY": weakening_quote},
        now,
    )
    require(
        weakening_shock["severity"] == "critical"
        and weakening_shock["shockDirection"] == "yen-weakening",
        "yen-weakening regression fixture was not classified as a critical opposite-direction move",
    )
    require(
        weakening_shock["interventionStatus"] == "yen-weakening-shock",
        "yen weakening was presented as observed yen-buying intervention",
    )
    producer.update_intervention_assessment(weakening_shock, [news_item])
    require(
        weakening_shock["interventionStatus"] == "yen-weakening-shock"
        and weakening_shock["reportedEvidenceCount"] == 0
        and weakening_shock["officiallyConfirmed"] is False,
        "intervention reporting promoted an opposite-direction yen-weakening shock",
    )
    require(
        "円買い介入判定対象外" in weakening_shock["interventionLabel"],
        "yen-weakening shock does not explain the intervention-direction boundary",
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

    stale_now = datetime(2026, 8, 5, 14, 30, tzinfo=timezone.utc)
    stale_extreme_quote = json.loads(json.dumps(quote))
    stale_extreme_quote.update({
        "value": 160.0,
        "previousClose": 160.0,
        "changePct": 0.0,
        "sessionHigh": 161.0,
        "sessionLow": 157.0,
        "sessionRangePct": pct_change(161.0, 157.0),
        "quoteTimeUtc": stale_now.isoformat(),
        "quoteTimeJst": stale_now.astimezone(JST).isoformat(),
    })
    for key, minutes in (("move5m", 5), ("move15m", 15), ("move30m", 30)):
        stale_extreme_quote[key].update({
            "points": 0.0,
            "pct": 0.0,
            "startUtc": (stale_now - timedelta(minutes=minutes)).isoformat(),
            "endUtc": stale_now.isoformat(),
        })
    stale_extreme_quote["peakToTrough"].update({
        "points": 4.0,
        "pct": 2.5,
        "startUtc": "2026-08-04T13:00:00+00:00",
        "endUtc": "2026-08-04T13:30:00+00:00",
    })
    stale_shock = producer.build_market_shock(
        {"USDJPY": stale_extreme_quote},
        stale_now,
    )
    stale_news = {
        "id": "live-stale-extreme-news",
        "title": "Traders suspected intervention during the prior yen move",
        "summary": "The report concerned the prior session.",
        "url": "https://example.com/prior-intervention-report",
        "source": "Example News",
        "sourceKind": "news",
        "verification": "reported-unconfirmed",
        "publishedAtUtc": "2026-08-04T13:35:00+00:00",
    }
    producer.update_intervention_assessment(stale_shock, [stale_news])
    require(
        stale_shock["severity"] == "critical"
        and stale_shock["shockDirection"] == "yen-strengthening",
        "stale-extrema fixture did not retain its historical price direction",
    )
    require(
        stale_shock["recentDirectionalShock"] is False,
        "more-than-180-minute-old extrema was labelled as a current shock",
    )
    require(
        stale_shock["interventionStatus"] == "price-shock-only"
        and stale_shock["reportedEvidenceCount"] == 0,
        "historical extrema was promoted by a matching old intervention report",
    )
    require(
        "eventId" not in stale_shock
        and "officialDisclosureSchedule" not in stale_shock,
        "historical extrema received current-event disclosure metadata",
    )




def run_quote_reference_regressions() -> None:
    """Prevent a Yahoo intraday metadata value from driving a displayed sign."""

    try:
        import live_intelligence as producer
    except ImportError as exc:
        raise ValidationError("unable to import scripts/live_intelligence.py") from exc

    def verified(
        key: str,
        current: float,
        previous: float,
        raw_meta: float,
        quote_day: str = "2026-07-31",
        previous_day: str = "2026-07-30",
    ) -> dict[str, Any]:
        return producer.build_quote_reference(
            key=key,
            current_value=current,
            quote_date=date.fromisoformat(quote_day),
            raw_meta_previous_close=raw_meta,
            daily_reference={
                "previousClose": previous,
                "previousCloseDate": previous_day,
                "referenceKind": "yahoo-daily-close",
                "referenceSourceUrl": "https://finance.yahoo.com/quote/test/history",
                "sourceUrl": "https://finance.yahoo.com/quote/test",
            },
        )

    nikkei = producer.build_quote_reference(
        key="NIKKEI_CASH",
        current_value=64299.390625,
        quote_date=date(2026, 7, 31),
        raw_meta_previous_close=67242.73,
        official_reference={
            "currentValue": 64362.02,
            "quoteDate": "2026-07-31",
            "previousClose": 61867.43,
            "previousCloseDate": "2026-07-30",
            "referenceKind": "official-nikkei-daily-close",
            "referenceSourceUrl": "https://indexes.nikkei.co.jp/en/nkave/archives/data?list=daily",
            "sourceUrl": "https://indexes.nikkei.co.jp/en/nkave/archives/data?list=daily",
        },
    )
    require(
        close_enough(nikkei["changePct"], 4.032153913618197, absolute=1e-9),
        "Nikkei official previous close regression failed",
    )
    require(
        nikkei["changePct"] > 0 and nikkei["rawMetaPreviousClose"] == 67242.73,
        "Nikkei metadata close changed the published direction",
    )

    kioxia = verified("KIOXIA", 39420.0, 38380.0, 67100.0, "2026-07-30", "2026-07-29")
    require(
        close_enough(kioxia["changePct"], 2.709744658676394, absolute=1e-9),
        "Kioxia daily previous close regression failed",
    )
    require(kioxia["changePct"] > 0, "Kioxia metadata close changed the published direction")

    for key, current, previous, raw_meta, expected_sign in (
        ("SP500_CASH", 7504.95, 7437.6298828125, 7515.34, 1),
        ("DXY", 99.907, 100.01, 100.73, -1),
        ("VIX", 16.08, 17.09, 16.50, -1),
        ("USDJPY", 157.40, 163.30, 162.429, -1),
        ("US10Y", 4.745, 4.663, 4.585, 1),
        ("SP500_FUTURES", 7000.0, 6971.0, 7039.0, 1),
    ):
        quote = verified(key, current, previous, raw_meta)
        require(
            quote["changePct"] * expected_sign > 0,
            f"{key} daily reference regression changed the expected sign",
        )
        require(
            quote["referenceValidationStatus"] == "verified",
            f"{key} reference is not marked verified",
        )

    unavailable = producer.build_quote_reference(
        key="ACWI_CASH",
        current_value=156.43,
        quote_date=date(2026, 7, 31),
        raw_meta_previous_close=155.94,
    )
    require(
        unavailable["changePct"] is None
        and unavailable["previousClose"] is None
        and unavailable["referenceValidationStatus"] == "unavailable",
        "unverified metadata close was published as a daily comparison",
    )
def run_localization_freshness_regressions() -> None:
    """Exercise bilingual fallbacks and freshness boundaries without network access."""

    try:
        import live_intelligence as producer
    except ImportError as exc:
        raise ValidationError("unable to import scripts/live_intelligence.py") from exc

    require(
        producer.original_excerpt(
            "Yen surges on intervention speculation - Reuters",
            "Yen surges on intervention speculation Reuters",
        )
        == "",
        "duplicate RSS title/description was retained as an excerpt",
    )
    now = datetime(2026, 7, 31, 0, 0, tzinfo=timezone.utc)
    original_title = "Yen surges on intervention speculation - Reuters"
    item = producer.build_item(
        title=original_title,
        summary="",
        url="https://example.com/yen-story",
        source="Reuters",
        source_kind="news-wire",
        published=(now - timedelta(minutes=12)).isoformat(),
        retrieved_at=now,
        topic_hint="fx-rates",
    )
    require(
        item["original"]["title"] == original_title,
        "English original headline was altered by localization",
    )
    require(
        item["japanese"]["mode"] == "structured-gist"
        and "翻訳ではありません" in item["japanese"]["label"],
        "no-key fallback is not honestly labelled as a structured gist",
    )
    require(
        has_japanese(item["japanese"]["title"] + item["japanese"]["summary"]),
        "no-key fallback did not produce a Japanese reading aid",
    )
    require(
        "これは翻訳ではなく" in item["japanese"]["summary"],
        "structured gist does not explain that it is not a translation",
    )
    require(
        re.search(
            r"(?:\b[A-Za-z][A-Za-z0-9&.'/-]*\b[\s:,-]*){4,}",
            item["japanese"]["title"],
        ) is None,
        "structured gist regressed to an English headline with word substitution",
    )
    require(
        item["japanese"]["sourceHash"]
        == expected_translation_source_hash(
            item["original"]["title"], item["original"]["excerpt"]
        ),
        "localization source hash regression failed",
    )

    editorial = producer.build_item(
        title="Federal Reserve issues FOMC statement",
        summary="FRBは政策金利を据え置きました。",
        url="https://www.federalreserve.gov/example",
        source="Federal Reserve",
        source_kind="official-us",
        published=(now - timedelta(hours=1)).isoformat(),
        retrieved_at=now,
        topic_hint="fx-rates",
    )
    require(
        editorial["japanese"]["mode"] == "editorial-summary",
        "existing Japanese editorial summary was not preserved",
    )
    require(
        editorial["original"]["excerpt"] == "",
        "Japanese editorial text leaked into the English original excerpt",
    )

    boundaries = (
        (30, "breaking", "30分以内"),
        (31, "developing", "3時間以内"),
        (180, "developing", "3時間以内"),
        (181, "today", "24時間以内"),
        (1440, "today", "24時間以内"),
        (1441, "context", "背景情報"),
    )
    for minutes, expected_bucket, expected_label in boundaries:
        freshness = producer.freshness_profile(
            now - timedelta(minutes=minutes),
            now,
            "minute",
        )
        require(
            (freshness["bucket"], freshness["label"], freshness["ageMinutes"])
            == (expected_bucket, expected_label, minutes),
            f"freshness boundary regression failed at {minutes} minutes",
        )
    date_only = producer.freshness_profile(now - timedelta(minutes=1), now, "date")
    require(
        (date_only["bucket"], date_only["label"]) == ("context", "日付のみ"),
        "date-only source was presented as breaking",
    )
    unknown = producer.freshness_profile(None, now, "unknown")
    require(
        (unknown["bucket"], unknown["label"], unknown["ageMinutes"])
        == ("unknown", "時刻未確認", None),
        "unknown source time received false freshness",
    )


def run_story_cluster_regressions() -> None:
    """Ensure syndicated copies do not masquerade as independent reporting."""

    try:
        import live_intelligence as producer
    except ImportError as exc:
        raise ValidationError("unable to import scripts/live_intelligence.py") from exc

    now = datetime(2026, 7, 31, 0, 0, tzinfo=timezone.utc)

    def story(source: str, url: str, suffix: str) -> dict[str, Any]:
        return producer.build_item(
            title=f"Yen surges on suspected intervention {suffix}".strip(),
            summary="",
            url=url,
            source=source,
            source_kind="news-wire" if source == "Reuters" else "news",
            published=(now - timedelta(minutes=10)).isoformat(),
            retrieved_at=now,
            topic_hint="fx-rates",
        )

    syndicated = producer.cluster_story_candidates([
        story("Reuters", "https://www.reuters.com/example/yen", "- Reuters"),
        story("Reuters", "https://www.investing.com/news/yen-copy", "Reuters"),
    ])
    require(len(syndicated) == 1, "syndicated Reuters copies were not clustered")
    reuters_cluster = syndicated[0]
    require(
        reuters_cluster["clusterSize"] == 2
        and reuters_cluster["independentSourceCount"] == 1
        and reuters_cluster["corroborationState"] == "single-source",
        "syndicated Reuters copies inflated independent-source corroboration",
    )
    require(
        len(reuters_cluster["relatedLinks"]) == 1,
        "syndicated Reuters related link was lost",
    )

    independently_reported = producer.cluster_story_candidates([
        story("Reuters", "https://www.reuters.com/example/yen", "- Reuters"),
        story("Reuters", "https://www.investing.com/news/yen-copy", "Reuters"),
        story(
            "Financial Times",
            "https://www.ft.com/content/example-yen",
            "- Financial Times",
        ),
    ])
    require(
        len(independently_reported) == 1,
        "closely matching independent report did not join the event cluster",
    )
    independent_cluster = independently_reported[0]
    require(
        independent_cluster["clusterSize"] == 3
        and independent_cluster["independentSourceCount"] == 2
        and independent_cluster["corroborationState"] == "multi-source",
        "independent outlet did not increase corroboration exactly once",
    )

    variant_report = producer.build_item(
        title="Yen Surge Spurs Speculation Japan Intervened in Market Again",
        summary="",
        url="https://www.bloomberg.com/example/yen-intervened",
        source="Bloomberg",
        source_kind="news",
        published=(now - timedelta(minutes=8)).isoformat(),
        retrieved_at=now,
        topic_hint="fx-rates",
    )
    variant_cluster = producer.cluster_story_candidates([
        story("Reuters", "https://www.reuters.com/example/yen", "- Reuters"),
        variant_report,
    ])
    require(
        len(variant_cluster) == 1,
        "materially different wording for the same yen-intervention event was not clustered",
    )
    require(
        variant_cluster[0]["clusterSize"] == 2
        and variant_cluster[0]["independentSourceCount"] == 2
        and len(variant_cluster[0]["relatedLinks"]) == 1,
        "event-key clustering lost source independence or the related original link",
    )

    different_event = producer.build_item(
        title="Federal Reserve holds rates after its policy meeting",
        summary="",
        url="https://www.federalreserve.gov/example/statement",
        source="Federal Reserve",
        source_kind="official-us",
        published=(now - timedelta(minutes=5)).isoformat(),
        retrieved_at=now,
        topic_hint="fx-rates",
    )
    require(
        len(producer.cluster_story_candidates([
            story("Reuters", "https://www.reuters.com/example/yen", "- Reuters"),
            different_event,
        ]))
        == 2,
        "unrelated stories were over-clustered",
    )


def _run_legacy_company_disclosure_regressions() -> None:
    """Keep timely company disclosures inside the primary-source contract."""

    try:
        import live_intelligence as producer
    except ImportError as exc:
        raise ValidationError("unable to import scripts/live_intelligence.py") from exc

    now = datetime(2026, 7, 31, 7, 0, tzinfo=timezone.utc)
    item = producer.build_item(
        title="キオクシアホールディングス 2026年3月期 決算短信",
        summary="会社がTDnetで決算資料を公表しました。",
        url="https://ssl4.eir-parts.net/doc/285A/tdnet/2859905/00.pdf",
        source="キオクシアホールディングス / TDnet",
        source_kind="official-company",
        published="2026-07-31T15:30:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
        timestamp_basis="tdnet-disclosure-time",
        timestamp_precision_value="minute",
        discovery_provider="tdnet-direct",
        source_country="JP",
    )
    ranked = producer.rank_briefing_items([item])
    require(
        len(ranked) == 1 and ranked[0]["sourceKind"] == "official-company",
        "official company disclosure was lost from briefing ranking",
    )
    validate_item(ranked[0], 0, now, Counter({"japan-stocks": 1}))

    company_feed = producer.COMPANY_DISCLOSURE_FEEDS[0]
    require(
        company_feed.get("statusKind") == "company-disclosure",
        "company disclosure source status is not separated from item sourceKind",
    )
    japanese_query = next(
        (
            query
            for query in producer.NEWS_QUERIES
            if query.get("name") == "キオクシア決算・適時開示"
        ),
        None,
    )
    require(
        japanese_query is not None
        and japanese_query.get("googleLocale")
        == {"hl": "ja", "gl": "JP", "ceid": "JP:ja"},
        "Kioxia breaking-news query is not using the Japanese news locale",
    )
    require(
        producer.normalize_url("http://example.com/story?utm_source=test")
        == "https://example.com/story",
        "legacy HTTP discovery URL was not safely upgraded and normalized",
    )

    disclosure_html = """
    <ul>
      <li><article>
        <a href="https://finance-frontend-pc-dist.west.edge.storage-yahoo.jp/disclosure/results.pdf">
          <h3>2026年3月期 第1四半期決算短信〔IFRS〕（連結）</h3>
          <time dateTime="2026-07-31T15:30:00+09:00">15:30</time>
        </a>
      </article></li>
      <li><article>
        <a href="https://finance-frontend-pc-dist.west.edge.storage-yahoo.jp/disclosure/split.pdf">
          <h3>株式分割及び定款の一部変更に関するお知らせ</h3>
          <time dateTime="2026-07-31T15:30:00+09:00">15:30</time>
        </a>
      </article></li>
      <li><article>
        <a href="https://finance-frontend-pc-dist.west.edge.storage-yahoo.jp/disclosure/buyback.pdf">
          <h3>自己株式取得に係る事項の決定に関するお知らせ</h3>
          <time dateTime="2026-07-31T15:30:00+09:00">15:30</time>
        </a>
      </article></li>
    </ul>
    """.encode("utf-8")
    original_request = producer.request
    producer.request = lambda *_args, **_kwargs: (
        disclosure_html,
        company_feed["url"],
    )
    try:
        parsed_items, source_status = producer.fetch_company_disclosures(
            company_feed,
            now,
        )
    finally:
        producer.request = original_request
    require(
        len(parsed_items) == 3
        and source_status["kind"] == "company-disclosure"
        and source_status["acceptedCount"] == 3,
        "TDnet-backed company disclosure parser lost a timed filing",
    )

    reported_results = producer.build_item(
        title="キオクシア、第1四半期決算を発表",
        summary="決算速報です。",
        url="https://example.com/kioxia-results",
        source="Example News",
        source_kind="news",
        published="2026-07-31T15:32:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
    )
    clustered = producer.cluster_story_candidates(
        parsed_items + [reported_results]
    )
    require(
        len(clustered) == 3,
        "Kioxia results, stock split, and buyback were not kept as three events",
    )
    result_cluster = next(
        (
            row
            for row in clustered
            if producer.event_signature(row) == "kioxia-results"
        ),
        None,
    )
    require(
        result_cluster is not None
        and result_cluster["sourceKind"] == "official-company"
        and result_cluster["clusterSize"] == 2
        and result_cluster["independentSourceCount"] == 2,
        "Kioxia result coverage was not clustered with independent-source evidence",
    )
    compensation_item = producer.build_item(
        title="勤務継続型株式報酬制度及び業績連動型株式報酬制度のお知らせ",
        summary="",
        url="https://ssl4.eir-parts.net/doc/285A/tdnet/compensation/00.pdf",
        source="キオクシアホールディングス / TDnet",
        source_kind="official-company",
        published="2026-07-31T15:30:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
    )
    require(
        producer.event_signature(compensation_item) == "",
        "performance-linked compensation was misclassified as financial results",
    )

    try:
        require_https_url(
            "https://example.com/not-an-official-disclosure",
            "company disclosure regression",
            hosts=OFFICIAL_SOURCE_HOSTS["official-company"],
        )
    except ValidationError:
        pass
    else:
        raise ValidationError(
            "unapproved host was accepted as an official company disclosure"
        )


def run_company_disclosure_regressions() -> None:
    """Prove material disclosures are issuer-agnostic and survive selection."""

    try:
        import live_intelligence as producer
    except ImportError as exc:
        raise ValidationError("unable to import scripts/live_intelligence.py") from exc

    production_config = json.dumps(
        {
            "feeds": producer.COMPANY_DISCLOSURE_FEEDS,
            "queries": producer.NEWS_QUERIES,
        },
        ensure_ascii=False,
        default=list,
    ).casefold()
    require(
        all(
            token not in production_config
            for token in ("キオクシア", "kioxia", "285a")
        ),
        "production disclosure discovery still depends on one issuer",
    )
    company_feed = producer.COMPANY_DISCLOSURE_FEEDS[0]
    require(
        company_feed["url"]
        == "https://www.release.tdnet.info/inbs/I_main_00.html"
        and company_feed.get("statusKind") == "company-disclosure",
        "company discovery is not rooted in the all-issuer TDnet viewer",
    )
    japanese_query = next(
        (
            query for query in producer.NEWS_QUERIES
            if query.get("name") == "日本株・決算サプライズ"
        ),
        None,
    )
    require(
        japanese_query is not None
        and japanese_query.get("googleLocale")
        == {"hl": "ja", "gl": "JP", "ceid": "JP:ja"}
        and set(japanese_query.get("providers") or ()) == {"google", "bing"},
        "generic Japanese earnings discovery lacks dual-provider locale coverage",
    )
    require(
        producer.reporting_origin_group(
            "Reuters", "https://news.google.com/rss/articles/example"
        ) == "reuters"
        and producer.reporting_origin_group(
            "日本経済新聞", "https://news.google.com/rss/articles/example"
        ) == producer.normalized_comparison_text("日本経済新聞"),
        "news aggregator domain replaced the actual publisher identity",
    )

    now = datetime(2026, 7, 31, 7, 0, tzinfo=timezone.utc)
    main_html = """
    <select id="day-selector">
      <option value="I_list_001_20260731.html">2026/07/31</option>
    </select>
    <div>最終更新日時：2026年07月31日 16:00</div>
    """.encode("utf-8")

    def tdnet_row(
        time_text: str,
        code: str,
        company: str,
        document_id: str,
        title: str,
    ) -> str:
        return f"""
        <tr>
          <td class="oddnew-L kjTime">{time_text}</td>
          <td class="oddnew-M kjCode">{code}</td>
          <td class="oddnew-M kjName">{company}</td>
          <td class="oddnew-M kjTitle">
            <a href="{document_id}.pdf">{title}</a>
          </td>
          <td class="oddnew-M kjXbrl"></td>
          <td class="oddnew-M kjPlace">東</td>
          <td class="oddnew-R kjHistroy"></td>
        </tr>
        """

    page_one_html = (
        """
        <div>1～4件 / 全5件</div>
        <div onclick="pagerLink('I_list_001_20260731.html')">1</div>
        """
        + tdnet_row(
            "15:30",
            "99990",
            "未知テックＨＤ",
            "140120260731900001",
            "2027年3月期 第1四半期決算短信〔日本基準〕（連結）",
        )
        + tdnet_row(
            "15:30",
            "99990",
            "未知テックＨＤ",
            "140120260731900002",
            "自己株式の取得枠設定に関するお知らせ",
        )
        + tdnet_row(
            "15:30",
            "99990",
            "未知テックＨＤ",
            "140120260731900003",
            "株式分割に関するお知らせ",
        )
        + tdnet_row(
            "15:30",
            "99990",
            "未知テックＨＤ",
            "140120260731900004",
            "業績連動型株式報酬制度のユニット付与に関するお知らせ",
        )
    ).encode("utf-8")
    page_two_html = (
        """
        <div>5～5件 / 全5件</div>
        <div onclick="pagerLink('I_list_001_20260731.html')">1</div>
        <div onclick="pagerLink('I_list_002_20260731.html')">2</div>
        """
        + tdnet_row(
            "15:00",
            "88880",
            "全国産業",
            "140120260731900005",
            "通期業績予想の上方修正に関するお知らせ",
        )
    ).encode("utf-8")

    previous_day_html = (
        """
        <div>1～1件 / 全1件</div>
        <div onclick="pagerLink('I_list_001_20260730.html')">1</div>
        """
        + tdnet_row(
            "18:00",
            "55550",
            "Backfill Industries",
            "140120260730800001",
            "Quarterly financial results",
        )
    ).encode("utf-8")

    empty_previous_day_html = """
        <div>0件 / 全0件</div>
        <div onclick="pagerLink('I_list_001_20260729.html')">1</div>
    """.encode("utf-8")

    requested_urls: list[str] = []

    def fixture_request(url: str, *_args: Any, **_kwargs: Any) -> tuple[bytes, str]:
        requested_urls.append(url)
        if url.endswith("I_main_00.html"):
            return main_html, company_feed["url"]
        if "I_list_001_20260731.html" in url:
            return (
                page_one_html,
                "https://www.release.tdnet.info/inbs/I_list_001_20260731.html",
            )
        if "I_list_002_20260731.html" in url:
            return (
                page_two_html,
                "https://www.release.tdnet.info/inbs/I_list_002_20260731.html",
            )
        if "I_list_001_20260730.html" in url:
            return (
                previous_day_html,
                "https://www.release.tdnet.info/inbs/I_list_001_20260730.html",
            )
        if "I_list_001_20260729.html" in url:
            return (
                empty_previous_day_html,
                "https://www.release.tdnet.info/inbs/I_list_001_20260729.html",
            )
        raise RuntimeError(f"unexpected fixture URL: {url}")

    original_request = producer.request
    producer.request = fixture_request
    try:
        parsed_items, source_status = producer.fetch_company_disclosures(
            company_feed,
            now,
        )
    finally:
        producer.request = original_request
    require(
        len(parsed_items) == 5
        and source_status["kind"] == "company-disclosure"
        and source_status["acceptedCount"] == 5
        and source_status["receivedCount"] == 6
        and source_status["scannedPages"] == 4
        and source_status["scannedDates"] == 3
        and source_status["coverageVersion"] == producer.TDNET_SCAN_COVERAGE_VERSION
        and source_status["coverageComplete"] is True
        and source_status["backfillFailedDates"] == 0
        and source_status["totalAvailableCount"] == 6
        and source_status["scanMode"] == "full",
        "TDnet full scan lost a prior-day disclosure or a hidden later page",
    )

    requested_urls.clear()

    def failing_backfill_request(
        url: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> tuple[bytes, str]:
        if "I_list_001_20260730.html" in url:
            requested_urls.append(url)
            raise RuntimeError("simulated prior-date failure")
        return fixture_request(url, *_args, **_kwargs)

    producer.request = failing_backfill_request
    try:
        _, failed_backfill_status = producer.fetch_company_disclosures(
            company_feed,
            now,
        )
    finally:
        producer.request = original_request
    require(
        failed_backfill_status["status"] == "limited"
        and failed_backfill_status["coverageComplete"] is False
        and failed_backfill_status["backfillFailedDates"] == 1
        and any("I_list_001_20260730.html" in url for url in requested_urls),
        "a failed prior-date fetch was silently reported as complete",
    )

    requested_urls.clear()
    recovery_feed = {
        **company_feed,
        "previousState": {
            "newestDisclosureId": "140120260730800001",
        },
    }
    producer.request = fixture_request
    try:
        recovered_items, recovered_status = producer.fetch_company_disclosures(
            recovery_feed,
            now,
        )
    finally:
        producer.request = original_request
    require(
        recovered_status["status"] == "ok"
        and recovered_status["scanMode"] == "incremental"
        and recovered_status["coverageComplete"] is True
        and recovered_status["backfillFailedDates"] == 0
        and recovered_status["scannedDates"] == 2
        and len(recovered_items) == 5
        and any("I_list_001_20260730.html" in url for url in requested_urls)
        and not any("I_list_001_20260729.html" in url for url in requested_urls),
        "a prior-date watermark did not recover the intervening TDnet date",
    )

    compact_cache = producer.build_company_disclosure_cache(
        parsed_items,
        now,
    )
    restored_cache = producer.restore_company_disclosure_cache(
        compact_cache,
        now,
    )
    require(
        len(compact_cache) == 5
        and len(restored_cache) == 5
        and {
            item.get("disclosureId") for item in restored_cache
        } == {
            item.get("disclosureId") for item in parsed_items
        }
        and all(
            item.get("discoveryProvider") == "tdnet-recent-cache"
            for item in restored_cache
        ),
        "unselected TDnet candidates were not preserved by the 48-hour cache",
    )
    unknown_items = [
        item for item in parsed_items if item.get("issuerCode") == "9999"
    ]
    require(
        {
            item.get("disclosureCategory") for item in unknown_items
        }
        == {"financial-results", "buyback", "stock-split"},
        "generic classifier did not preserve three distinct same-issuer events",
    )
    require(
        all(
            producer.publisher_domain(item["url"]) == "www.release.tdnet.info"
            and item["verification"] == "primary"
            for item in parsed_items
        ),
        "TDnet items do not lead to official primary PDFs",
    )
    require(
        producer.company_disclosure_category(
            "業績連動型株式報酬制度のお知らせ"
        )
        == ("", 0)
        and producer.company_disclosure_category(
            "第1四半期決算説明資料"
        )
        == ("", 0),
        "routine compensation or presentation material was misclassified as results",
    )
    require(
        not producer._issuer_is_mentioned(
            {"issuerCode": "2026", "issuerName": "架空産業"},
            {"title": "2026年7月の日本株決算", "summary": ""},
        )
        and not producer._issuer_is_mentioned(
            {"issuerCode": "7203", "issuerName": "架空自動車"},
            {"title": "利益7203億円を計上", "summary": ""},
        )
        and not producer._issuer_is_mentioned(
            {"issuerCode": "4813", "issuerName": "ACCESS"},
            {
                "title": "Investors seek access to markets during earnings season",
                "summary": "",
            },
        ),
        "bare numeric codes or short English names caused issuer false positives",
    )
    require(
        producer._issuer_is_mentioned(
            {"issuerCode": "Z99A", "issuerName": "無名企業"},
            {"title": "TYO:Z99A reports quarterly results", "summary": ""},
        ),
        "an explicitly labelled alphanumeric security code was not detected",
    )
    collision_report = producer.build_item(
        title="共通テックが決算を発表",
        summary="株価への影響を確認します。",
        url="https://example.com/shared-alias",
        source="Example News",
        source_kind="news",
        published="2026-07-31T15:31:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
    )
    collision_signals = producer.company_news_signals([
        {"sourceKind": "official-company", "issuerCode": "7777", "issuerName": "共通テックHD"},
        {"sourceKind": "official-company", "issuerCode": "6666", "issuerName": "共通テックグループ"},
        collision_report,
    ])
    require(
        all(row["mentions"] == 0 for row in collision_signals.values()),
        "a shared issuer stem was attributed to multiple companies",
    )

    def shared_alias_disclosure(
        code: str,
        name: str,
        document_id: str,
    ) -> dict[str, Any]:
        item = producer.build_item(
            title=f"{name}｜2027年3月期 第1四半期決算短信",
            summary="第1四半期決算を開示しました。",
            url=(
                "https://www.release.tdnet.info/inbs/"
                f"{document_id}.pdf"
            ),
            source=f"TDnet / {name}",
            source_kind="official-company",
            published="2026-07-31T15:30:00+09:00",
            retrieved_at=now,
            topic_hint="japan-stocks",
            verification="primary",
            timestamp_basis="tdnet-official-disclosure-time",
            timestamp_precision_value="minute",
            discovery_provider="tdnet-public-viewer",
            source_country="JP",
        )
        item.update({
            "disclosureId": document_id,
            "issuerCode": code,
            "issuerName": name,
            "disclosureCategory": "financial-results",
            "materialityScore": 93,
        })
        return item

    ambiguous_company_report = producer.build_item(
        title="共通テック、第1四半期決算を発表",
        summary="共通テックの決算速報です。",
        url="https://example.com/shared-company-stem-results",
        source="Example News",
        source_kind="news",
        published="2026-07-31T15:31:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
    )
    ambiguous_clusters = producer.cluster_story_candidates([
        shared_alias_disclosure(
            "7777",
            "共通テックHD",
            "140120260731977771",
        ),
        shared_alias_disclosure(
            "6666",
            "共通テックグループ",
            "140120260731966661",
        ),
        ambiguous_company_report,
    ])
    require(
        len(ambiguous_clusters) == 3
        and sum(
            1
            for row in ambiguous_clusters
            if row.get("sourceKind") == "official-company"
        )
        == 2
        and all(
            row.get("clusterSize") == 1
            for row in ambiguous_clusters
        ),
        "a shared issuer alias bridged two official company clusters",
    )

    explicit_code_report = producer.build_item(
        title="共通テック（7777）、第1四半期決算を発表",
        summary="証券コード7777の決算速報です。",
        url="https://example.com/explicit-company-code-results",
        source="Example News",
        source_kind="news",
        published="2026-07-31T15:31:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
    )
    explicit_clusters = producer.cluster_story_candidates([
        shared_alias_disclosure(
            "7777",
            "共通テックHD",
            "140120260731977772",
        ),
        shared_alias_disclosure(
            "6666",
            "共通テックグループ",
            "140120260731966662",
        ),
        explicit_code_report,
    ])
    explicit_cluster = next(
        (
            row for row in explicit_clusters
            if row.get("issuerCode") == "7777"
        ),
        None,
    )
    other_company_cluster = next(
        (
            row for row in explicit_clusters
            if row.get("issuerCode") == "6666"
        ),
        None,
    )
    require(
        len(explicit_clusters) == 2
        and explicit_cluster is not None
        and explicit_cluster.get("clusterSize") == 2
        and other_company_cluster is not None
        and other_company_cluster.get("clusterSize") == 1
        and any(
            row.get("url")
            == "https://example.com/explicit-company-code-results"
            for row in explicit_cluster.get("relatedLinks") or []
        ),
        "an explicit issuer code did not bind news to exactly one company",
    )

    def category_disclosure(
        category: str,
        document_id: str,
        title: str,
    ) -> dict[str, Any]:
        item = shared_alias_disclosure(
            "B99A",
            "Bridge Industries",
            document_id,
        )
        item["title"] = f"Bridge Industries｜{title}"
        item["disclosureCategory"] = category
        return item

    bridge_results_report = producer.build_item(
        title="Bridge Industries quarterly financial results",
        summary="Bridge Industries earnings report.",
        url="https://example.com/bridge-company-event",
        source="Example News",
        source_kind="news",
        published="2026-07-31T15:40:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
    )
    bridge_guidance_report = producer.build_item(
        title="Bridge Industries guidance revision",
        summary="Bridge Industries revised its business outlook.",
        url="https://example.com/bridge-company-event",
        source="Example Wire",
        source_kind="news-wire",
        published="2026-07-31T15:39:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
    )
    category_bridge_clusters = producer.cluster_story_candidates([
        bridge_results_report,
        bridge_guidance_report,
        category_disclosure(
            "financial-results",
            "140120260731955551",
            "Quarterly financial results",
        ),
        category_disclosure(
            "guidance-revision",
            "140120260731955552",
            "Guidance revision",
        ),
    ])
    official_category_clusters = [
        row for row in category_bridge_clusters
        if row.get("sourceKind") == "official-company"
    ]
    require(
        len(category_bridge_clusters) == 3
        and len(official_category_clusters) == 2
        and {
            row.get("disclosureCategory")
            for row in official_category_clusters
        } == {"financial-results", "guidance-revision"}
        and all(
            row.get("clusterSize") == 1
            for row in official_category_clusters
        ),
        "same-issuer reports bridged two different disclosure categories",
    )

    result_report = producer.build_item(
        title="未知テック、第1四半期決算を発表",
        summary="決算速報です。",
        url="https://example.com/unknown-company-results",
        source="Example News",
        source_kind="news",
        published="2026-07-31T15:32:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
    )
    result_report["originGroup"] = "reuters"
    duplicate_report = producer.build_item(
        title="未知テック、第1四半期決算を発表",
        summary="決算速報です。",
        url="https://another.example/unknown-company-results-copy",
        source="Reuters syndication",
        source_kind="news-wire",
        published="2026-07-31T15:33:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
    )
    duplicate_report["originGroup"] = "reuters"
    second_origin_report = producer.build_item(
        title="未知テックの好決算を市場が評価",
        summary="同社株の反応を報じます。",
        url="https://market.example/unknown-company-reaction",
        source="Market Journal",
        source_kind="news",
        published="2026-07-31T15:34:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
    )
    second_origin_report["originGroup"] = "market-journal"
    dynamic_only_report = producer.build_item(
        title="未知テック、第1四半期決算を発表",
        summary="決算速報です。",
        url="https://dynamic.example/unknown-company",
        source="Dynamic Search",
        source_kind="news",
        published="2026-07-31T15:35:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
        discovery_provider="issuer-dynamic",
    )
    social_only_report = producer.build_item(
        title="未知テック決算がSNSで話題",
        summary="未検証の投稿です。",
        url="https://x.com/example/status/123456789",
        source="X public index",
        source_kind="x-index",
        published="2026-07-31T15:36:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
        discovery_provider="public-search-index",
    )
    signal_input = parsed_items + [
        result_report,
        duplicate_report,
        second_origin_report,
        dynamic_only_report,
        social_only_report,
    ]
    producer.annotate_company_news_signals(signal_input)
    unknown_signal_item = next(
        item for item in parsed_items
        if item.get("issuerCode") == "9999"
    )
    require(
        unknown_signal_item["issuerNewsMentionCount"] == 2
        and unknown_signal_item["issuerIndependentNewsSourceCount"] == 2
        and unknown_signal_item["issuerBuzzScore"] == 6,
        "issuer buzz did not exclude syndication, dynamic search, or social posts",
    )
    clustered = producer.cluster_story_candidates(
        parsed_items + [result_report, dynamic_only_report]
    )
    result_cluster = next(
        (
            row for row in clustered
            if producer.event_signature(row)
            == "company-9999-financial-results"
        ),
        None,
    )
    require(
        len(clustered) == 5
        and result_cluster is not None
        and result_cluster["sourceKind"] == "official-company"
        and result_cluster["clusterSize"] == 3
        and result_cluster["rankingClusterSize"] == 2
        and result_cluster["independentSourceCount"] == 2
        and any(
            link.get("url") == "https://dynamic.example/unknown-company"
            and link.get("rankingEvidence") is False
            for link in result_cluster.get("relatedLinks") or []
        ),
        "generic issuer/category clustering mixed events or lost corroboration",
    )

    general_only_report = producer.build_item(
        title="Generic issuer posts quarterly results",
        summary="General discovery report.",
        url="https://general.example/generic-results",
        source="General News",
        source_kind="news",
        published="2026-07-31T15:34:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
        discovery_provider="google-news",
    )
    newer_dynamic_report = producer.build_item(
        title="Generic issuer posts quarterly results",
        summary="Issuer-specific follow-up result.",
        url="https://dynamic.example/generic-results",
        source="Dynamic Search",
        source_kind="news",
        published="2026-07-31T15:35:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
        discovery_provider="issuer-dynamic",
    )
    news_only_cluster = producer.cluster_story_candidates([
        newer_dynamic_report,
        general_only_report,
    ])
    require(
        len(news_only_cluster) == 1
        and news_only_cluster[0]["url"] == "https://general.example/generic-results"
        and news_only_cluster[0]["clusterSize"] == 2
        and news_only_cluster[0]["rankingClusterSize"] == 1
        and len(news_only_cluster[0]["relatedLinks"]) == 1
        and news_only_cluster[0]["relatedLinks"][0]["rankingEvidence"] is False,
        "a newer issuer-dynamic item became ranking evidence for a news-only cluster",
    )

    duplicate_url_first = producer.build_item(
        title="Generic market report",
        summary="One canonical article.",
        url="https://wire.example/canonical-story",
        source="Wire Label A",
        source_kind="news-wire",
        published="2026-07-31T15:40:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
        discovery_provider="google-news",
    )
    duplicate_url_second = producer.build_item(
        title="Generic market report mirror label",
        summary="The same canonical article from another discovery path.",
        url="https://wire.example/canonical-story",
        source="Publisher Label B",
        source_kind="news",
        published="2026-07-31T15:39:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
        discovery_provider="bing-news",
    )
    duplicate_url_cluster = producer.cluster_story_candidates([
        duplicate_url_first,
        duplicate_url_second,
    ])
    require(
        len(duplicate_url_cluster) == 1
        and duplicate_url_cluster[0]["clusterSize"] == 1
        and duplicate_url_cluster[0]["rankingClusterSize"] == 1
        and duplicate_url_cluster[0]["independentSourceCount"] == 1
        and not duplicate_url_cluster[0]["relatedLinks"],
        "one canonical URL was counted as multiple independent ranking sources",
    )

    shared_general = producer.build_item(
        title="未知テック quarterly results gain attention",
        summary="General discovery copy.",
        url="https://shared.example/unknown-results",
        source="General Publisher",
        source_kind="news",
        published="2026-07-31T15:34:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
        discovery_provider="google-news",
    )
    shared_dynamic = producer.build_item(
        title="未知テック quarterly results gain attention",
        summary="Dynamic copy of the same canonical article.",
        url="https://shared.example/unknown-results",
        source="Dynamic Search",
        source_kind="news",
        published="2026-07-31T15:35:00+09:00",
        retrieved_at=now,
        topic_hint="japan-stocks",
        discovery_provider="issuer-dynamic",
    )
    shared_url_cluster = producer.cluster_story_candidates([
        unknown_signal_item,
        shared_dynamic,
        shared_general,
    ])
    shared_result_cluster = next(
        row for row in shared_url_cluster
        if producer.event_signature(row) == "company-9999-financial-results"
    )
    require(
        shared_result_cluster["clusterSize"] == 2
        and shared_result_cluster["rankingClusterSize"] == 2
        and shared_result_cluster["independentSourceCount"] == 2
        and len(shared_result_cluster["relatedLinks"]) == 1
        and shared_result_cluster["relatedLinks"][0]["source"] == "General Publisher"
        and shared_result_cluster["relatedLinks"][0]["rankingEvidence"] is True,
        "same-URL dynamic copy hid or mislabeled the general ranking evidence",
    )

    dynamic_queries = producer.build_dynamic_company_news_queries(signal_input)
    require(
        dynamic_queries
        and any(
            "未知テック" in query["query"]
            and "9999" not in query["query"]
            and query.get("discoveryProvider") == "issuer-dynamic"
            for query in dynamic_queries
        ),
        "dynamic discovery missed the issuer or retained a bare numeric code",
    )
    require(
        unknown_signal_item["issuerBuzzScore"] == 6,
        "dynamic discovery improperly self-reinforced issuer buzz",
    )

    filler_items = [
        producer.build_item(
            title=f"海外市場速報 {index:02d}",
            summary="株式市場の更新です。",
            url=f"https://example.com/market-{index:02d}",
            source="Example News",
            source_kind="news",
            published=f"2026-07-31T06:{index:02d}:00+00:00",
            retrieved_at=now,
            topic_hint="us-stocks",
        )
        for index in range(30)
    ]
    ranked = producer.rank_briefing_items(
        clustered + filler_items,
        already_clustered=True,
    )
    require(
        any(
            producer.event_signature(item)
            == "company-9999-financial-results"
            for item in ranked
        ),
        "a material unknown-company result was displaced by a newer-news flood",
    )
    require(
        sum(
            1 for item in ranked
            if item.get("sourceKind") == "official-company"
        )
        <= 6,
        "company disclosure lane exceeded its six-card cap",
    )

    issuer_cap_items: list[dict[str, Any]] = []
    for index, category in enumerate((
        "financial-results",
        "guidance-revision",
        "m-and-a-tob",
        "accounting-governance",
    )):
        cap_item = producer.build_item(
            title=(
                "Jason Furman comments on Cap Industries"
                if index == 3
                else f"Cap Industries material event {index}"
            ),
            summary="Official material disclosure.",
            url=f"https://www.release.tdnet.info/inbs/issuer-cap-{index}.pdf",
            source="TDnet / Cap Industries",
            source_kind="official-company",
            published=f"2026-07-31T15:{40 + index}:00+09:00",
            retrieved_at=now,
            topic_hint="japan-stocks",
            verification="primary",
        )
        cap_item.update({
            "disclosureId": f"issuer-cap-{index:02d}",
            "issuerCode": "C99A",
            "issuerName": "Cap Industries",
            "disclosureCategory": category,
            "materialityScore": 99 - index,
            "issuerNewsMentionCount": 0,
            "issuerIndependentNewsSourceCount": 0,
            "issuerBuzzScore": 0,
        })
        issuer_cap_items.append(cap_item)
    issuer_cap_ranked = producer.rank_briefing_items(
        issuer_cap_items,
        already_clustered=True,
    )
    require(
        sum(item.get("issuerCode") == "C99A" for item in issuer_cap_ranked) == 3,
        "reserved company categories bypassed the three-card issuer cap",
    )

    bundle_specs = (
        ("RFIN", "financial-results", 100, 12, 6, 12),
        ("RGDE", "guidance-revision", 100, 12, 6, 12),
        ("RTOB", "m-and-a-tob", 100, 12, 6, 12),
        ("RACC", "accounting-governance", 100, 12, 6, 12),
        ("BNDL", "financial-results", 100, 1, 1, 0),
        ("BNDL", "buyback", 98, 5, 5, 12),
        ("BNDL", "stock-split", 95, 5, 5, 12),
    )
    bundle_items: list[dict[str, Any]] = []
    for index, (
        issuer,
        category,
        materiality,
        cluster_size,
        independent_sources,
        buzz,
    ) in enumerate(bundle_specs):
        bundle_item = producer.build_item(
            title=f"Generic {issuer} {category} disclosure",
            summary="Official same-time material disclosure.",
            url=f"https://www.release.tdnet.info/inbs/generic-bundle-{index}.pdf",
            source=f"TDnet / Generic {issuer}",
            source_kind="official-company",
            published="2026-07-31T15:30:00+09:00",
            retrieved_at=now,
            topic_hint="japan-stocks",
            verification="primary",
        )
        bundle_item.update({
            "disclosureId": f"generic-bundle-{index:02d}",
            "issuerCode": issuer,
            "issuerName": f"Generic {issuer}",
            "disclosureCategory": category,
            "materialityScore": materiality,
            "clusterSize": cluster_size,
            "rankingClusterSize": cluster_size,
            "independentSourceCount": independent_sources,
            "issuerNewsMentionCount": buzz,
            "issuerIndependentNewsSourceCount": independent_sources,
            "issuerBuzzScore": buzz,
        })
        bundle_items.append(bundle_item)
    bundle_ranked = producer.rank_briefing_items(
        bundle_items,
        already_clustered=True,
    )
    selected_bundle_categories = {
        item.get("disclosureCategory")
        for item in bundle_ranked
        if item.get("issuerCode") == "BNDL"
    }
    require(
        "financial-results" in selected_bundle_categories
        and len(bundle_ranked) == 6,
        "same-time ancillary disclosures displaced their issuer's core results",
    )

    carry_now = now + timedelta(hours=8)
    carry_package = {
        "briefing": {
            "items": [issuer_cap_items[0]],
            "summary": "stale aggregate",
            "topicCounts": {"stale": 99},
            "verificationCounts": {"stale": 99},
            "sourceKindCounts": {"stale": 99},
            "bullish": [],
            "bearish": [],
            "unverifiedCount": 99,
        },
        "dataHealth": {
            "carriedForwardItems": 0,
            "status": "ok",
            "message": "",
        },
    }
    carry_previous = {"briefing": {"items": issuer_cap_items[1:]}}
    producer.carry_forward_if_needed(carry_package, carry_previous, carry_now)
    carried_company_items = [
        item for item in carry_package["briefing"]["items"]
        if item.get("sourceKind") == "official-company"
    ]
    require(
        len(carried_company_items) == 3
        and sum(item.get("issuerCode") == "C99A" for item in carried_company_items) == 3
        and carry_package["dataHealth"]["carriedForwardItems"] == 2,
        "carry-forward bypassed the three-card issuer cap",
    )
    carried_briefing = carry_package["briefing"]
    require(
        sum(carried_briefing["topicCounts"].values()) == len(carried_briefing["items"])
        and sum(carried_briefing["verificationCounts"].values()) == len(carried_briefing["items"])
        and sum(carried_briefing["sourceKindCounts"].values()) == len(carried_briefing["items"])
        and carried_briefing["unverifiedCount"]
        == sum(item["verification"] == "unverified" for item in carried_briefing["items"]),
        "carry-forward left stale briefing aggregates",
    )

    carry_guidance = dict(bundle_items[1])
    carry_guidance.update({
        "issuerCode": "BNDL",
        "issuerName": "Generic BNDL",
    })
    carry_bundle_package = {
        "briefing": {
            "items": [carry_guidance],
            "summary": "stale aggregate",
            "topicCounts": {"stale": 99},
            "verificationCounts": {"stale": 99},
            "sourceKindCounts": {"stale": 99},
            "bullish": [],
            "bearish": [],
            "unverifiedCount": 99,
        },
        "dataHealth": {
            "carriedForwardItems": 0,
            "status": "ok",
            "message": "",
        },
    }
    carry_bundle_previous = {
        "briefing": {
            "items": [bundle_items[5], bundle_items[6], bundle_items[4]],
        },
    }
    producer.carry_forward_if_needed(
        carry_bundle_package,
        carry_bundle_previous,
        carry_now,
    )
    carry_bundle_categories = {
        item.get("disclosureCategory")
        for item in carry_bundle_package["briefing"]["items"]
        if item.get("issuerCode") == "BNDL"
    }
    require(
        "financial-results" in carry_bundle_categories
        and len(carry_bundle_categories) == 3
        and carry_bundle_package["dataHealth"]["carriedForwardItems"] == 2,
        "carry-forward ancillary items displaced their same-time core results",
    )

    requested_urls.clear()
    head_only_feed = {
        **company_feed,
        "previousState": {
            "newestDisclosureId": "140120260731900001",
        },
    }
    producer.request = fixture_request
    try:
        _, head_status = producer.fetch_company_disclosures(
            head_only_feed,
            now,
        )
    finally:
        producer.request = original_request
    require(
        head_status["scanMode"] == "head-only"
        and head_status["scannedPages"] == 1
        and not any("I_list_002_" in url for url in requested_urls),
        "TDnet incremental watermark did not prevent unnecessary deep scanning",
    )

    require_https_url(
        "https://www.release.tdnet.info/inbs/140120260731900001.pdf",
        "TDnet official regression",
        hosts=OFFICIAL_SOURCE_HOSTS["official-company"],
    )
    try:
        require_https_url(
            "https://example.com/not-an-official-disclosure",
            "company disclosure regression",
            hosts=OFFICIAL_SOURCE_HOSTS["official-company"],
        )
    except ValidationError:
        pass
    else:
        raise ValidationError(
            "unapproved host was accepted as an official company disclosure"
        )


def validate_company_disclosure_cache(
    data: dict[str, Any],
    generated_utc: datetime,
) -> set[str]:
    rows = require_list(
        data.get("companyDisclosureCache"),
        "companyDisclosureCache",
    )
    require(
        len(rows) <= 2000,
        "companyDisclosureCache exceeds its 2000-row safety cap",
    )
    disclosure_ids: set[str] = set()
    previous_time: datetime | None = None
    for index, raw in enumerate(rows):
        context = f"companyDisclosureCache[{index}]"
        row = require_dict(raw, context)
        require_keys(
            row,
            {
                "disclosureId",
                "issuerCode",
                "issuerName",
                "disclosureCategory",
                "materialityScore",
                "title",
                "url",
                "publishedAtUtc",
            },
            context,
        )
        disclosure_id = require_string(
            row["disclosureId"], f"{context}.disclosureId"
        )
        require(
            re.fullmatch(r"[0-9A-Za-z_-]{8,80}", disclosure_id) is not None,
            f"{context}.disclosureId is malformed",
        )
        require(
            disclosure_id not in disclosure_ids,
            f"{context}.disclosureId is duplicated",
        )
        disclosure_ids.add(disclosure_id)
        require(
            re.fullmatch(
                r"[0-9A-Z]{4,6}",
                require_string(row["issuerCode"], f"{context}.issuerCode"),
            ) is not None,
            f"{context}.issuerCode is malformed",
        )
        require_string(row["issuerName"], f"{context}.issuerName")
        require_string(row["title"], f"{context}.title")
        require(
            row["disclosureCategory"] in DISCLOSURE_CATEGORIES,
            f"{context}.disclosureCategory is invalid",
        )
        require_int(
            row["materialityScore"],
            f"{context}.materialityScore",
            low=0,
            high=100,
        )
        require_https_url(
            row["url"],
            f"{context}.url",
            hosts={"release.tdnet.info"},
        )
        published = parse_timestamp(
            row["publishedAtUtc"],
            f"{context}.publishedAtUtc",
            expected_offset=timedelta(0),
        )
        require(
            published <= generated_utc + timedelta(minutes=2)
            and generated_utc - published <= timedelta(hours=48, minutes=5),
            f"{context} is outside the 48-hour cache window",
        )
        if previous_time is not None:
            require(
                published <= previous_time,
                "companyDisclosureCache must be newest-first",
            )
        previous_time = published
    return disclosure_ids


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
            "companyDisclosureCache",
            "sourceStatus",
            "methodology",
        },
        "root",
        optional={"fallbackAppliedAtUtc"},
    )
    require(data["schemaVersion"] == 1, "live schemaVersion must be 1")
    generated_utc, generated_jst = validate_root_times(data)
    cached_disclosure_ids = validate_company_disclosure_cache(data, generated_utc)
    validate_refresh_policy(data)
    source_rows, market_status = validate_source_status(data, generated_utc)
    validate_data_health(data, source_rows)
    validate_methodology(data)
    briefing_items = validate_briefing(
        data, generated_utc, generated_jst, source_rows
    )
    for item in briefing_items.values():
        if (
            item.get("sourceKind") == "official-company"
            and item.get("publisherDomain") == "www.release.tdnet.info"
        ):
            require(
                item.get("disclosureId") in cached_disclosure_ids,
                "selected TDnet disclosure is missing from the 48-hour cache",
            )
    selected_company_items = [
        item for item in briefing_items.values()
        if item.get("sourceKind") == "official-company"
    ]

    def selected_company_time(selected: dict[str, Any]) -> datetime:
        return parse_timestamp(
            selected["effectivePublishedAtUtc"],
            f"selected company item {selected['id']}.effectivePublishedAtUtc",
            expected_offset=timedelta(0),
        )

    cached_company_items = data["companyDisclosureCache"]
    for item in selected_company_items:
        if item.get("disclosureCategory") not in {
            "buyback",
            "stock-split",
            "dividend",
            "capital-raising",
        }:
            continue
        issuer = str(item.get("issuerCode") or "")
        item_time = parse_timestamp(
            item["effectivePublishedAtUtc"],
            f"selected company item {item['id']}.effectivePublishedAtUtc",
            expected_offset=timedelta(0),
        )
        bundled_results = [
            row for row in cached_company_items
            if str(row.get("issuerCode") or "") == issuer
            and row.get("disclosureCategory") == "financial-results"
            and abs((
                parse_timestamp(
                    row["publishedAtUtc"],
                    f"cached bundle result {row['disclosureId']}.publishedAtUtc",
                    expected_offset=timedelta(0),
                ) - item_time
            ).total_seconds()) <= 15 * 60
        ]
        if bundled_results:
            require(
                any(
                    selected.get("issuerCode") == issuer
                    and selected.get("disclosureCategory") == "financial-results"
                    and abs((selected_company_time(selected) - item_time).total_seconds()) <= 15 * 60
                    for selected in selected_company_items
                ),
                "a selected same-time company bundle omitted its core financial results",
            )
    quotes = validate_premarket(
        data, generated_utc, generated_jst, market_status
    )
    validate_market_shock(
        data, generated_utc, quotes, briefing_items
    )
    run_price_only_intervention_regression()
    run_quote_reference_regressions()
    run_localization_freshness_regressions()
    run_story_cluster_regressions()
    run_company_disclosure_regressions()
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
