#!/usr/bin/env python3
"""Fail the data update when core data or audited calculation contracts break."""

from __future__ import annotations

import json
import math
import re
import statistics
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "latest.json"
MONEY_DATA_FILE = ROOT / "data" / "money-strategist-history.json"
MARGIN_DATA_FILE = ROOT / "data" / "margin-debt-history.json"
APP_FILE = ROOT / "app.js"
INDEX_FILE = ROOT / "index.html"
SNAPSHOT_HISTORY_INDEX = ROOT / "data" / "history" / "index.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def close_enough(actual: float, expected: float, *, relative: float = 1e-8) -> bool:
    scale = max(1.0, abs(actual), abs(expected))
    return abs(actual - expected) <= scale * relative


def dcf_value(fcf: float, growth_pct: float, discount_pct: float, terminal_pct: float, years: int = 10) -> float:
    growth = growth_pct / 100
    discount = discount_pct / 100
    terminal = terminal_pct / 100
    require(fcf > 0, "DCF input FCF must be positive")
    require(discount > terminal, "DCF discount rate must exceed terminal growth")
    future = fcf
    present = 0.0
    for year in range(1, years + 1):
        future *= 1 + growth
        present += future / (1 + discount) ** year
    present += future * (1 + terminal) / (discount - terminal) / (1 + discount) ** years
    return present


def check_yoy_dates(company: dict[str, Any], prefix: str) -> None:
    current = company.get(f"{prefix}CurrentDate")
    prior = company.get(f"{prefix}PriorDate")
    if current is None and prior is None:
        return
    require(bool(current and prior), f"{company['ticker']} {prefix}: one comparison date is missing")
    gap = (date.fromisoformat(current) - date.fromisoformat(prior)).days
    require(320 <= gap <= 410, f"{company['ticker']} {prefix}: comparison is not year-over-year ({gap} days)")


def main() -> None:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    require(data.get("schemaVersion") == 14, "schemaVersion must be 14")
    require(data.get("methodVersion") == "4.3.0", "methodVersion must be 4.3.0")

    generated = datetime.fromisoformat(data["generatedAtUtc"]).date()
    market_day = date.fromisoformat(data["marketDate"])
    require(0 <= (generated - market_day).days <= 10, "market date is future-dated or stale")

    series = data["market"]["series"]
    for key in ("SOX", "NASDAQ", "NIKKEI", "VIX", "SP500", "GOLD"):
        row = series.get(key)
        require(bool(row), f"missing core market series: {key}")
        require(finite(row.get("close")) and row["close"] > 0, f"invalid close: {key}")
        require(finite(row.get("drawdown3yPct")) and 0 <= row["drawdown3yPct"] <= 100, f"invalid drawdown: {key}")
        require(finite(row.get("weeksBelowSma200")) and row["weeksBelowSma200"] >= 0, f"invalid SMA duration: {key}")
        calculated_drawdown = (1 - row["close"] / row["peak3y"]) * 100
        require(close_enough(calculated_drawdown, row["drawdown3yPct"]), f"{key}: drawdown identity failed")

    purchasing_power = data["market"].get("purchasingPowerStress") or {}
    require(bool(purchasing_power), "purchasing-power monitor is missing")
    require(finite(purchasing_power.get("sp500GoldRatio")) and purchasing_power["sp500GoldRatio"] > 0, "invalid S&P 500 / gold ratio")
    require(
        close_enough(
            purchasing_power["sp500GoldRatio"],
            purchasing_power["sp500"] / purchasing_power["goldUsdPerOunce"],
        ),
        "S&P 500 / gold ratio identity failed",
    )
    require(len(purchasing_power.get("chart") or []) >= 100, "purchasing-power chart history is too short")
    require(
        (purchasing_power.get("divergence") or {}).get("code")
        in {"stealth-loss", "broad-loss", "nominal-only-loss", "aligned-rise", "insufficient"},
        "invalid purchasing-power divergence code",
    )

    topix = series.get("TOPIX")
    require(bool(topix), "missing TOPIX series")
    require(finite(topix.get("close")) and topix["close"] > 0, "invalid TOPIX close")
    require(finite(topix.get("change20dPct")), "TOPIX 20-day return is missing")
    kioxia_series = series.get("KIOXIA")
    require(bool(kioxia_series), "missing Kioxia series")
    require(finite(kioxia_series.get("peak2026")) and kioxia_series["peak2026"] > 0, "Kioxia 2026 peak is missing")

    companies = data.get("companies") or []
    require(len(companies) == 26, f"expected 26 companies, got {len(companies)}")
    category_counts = {
        category: sum(1 for company in companies if company.get("category") == category)
        for category in ("overseas-ai", "japan-ai", "japan-diversified")
    }
    require(category_counts == {"overseas-ai": 10, "japan-ai": 8, "japan-diversified": 8}, f"category counts changed: {category_counts}")

    tickers = set()
    for company in companies:
        ticker = company["ticker"]
        require(ticker not in tickers, f"duplicate ticker: {ticker}")
        tickers.add(ticker)
        require(finite(company.get("price")) and company["price"] > 0, f"{ticker}: invalid price")
        require(finite(company.get("marketCap")) and company["marketCap"] > 0, f"{ticker}: invalid market cap")
        require(finite(company.get("drawdown3yPct")) and 0 <= company["drawdown3yPct"] <= 100, f"{ticker}: invalid drawdown")
        price_row = series.get(ticker)
        require(bool(price_row), f"{ticker}: market series is missing")
        calculated_drawdown = (1 - company["price"] / price_row["peak3y"]) * 100
        require(close_enough(calculated_drawdown, company["drawdown3yPct"]), f"{ticker}: company drawdown identity failed")
        if finite(company.get("approxTrailingPe")):
            require(finite(company.get("trailingNetIncome")) and company["trailingNetIncome"] > 0, f"{ticker}: PE has no positive net income")
            require(close_enough(company["approxTrailingPe"], company["marketCap"] / company["trailingNetIncome"]), f"{ticker}: approximate PE identity failed")
        if finite(company.get("approxPriceToBook")):
            require(finite(company.get("stockholdersEquity")) and company["stockholdersEquity"] > 0, f"{ticker}: PBR has no positive equity")
            require(close_enough(company["approxPriceToBook"], company["marketCap"] / company["stockholdersEquity"]), f"{ticker}: approximate PBR identity failed")
        if finite(company.get("trailingDividendYieldPct")):
            require(0 <= company["trailingDividendYieldPct"] <= 20, f"{ticker}: trailing dividend yield out of range")
        if finite(company.get("enterpriseValue")):
            expected_ev = company["marketCap"] + (company.get("debt") or 0) - (company.get("cash") or 0)
            require(close_enough(company["enterpriseValue"], expected_ev), f"{ticker}: EV identity failed")
        valuation_fcf = company.get("valuationFcf")
        if finite(valuation_fcf):
            expected_yield = valuation_fcf / company["marketCap"] * 100
            require(close_enough(company["valuationFcfYieldPct"], expected_yield), f"{ticker}: valuation FCF yield failed")
        assumptions = company.get("assumptions") or {}
        discount = assumptions.get("discountRatePct")
        terminal = assumptions.get("terminalGrowthPct")
        base_growth = assumptions.get("baseGrowthPct")
        years = assumptions.get("forecastYears")
        require(finite(discount) and 6 <= discount <= 16, f"{ticker}: discount assumption out of range")
        require(finite(terminal) and 0 <= terminal <= 4, f"{ticker}: terminal assumption out of range")
        require(discount > terminal, f"{ticker}: discount must exceed terminal growth")
        require(finite(base_growth) and -10 <= base_growth <= 35, f"{ticker}: base growth assumption out of range")
        require(years == 10, f"{ticker}: forecast horizon changed without audit")
        if finite(valuation_fcf) and valuation_fcf > 0:
            base_value = dcf_value(valuation_fcf, base_growth, discount, terminal, years)
            require(finite(base_value) and base_value > 0, f"{ticker}: invalid base DCF")
        require(company.get("ttmCapex") is None or company["ttmCapex"] >= 0, f"{ticker}: CapEx magnitude must be non-negative")
        check_yoy_dates(company, "revenueGrowth")
        check_yoy_dates(company, "freeCashFlowGrowth")
        check_yoy_dates(company, "capexGrowth")

    overseas = data["market"]["aiBasket"]
    japan = data["market"]["japanAiBasket"]
    require(len(overseas.get("constituents") or []) == 10, "overseas AI basket must contain 10 companies")
    require(len(japan.get("constituents") or []) == 8, "Japan transmission basket must contain 8 companies")
    require(japan.get("label", "").startswith("日本AI・半導体連動8社"), "Japan basket must be labelled as a site-specific proxy")

    derived = data["derived"]
    require(derived.get("latestQuarterRevenueGrowthCoverage", 0) >= 7, "revenue YoY coverage below 7/10")
    require(derived.get("fcfDeteriorationCoverage", 0) >= 7, "FCF deterioration coverage below 7/10")
    require(derived.get("hyperscalerCapexCoverage") == 4, "hyperscaler CapEx coverage must be 4/4")
    require(0 <= derived.get("fcfDeteriorationBreadthPct", -1) <= 100, "invalid FCF deterioration breadth")


    us_risk = data["market"].get("usBubbleRisk") or {}
    components = us_risk.get("components") or []
    require(us_risk.get("method") == "US breakdown progression index v1.0", "US risk method label is missing")
    require(len(components) == 5, "US risk must contain five evidence groups")
    require(close_enough(sum(row["maxScore"] for row in components), 100.0), "US risk maximum must be 100")
    require(close_enough(sum(row["score"] for row in components), us_risk["rawScore"]), "US risk raw-score identity failed")
    require(close_enough(sum(row["knownMax"] for row in components), us_risk["knownMax"]), "US risk coverage identity failed")
    require(us_risk["knownMax"] >= 70, "US risk coverage is too low")
    require(close_enough(us_risk["score"], us_risk["rawScore"] / us_risk["knownMax"] * 100, relative=1e-3), "US risk normalized score failed")
    require(0 <= us_risk["score"] <= 100, "US risk score out of range")
    require(len(us_risk.get("scenarios") or []) == 4, "US risk S&P levels are incomplete")
    sp_peak = series["SP500"]["peak3y"]
    for scenario in us_risk["scenarios"]:
        expected_level = sp_peak * (1 - scenario["drawdownFromPeakPct"] / 100)
        require(close_enough(scenario["level"], expected_level, relative=1e-5), f"US scenario level failed: {scenario['id']}")

    financial_conditions = data.get("macro", {}).get("financialConditions") or {}
    require(financial_conditions.get("seriesId") == "NFCI", "NFCI is missing")
    require(finite(financial_conditions.get("value")), "NFCI value is invalid")

    berkshire = data["market"].get("berkshireMonitor") or {}
    balance = berkshire.get("balanceLatest") or {}
    previous_balance = berkshire.get("balancePrevious") or {}
    require(balance.get("periodEnd") >= previous_balance.get("periodEnd", ""), "Berkshire periods are reversed")
    expected_reserve = balance["cashAndEquivalentsBillion"] + balance["treasuryBillsBillion"] - balance["unsettledTreasuryPayableBillion"]
    require(close_enough(balance["netLiquidReserveBillion"], expected_reserve), "Berkshire net liquidity identity failed")
    expected_pool_ratio = expected_reserve / (expected_reserve + balance["equitySecuritiesBillion"] + balance["fixedMaturityBillion"]) * 100
    require(close_enough(balance["investmentPoolLiquidRatioPct"], expected_pool_ratio), "Berkshire liquidity ratio identity failed")
    thirteen_f = berkshire.get("thirteenF") or {}
    require(thirteen_f.get("latest", {}).get("reportDate") > thirteen_f.get("previous", {}).get("reportDate", ""), "13F periods are reversed")
    require(len(thirteen_f.get("buys") or []) >= 3 and len(thirteen_f.get("sells") or []) >= 3, "13F comparison is incomplete")

    overseas = data.get("overseasIntelligence") or {}
    require(isinstance(overseas.get("newsItems"), list), "overseas news list is missing")
    require((overseas.get("x") or {}).get("status") in {"connected", "not-configured", "failed"}, "X update status is invalid")
    require(bool(overseas.get("readingRule")), "overseas information reading rule is missing")

    by_ticker = {company["ticker"]: company for company in companies}
    require(by_ticker["7203.T"].get("valuationFcf") == 2_492_282_000_000, "Toyota audited valuation FCF changed")
    require(by_ticker["7267.T"].get("valuationFcf") == 685_867_000_000, "Honda audited valuation FCF changed")
    require("非金融" in by_ticker["7203.T"].get("valuationFcfBasis", ""), "Toyota non-financial basis missing")
    require("非金融" in by_ticker["7267.T"].get("valuationFcfBasis", ""), "Honda non-financial basis missing")
    require(by_ticker["9984.T"].get("valuationFcf", 0) <= 0, "SoftBank should not silently receive a positive common DCF input")

    toyota = by_ticker["7203.T"]
    toyota_base = dcf_value(
        toyota["valuationFcf"], toyota["assumptions"]["baseGrowthPct"],
        toyota["assumptions"]["discountRatePct"], toyota["assumptions"]["terminalGrowthPct"],
    )
    toyota_ratio = toyota_base / toyota["marketCap"]
    require(0.80 <= toyota_ratio <= 1.10, f"Toyota base DCF ratio is implausibly far from audited range: {toyota_ratio:.3f}")

    honda = by_ticker["7267.T"]
    honda_base = dcf_value(
        honda["valuationFcf"], honda["assumptions"]["baseGrowthPct"],
        honda["assumptions"]["discountRatePct"], honda["assumptions"]["terminalGrowthPct"],
    )
    honda_ratio = honda_base / honda["marketCap"]
    require(honda_ratio >= 1.0, f"Honda audited FCF no longer supports the current market cap: {honda_ratio:.3f}")

    reference = data["market"]["nikkeiValuationReference"]
    require(reference.get("date") == "2026-07-17", "Nikkei reference date changed without audit")
    require(reference.get("price") == 64141.12, "Nikkei reference close changed without audit")
    require(reference.get("indexPe") == 22.99 and reference.get("indexPb") == 2.71, "Nikkei official index-weight PE/PB changed without audit")
    require(reference.get("marketCapPe") == 17.42 and reference.get("marketCapPb") == 1.84, "Nikkei official market-cap PE/PB changed without audit")
    require(close_enough(reference["impliedEps"], reference["price"] / reference["marketCapPe"]), "Nikkei implied EPS identity failed")
    require(close_enough(reference["impliedBps"], reference["price"] / reference["marketCapPb"]), "Nikkei implied BPS identity failed")


    sakakibara = data["market"].get("sakakibaraAnalysis") or {}
    require(sakakibara.get("methodLabel") == "榊原式 proxy v1.1", "Sakakibara method label changed")
    nt = sakakibara.get("ntRatio") or {}
    require(finite(nt.get("latest")) and finite(nt.get("peak252d")), "NT ratio values are missing")
    nt_history = nt.get("history") or []
    require(bool(nt_history), "NT ratio history is missing")
    require(nt.get("latestDate") == topix.get("date") == nt_history[-1].get("date"), "NT ratio inputs are not aligned to the latest common market date")
    require(nt.get("latestDate") <= series["NIKKEI"].get("date"), "NT ratio common date is after the Nikkei series date")
    expected_nt = nt_history[-1].get("ntRatio")
    require(close_enough(nt["latest"], expected_nt), "latest NT ratio identity failed")
    require(nt["peak252d"] >= nt["latest"], "NT peak is below latest ratio")
    expected_nt_decline = (1 - nt["latest"] / nt["peak252d"]) * 100
    require(close_enough(nt["declineFromPeakPct"], expected_nt_decline), "NT peak decline identity failed")
    require(len(nt_history) >= 200, "NT ratio history is too short")

    gates = sakakibara.get("gates") or {}
    for key in ("distortion", "ntReversal", "broadOutperformance", "basketRotation", "breadthConfirmation"):
        require(isinstance(gates.get(key), bool), f"Sakakibara gate is not boolean: {key}")
    expected_confirmation = sum(
        1 for key in ("ntReversal", "broadOutperformance", "basketRotation", "breadthConfirmation")
        if gates[key]
    )
    require(sakakibara.get("confirmationCount") == expected_confirmation, "Sakakibara confirmation count failed")
    require(sakakibara.get("confirmationMax") == 4, "Sakakibara confirmation maximum changed")

    kioxia = sakakibara.get("kioxiaCase") or {}
    require(kioxia.get("articleStartDate") == "2026-03-31", "Kioxia article start date changed")
    require(close_enough(kioxia.get("articleStartLow"), 18540.0), "Kioxia article start price changed")
    require(close_enough(kioxia.get("articleStartClose"), 19080.0), "Kioxia article start close changed")
    require(finite(kioxia.get("close")) and kioxia["close"] > 0, "Kioxia latest close is invalid")
    require(finite(kioxia.get("peak2026")) and kioxia["peak2026"] >= kioxia["close"], "Kioxia 2026 peak is invalid")
    require(date.fromisoformat(kioxia["date"]) >= date.fromisoformat(kioxia["articleStartDate"]), "Kioxia latest date is stale")
    expected_kioxia_rise = (kioxia["peak2026"] / kioxia["articleStartLow"] - 1) * 100
    require(close_enough(kioxia["riseFromArticleStartToPeakPct"], expected_kioxia_rise), "Kioxia rise identity failed")
    expected_kioxia_drawdown = (1 - kioxia["close"] / kioxia["peak2026"]) * 100
    require(close_enough(kioxia["drawdownFrom2026HighPct"], expected_kioxia_drawdown), "Kioxia drawdown identity failed")

    article = sakakibara.get("articleScenario") or {}
    require(article.get("asOfDate") == "2026-07-17", "article valuation date changed")
    require(close_enough(article["earningsFairValue"], article["eps"] * article["targetPe"]), "article earnings fair-value identity failed")
    require(close_enough(article["targetPb"], (1 + article["roePct"] / 100) ** article["growthYears"]), "article target PBR identity failed")
    require(close_enough(article["bookFairValue"], article["bps"] * article["targetPb"]), "article book fair-value identity failed")


    market_path = sakakibara.get("marketPath") or {}
    require(
        market_path.get("statusCode") in {
            "insufficient", "panic", "mixed", "neutral", "normalization-strong",
            "normalization-watch", "panic-watch", "unclear",
        },
        "market path status is invalid",
    )
    for axis_name in ("normalization", "panic"):
        axis = market_path.get(axis_name) or {}
        components = axis.get("components") or []
        require(len(components) == 4, f"{axis_name}: market path must contain four components")
        component_score = sum(component["score"] for component in components)
        component_known = sum(component["knownMax"] for component in components)
        component_max = sum(component["maxScore"] for component in components)
        require(close_enough(axis["rawScore"], component_score), f"{axis_name}: raw score identity failed")
        require(close_enough(axis["knownMax"], component_known), f"{axis_name}: known maximum identity failed")
        require(close_enough(axis["maxScore"], component_max), f"{axis_name}: maximum identity failed")
        require(close_enough(component_max, 100.0), f"{axis_name}: maximum must be 100")
        require(close_enough(axis["coveragePct"], component_known / component_max * 100.0), f"{axis_name}: coverage identity failed")
        if component_known >= 60:
            require(finite(axis.get("score")), f"{axis_name}: normalized score is missing")
            require(close_enough(axis["score"], component_score / component_known * 100.0, relative=1e-3), f"{axis_name}: normalized score identity failed")
        require(0 <= axis.get("coveragePct", -1) <= 100, f"{axis_name}: coverage out of range")
        for component in components:
            require(0 <= component["score"] <= component["knownMax"] <= component["maxScore"], f"{axis_name}: component score out of range")
            require(bool(component.get("detail")), f"{axis_name}: component explanation is missing")

    normalization_score = market_path["normalization"].get("score")
    panic_score = market_path["panic"].get("score")
    if finite(normalization_score) and finite(panic_score):
        expected_route = max(-100.0, min(100.0, normalization_score - panic_score))
        require(close_enough(market_path["routeIndex"], expected_route, relative=1e-3), "market path route-index identity failed")
        require(-100 <= market_path["routeIndex"] <= 100, "market path route index out of range")

    valuation_anchor = market_path.get("valuationAnchor") or {}
    expected_lower = min(article["earningsFairValue"], article["bookFairValue"])
    expected_upper = max(article["earningsFairValue"], article["bookFairValue"])
    require(close_enough(valuation_anchor["lower"], expected_lower), "market path lower valuation anchor failed")
    require(close_enough(valuation_anchor["upper"], expected_upper), "market path upper valuation anchor failed")
    require(close_enough(
        valuation_anchor["drawdownFromPeakToUpperPct"],
        (1 - valuation_anchor["upper"] / valuation_anchor["peak2026"]) * 100,
    ), "market path upper peak-drawdown identity failed")
    require(close_enough(
        valuation_anchor["drawdownFromPeakToLowerPct"],
        (1 - valuation_anchor["lower"] / valuation_anchor["peak2026"]) * 100,
    ), "market path lower peak-drawdown identity failed")
    require("正常化スコア - パニックスコア" in market_path.get("rules", {}).get("formula", ""), "market path formula explanation is missing")
    require("確率予測ではない" in market_path.get("rules", {}).get("thresholdCaveat", ""), "market path forecast caveat is missing")
    require("60点" in market_path.get("rules", {}).get("weightingRationale", ""), "market path weighting rationale is missing")
    calibration = market_path.get("calibration") or {}
    for calibration_name in ("vix", "oas"):
        sample = calibration.get(calibration_name) or {}
        require(sample.get("sampleCount", 0) >= 200, f"{calibration_name}: threshold sample is too small")
        require(len(sample.get("thresholds") or []) == 4, f"{calibration_name}: threshold audit is incomplete")
        for threshold in sample["thresholds"]:
            require(0 <= threshold["percentileRank"] <= 100, f"{calibration_name}: percentile rank is invalid")
    require("直近3年" in str((calibration.get("oas") or {}).get("historyNote")), "OAS history-limit note missing")
    require((calibration.get("oas") or {}).get("maximum", 99) < 5, "OAS public sample should not claim 5% observation")
    require("20年" in str((calibration.get("vix") or {}).get("historyNote")), "VIX history note missing")
    basket_audit = calibration.get("basket") or {}
    require(basket_audit.get("constituentCount") == 8, "basket audit must describe eight companies")
    require(close_enough(basket_audit.get("oneStockSharePct"), 12.5), "one-stock breadth share must be 12.5%")
    require("生存者" in basket_audit.get("selectionWarning", ""), "basket survivorship warning is missing")

    en_ai = sakakibara.get("enAiProxy") or []
    diversified_tickers = {company["ticker"] for company in companies if company.get("category") == "japan-diversified"}
    require(len(en_ai) == 8, "EN-AI proxy must contain 8 diversified companies")
    require(len({row["ticker"] for row in en_ai}) == 8, "EN-AI proxy contains duplicate tickers")
    for row in en_ai:
        require(row["ticker"] in diversified_tickers, f"EN-AI proxy includes non-diversified ticker: {row['ticker']}")
        require(row.get("score") is None or 0 <= row["score"] <= 100, f"EN-AI proxy score out of range: {row['ticker']}")
        require(row.get("coveragePct") is None or 0 <= row["coveragePct"] <= 100, f"EN-AI proxy coverage out of range: {row['ticker']}")
    notes = sakakibara.get("methodNotes") or {}
    require("価格加重" in notes.get("indexCorrection", ""), "Nikkei price-weight correction is missing")
    require("証明" in notes.get("flowCaveat", ""), "fund-flow caveat is missing")
    require("正式" in notes.get("classificationCaveat", ""), "EN-AI proxy caveat is missing")

    jgb = data.get("macro", {}).get("jgb10y") or {}
    require(finite(jgb.get("tenYearPct")) and 0 <= jgb["tenYearPct"] <= 10, "10-year JGB yield is invalid")
    jgb_day = date.fromisoformat(jgb["date"])
    require(0 <= (generated - jgb_day).days <= 14, "10-year JGB yield is future-dated or stale")

    episodes = data["market"].get("historicalEpisodes") or []
    require(len(episodes) == 6, "historical episode count must be 6")
    for episode in episodes:
        require(episode["troughDate"] >= episode["peakDate"], f"{episode['id']}: trough precedes peak")
        calculated = (1 - episode["trough"] / episode["peak"]) * 100
        require(abs(calculated - episode["drawdownPct"]) < 1e-8, f"{episode['id']}: drawdown identity failed")

    dotcom = data["market"].get("dotComComparison") or {}
    require(dotcom.get("window", {}).get("startDate") == "2000-03-10", "dot-com comparison start date changed")
    require(dotcom.get("window", {}).get("endDate") == "2002-10-09", "dot-com comparison end date changed")
    require(dotcom.get("japanExtendedEndDate") == "2003-04-28", "Japan extended comparison date changed")
    require("調整後終値" in dotcom.get("priceBasis", ""), "adjusted-close basis is missing")
    dotcom_rows = dotcom.get("rows") or []
    require(len(dotcom_rows) == 12, f"dot-com comparison must contain 12 series, got {len(dotcom_rows)}")
    dotcom_counts = {
        group: sum(1 for row in dotcom_rows if row.get("group") == group)
        for group in ("direct-tech", "broad-market", "tech-sensitive", "non-tech")
    }
    require(
        dotcom_counts == {"direct-tech": 4, "broad-market": 2, "tech-sensitive": 2, "non-tech": 4},
        f"dot-com group counts changed: {dotcom_counts}",
    )

    dotcom_by_id: dict[str, dict[str, Any]] = {}
    for row in dotcom_rows:
        row_id = row["id"]
        require(row_id not in dotcom_by_id, f"duplicate dot-com comparison id: {row_id}")
        dotcom_by_id[row_id] = row
        for field in ("startAdjustedClose", "endAdjustedClose", "peakAdjustedClose", "troughAdjustedClose"):
            require(finite(row.get(field)) and row[field] > 0, f"{row_id}: invalid {field}")
        expected_return = (row["endAdjustedClose"] / row["startAdjustedClose"] - 1) * 100
        expected_drawdown = (1 - row["troughAdjustedClose"] / row["peakAdjustedClose"]) * 100
        require(close_enough(expected_return, row["windowReturnPct"]), f"{row_id}: same-window return identity failed")
        require(close_enough(expected_drawdown, row["maxDrawdownPct"]), f"{row_id}: max-drawdown identity failed")
        require(date.fromisoformat(row["startDate"]) <= date.fromisoformat(row["peakDate"]), f"{row_id}: peak precedes window")
        require(date.fromisoformat(row["peakDate"]) <= date.fromisoformat(row["troughDate"]), f"{row_id}: trough precedes peak")
        require(date.fromisoformat(row["troughDate"]) <= date.fromisoformat(row["endDate"]), f"{row_id}: trough exceeds window")
        require(row.get("sourceUrl", "").startswith("https://"), f"{row_id}: price source is missing")
        require(row.get("classificationSourceUrl", "").startswith("https://"), f"{row_id}: classification source is missing")
        if row.get("extendedMaxDrawdownPct") is not None:
            for field in ("extendedPeakAdjustedClose", "extendedTroughAdjustedClose"):
                require(finite(row.get(field)) and row[field] > 0, f"{row_id}: invalid {field}")
            expected_extended = (1 - row["extendedTroughAdjustedClose"] / row["extendedPeakAdjustedClose"]) * 100
            require(close_enough(expected_extended, row["extendedMaxDrawdownPct"]), f"{row_id}: extended drawdown identity failed")
            require(
                date.fromisoformat(row["extendedPeakDate"]) <= date.fromisoformat(row["extendedTroughDate"])
                <= date.fromisoformat(dotcom["japanExtendedEndDate"]),
                f"{row_id}: extended dates are invalid",
            )

    summaries = {row["group"]: row for row in dotcom.get("groupSummaries") or []}
    require(set(summaries) == set(dotcom_counts), "dot-com group summaries are incomplete")
    for group, count in dotcom_counts.items():
        group_rows = [row for row in dotcom_rows if row["group"] == group]
        summary = summaries[group]
        require(summary.get("count") == count, f"{group}: summary count changed")
        require(
            close_enough(summary["medianWindowReturnPct"], statistics.median(row["windowReturnPct"] for row in group_rows)),
            f"{group}: median same-window return failed",
        )
        require(
            close_enough(summary["medianMaxDrawdownPct"], statistics.median(row["maxDrawdownPct"] for row in group_rows)),
            f"{group}: median max drawdown failed",
        )
        extended = [row["extendedMaxDrawdownPct"] for row in group_rows if row.get("extendedMaxDrawdownPct") is not None]
        if extended:
            require(
                close_enough(summary["medianExtendedMaxDrawdownPct"], statistics.median(extended)),
                f"{group}: median extended drawdown failed",
            )

    require(close_enough(dotcom_by_id["nasdaq"]["maxDrawdownPct"], 77.93238628593402), "NASDAQ anchor changed")
    require(close_enough(dotcom_by_id["sox"]["maxDrawdownPct"], 83.93823258107899), "SOX anchor changed")
    require(close_enough(dotcom_by_id["nikkei"]["maxDrawdownPct"], 59.01092793920164), "Nikkei anchor changed")
    require(close_enough(dotcom_by_id["toyota"]["maxDrawdownPct"], 51.13091658380207), "Toyota history anchor changed")
    require(close_enough(dotcom_by_id["sony"]["maxDrawdownPct"], 73.32381565173569), "Sony history anchor changed")
    require(dotcom_by_id["sony"]["group"] == "tech-sensitive", "Sony must not be labelled non-tech in the 2000 comparison")
    require(dotcom_by_id["honda"]["windowReturnPct"] > 0, "Honda endpoint example must remain positive")
    require(dotcom_by_id["honda"]["maxDrawdownPct"] >= 35, "Honda interim drawdown example is missing")
    require("因果" in dotcom.get("overlapWarning", ""), "overlapping-shock warning is missing")
    require("生存者バイアス" in dotcom.get("selectionWarning", ""), "survivorship warning is missing")

    require("highYieldOas" in data.get("macro", {}), "FRED high-yield OAS is missing")

    margin = json.loads(MARGIN_DATA_FILE.read_text(encoding="utf-8"))
    require(margin.get("schemaVersion") == 1, "margin-debt schemaVersion must be 1")
    margin_rows = margin.get("series") or []
    margin_latest = margin.get("latest") or {}
    require(len(margin_rows) >= 800, "margin-debt/GDP history is too short")
    require(margin_rows[0].get("date") == "1959-01-01", "margin-debt history must start in January 1959")
    require(margin_rows[-1].get("date") == margin_latest.get("date"), "margin-debt latest row is not synchronized")
    require(margin_latest.get("date", "") >= "2026-06-01", "FINRA margin-debt series is stale")
    require(all(margin_rows[index]["date"] < margin_rows[index + 1]["date"] for index in range(len(margin_rows) - 1)), "margin-debt history is not strictly chronological")
    require(all(finite(row.get("marginDebtUsdMillions")) and row["marginDebtUsdMillions"] > 0 for row in margin_rows), "margin-debt history contains invalid balances")
    require(all(finite(row.get("nominalGdpUsdBillions")) and row["nominalGdpUsdBillions"] > 0 for row in margin_rows), "margin-debt history contains invalid GDP")
    latest_margin_row = margin_rows[-1]
    expected_margin_ratio = latest_margin_row["marginDebtUsdMillions"] / (latest_margin_row["nominalGdpUsdBillions"] * 1000) * 100
    require(close_enough(latest_margin_row["marginDebtToGdpPct"], expected_margin_ratio, relative=1e-4), "margin-debt/GDP identity failed")
    require(close_enough(margin_latest["marginDebtToGdpPct"], latest_margin_row["marginDebtToGdpPct"]), "margin-debt latest ratio changed between summary and series")
    require(margin_latest["marginDebtUsdMillions"] == latest_margin_row["marginDebtUsdMillions"], "margin-debt latest balance changed between summary and series")
    require(date.fromisoformat(margin_latest["nominalGdpDate"]) <= date.fromisoformat(margin_latest["date"]), "margin-debt ratio uses a future GDP quarter")
    margin_by_date = {row["date"]: row for row in margin_rows}
    latest_observed = date.fromisoformat(margin_latest["date"])
    prior_year_key = f"{latest_observed.year - 1:04d}-{latest_observed.month:02d}-01"
    prior_year_debt = margin_by_date[prior_year_key]["marginDebtUsdMillions"]
    expected_margin_yoy = (margin_latest["marginDebtUsdMillions"] / prior_year_debt - 1) * 100
    require(close_enough(margin_latest["marginDebtChange12mPct"], expected_margin_yoy, relative=1e-4), "margin-debt YoY identity failed")
    comparable_ratios = [
        row["marginDebtToGdpPct"] for row in margin_rows if row["date"] >= "2010-02-01"
    ]
    expected_percentile = sum(1 for value in comparable_ratios if value <= margin_latest["marginDebtToGdpPct"]) / len(comparable_ratios) * 100
    require(close_enough(margin_latest["ratioPercentileSince2010Pct"], expected_percentile, relative=1e-4), "margin-debt comparable-period percentile failed")
    regimes = margin.get("sourceRegimes") or []
    require(len(regimes) == 3, "margin-debt source-regime boundaries are missing")
    require(regimes[0].get("start") == "1959-01-01", "NYSE source regime start changed")
    require(regimes[2].get("start") == "2010-02-01", "FINRA reporting-population regime boundary changed")
    require("報告対象会員会社" in regimes[2].get("label", ""), "FINRA reporting population label is imprecise")
    require("全会員会社が一律" in regimes[2].get("importantLimit", ""), "FINRA all-member-firms caveat is missing")
    margin_events = margin.get("events") or []
    require(len(margin_events) == 8, "margin-debt chart must contain eight historical observation markers")
    require(any(row.get("date") == "2000-03-01" for row in margin_events), "dot-com margin-debt marker is missing")
    require(any(row.get("date") == "2007-07-01" for row in margin_events), "pre-GFC margin-debt marker is missing")
    period_names = " ".join(row.get("label", "") for row in margin_events)
    require("ITバブルの天井" in period_names, "dot-com period name is missing")
    require("ブラックマンデー" in period_names and "住宅・信用バブル" in period_names, "historical period names are incomplete")
    require("AI・半導体集中相場" in period_names, "current AI-market period name is missing")
    require(all(row.get("chartLabel") and row.get("description") for row in margin_events), "margin event chart labels or descriptions are missing")
    korea = margin.get("koreaStressCase") or {}
    require(close_enough(korea.get("forcedLiquidationsKrwTrillions"), 1.1228), "Korea forced-liquidation fact changed")
    require(korea.get("circuitBreakers") == 3, "Korea circuit-breaker fact changed")
    require(close_enough(korea.get("vkospiIntradayHigh"), 97.78), "Korea VKOSPI fact changed")
    margin_limits = " ".join(margin.get("limits") or [])
    require("単独では暴落時期を予測しません" in margin_limits, "margin-debt timing limitation is missing")
    require("デリバティブ" in margin_limits and "海外口座" in margin_limits, "margin-debt coverage limitation is missing")

    money = json.loads(MONEY_DATA_FILE.read_text(encoding="utf-8"))
    money_series = money.get("series") or {}
    money_history = money_series.get("history") or []
    require("linear scale from zero" in money_series.get("definition", ""), "Money Strategist chart definition must disclose the zero-based linear scale")
    require(len(money_history) >= 1500, "Money Strategist long-run history is too short")
    require(money_history[0].get("date") == "1900-01-01", "Money Strategist history must start in 1900")
    require(money_history[-1].get("date") == money_series.get("latestDate"), "Money Strategist latest date is not synchronized")
    require(close_enough(money_history[-1]["value"], money_series["latestValue"], relative=1e-5), "Money Strategist latest value identity failed")
    require(all(finite(row.get("value")) and row["value"] > 0 for row in money_history), "Money Strategist history contains invalid prices")
    require(all(money_history[index]["date"] <= money_history[index + 1]["date"] for index in range(len(money_history) - 1)), "Money Strategist history is not chronological")
    boundary_text = " ".join(money_series.get("boundaryNotes") or [])
    require("1900～1927年" in boundary_text and "1957年3月4日" in boundary_text, "Money Strategist series-boundary disclosure is missing")

    inflation = money.get("inflation") or {}
    cpi_history = inflation.get("history") or []
    require(inflation.get("seriesId") == "CPIAUCNS", "Money Strategist CPI-U series id is missing")
    require(inflation.get("units") == "Index 1982-1984=100", "Money Strategist CPI-U units changed")
    require(len(cpi_history) >= 1300, "Money Strategist CPI-U history is too short")
    require(cpi_history[0].get("date") == "1913-01-01", "Money Strategist CPI-U must start in January 1913")
    require(cpi_history[-1].get("date") == inflation.get("latestDate"), "Money Strategist CPI-U latest date is not synchronized")
    require(close_enough(cpi_history[-1]["value"], inflation["latestValue"], relative=1e-6), "Money Strategist CPI-U latest identity failed")
    require(all(finite(row.get("value")) and row["value"] > 0 for row in cpi_history), "Money Strategist CPI-U contains invalid observations")
    require(all(cpi_history[index]["date"] <= cpi_history[index + 1]["date"] for index in range(len(cpi_history) - 1)), "Money Strategist CPI-U is not chronological")
    require(any(row.get("date") == inflation.get("comparisonBaseDate") for row in money_history), "Stock series lacks the CPI comparison base date")
    require(any(row.get("date") == inflation.get("comparisonBaseDate") for row in cpi_history), "CPI series lacks the comparison base date")
    cpi_base = next(row["value"] for row in cpi_history if row.get("date") == inflation.get("comparisonBaseDate"))
    stock_base = next(row["value"] for row in money_history if row.get("date") == inflation.get("comparisonBaseDate"))
    require(inflation["latestValue"] / cpi_base > 30, "CPI long-run multiple is implausibly low")
    require(money_series["latestValue"] / stock_base > 500, "Stock long-run multiple is implausibly low")
    require((money_series["latestValue"] / stock_base) / (inflation["latestValue"] / cpi_base) > 10, "Real stock multiple is implausibly low")

    calendar = money.get("marketCalendar") or {}
    events = calendar.get("events") or []
    require(any(row.get("date") == "2026-11-03" and row.get("type") == "election" for row in events), "2026 midterm election marker is missing")
    require(any(row.get("date") == "2028-11-07" and row.get("type") == "election" for row in events), "2028 presidential election marker is missing")
    require(sum(1 for row in events if row.get("type") == "fomc") >= 13, "2026-2028 FOMC schedule is incomplete")
    require(len(calendar.get("earningsWindows") or []) >= 10, "2026-2028 earnings observation windows are incomplete")
    require("未公表" in (calendar.get("ipoWatch") or {}).get("notScheduledReason", ""), "IPO uncertainty disclosure is missing")

    crashes = money.get("crashes") or []
    require(len(crashes) == 10, "Money Strategist chart must contain ten audited crash episodes")
    require(sum(1 for row in crashes if row.get("calculationBasis") == "月次平均系列") == 1, "Only the 1907 episode should use the monthly reconstruction")
    for crash in crashes:
        require(date.fromisoformat(crash["peakDate"]) <= date.fromisoformat(crash["troughDate"]), f"{crash['id']}: trough precedes peak")
        expected_drawdown = (1 - crash["troughValue"] / crash["peakValue"]) * 100
        require(abs(expected_drawdown - crash["drawdownPct"]) <= 0.051, f"{crash['id']}: drawdown identity failed")

    marker = money.get("japanBubbleMarker") or {}
    require(marker.get("date") == "1989-12-29", "Japan bubble marker date changed")
    require(close_enough(marker.get("sp500Value"), 353.4, relative=1e-4), "Japan bubble S&P marker changed")

    forecast = money.get("forecast") or {}
    require(forecast.get("asOfDate") == "2026-07-17", "Money Strategist scenario base date changed")
    path = forecast.get("illustrativePath") or []
    require(len(path) == 3, "Money Strategist blue path must contain exactly three points")
    require(path[-1].get("date") == "2027-05-31", "Money Strategist blue path must stop in May 2027")
    require(close_enough(path[0]["value"], forecast["baseValue"]), "Money Strategist scenario base identity failed")
    require(close_enough(path[1]["value"], forecast["baseValue"] * 0.82, relative=1e-5), "Money Strategist 18% scenario identity failed")
    require(close_enough(path[2]["value"], forecast["baseValue"] * 0.70, relative=1e-5), "Money Strategist 30% scenario identity failed")
    require(max(date.fromisoformat(row["date"]) for row in path) < date(2027, 6, 1), "Blue scenario invents a post-May-2027 price target")
    windows = forecast.get("riskWindows") or []
    require(len(windows) == 3 and windows[-1].get("end") == "2028-12-31", "Money Strategist risk windows must extend through 2028 without a price target")
    require("正式予測線ではない" in forecast.get("importantLimit", ""), "Money Strategist scenario caveat is missing")

    midterm = (money.get("audit") or {}).get("midtermYears") or {}
    observations = midterm.get("observations") or []
    require(len(observations) == 19, "Midterm-year audit must contain 19 observations")
    values = [row["maxDrawdownPct"] for row in observations]
    require(close_enough(midterm["meanMaxDrawdownPct"], statistics.mean(values), relative=1e-3), "Midterm-year mean identity failed")
    require(close_enough(midterm["medianMaxDrawdownPct"], statistics.median(values), relative=1e-3), "Midterm-year median identity failed")
    signals = (money.get("audit") or {}).get("currentSignals") or {}
    require(close_enough(signals["top10WeightPct"]["value"], 36.4), "S&P top-ten weight audit changed")
    require(close_enough(signals["nyFedRecessionProbabilityPct"]["value"], 16.0619), "NY Fed probability correction changed")

    app_source = APP_FILE.read_text(encoding="utf-8")
    index_source = INDEX_FILE.read_text(encoding="utf-8")
    referenced_ids = set(re.findall(r'byId\("([^"]+)"\)', app_source))
    html_id_list = re.findall(r'\bid="([^"]+)"', index_source)
    html_ids = set(html_id_list)
    require(len(html_id_list) == len(html_ids), "index.html contains duplicate element ids")
    missing_ids = sorted(referenced_ids - html_ids)
    require(not missing_ids, f"app.js references missing HTML ids: {missing_ids}")

    require(SNAPSHOT_HISTORY_INDEX.exists(), "daily snapshot history index is missing")
    snapshot_index = json.loads(SNAPSHOT_HISTORY_INDEX.read_text(encoding="utf-8"))
    snapshots = snapshot_index.get("snapshots") or []
    require(len(snapshots) >= 2, "daily snapshot history must preserve the prior and current update")
    snapshot_dates = [row.get("snapshotDate") for row in snapshots]
    require(snapshot_dates == sorted(set(snapshot_dates)), "snapshot dates must be unique and sorted")
    for entry in snapshots:
        snapshot_file = SNAPSHOT_HISTORY_INDEX.parent / entry["file"]
        require(snapshot_file.exists(), f"snapshot file is missing: {entry['file']}")
        snapshot_payload = json.loads(snapshot_file.read_text(encoding="utf-8"))
        require(snapshot_payload.get("generatedAtJst"), f"snapshot timestamp is missing: {entry['file']}")
    require("Method v4.2" in index_source, "method label is missing")
    require("評価への脆弱性は別枠20点" in index_source, "valuation/collapse score separation is missing")
    require("Margin Debt / GDP" in index_source, "margin-debt chart title is missing")
    require("燃料、引き金、巻き戻し" in index_source, "margin-debt three-stage explanation is missing")
    require("FINRA配布Excelを直接取得" in index_source, "FINRA acquisition path is missing")
    require("一般個人の借金総額" in index_source, "FINRA customer-population limitation is missing")
    require("利用者数や平均借入額は逆算できない" in index_source, "FINRA aggregate limitation is missing")
    require("ヘッジや複合戦略" in index_source, "FINRA strategic borrowing caveat is missing")
    require("約1,794億ドル" in index_source and "約6,067億ドル" in index_source, "FINRA versus household margin-loan comparison is missing")
    require("元データが画面の数字になるまで" in index_source, "data journey explanation is missing")
    require("主要データごとの取得経路" in index_source, "source route catalog is missing")
    require("FREDのCSVを系列IDごとに直接取得" in index_source, "FRED retrieval explanation is missing")
    require("SEC EDGAR submissions JSON" in index_source, "SEC retrieval explanation is missing")
    require("marginWorkedFormula" in app_source, "margin-debt worked formula rendering is missing")
    require("source.retrieved_at" in app_source, "source retrieval timestamp rendering is missing")
    require("半導体株の反発だけでは" in index_source, "business-bottom explanation is missing")
    require("margin-debt-history.json" in app_source, "margin-debt browser data load is missing")

    from validate_global_comparison import validate_global_comparison
    validate_global_comparison()

    print(
        "Data and logic audit passed: schema, formulas, coverage, YoY dates, baskets, "
        "automaker DCF overrides, Nikkei reference, Sakakibara rotation and market-path audit, margin debt/GDP, Money Strategist history, CPI, event calendar and scenarios, dot-com spillovers, history, and UI contracts."
    )


if __name__ == "__main__":
    main()
