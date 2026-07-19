#!/usr/bin/env python3
"""Build the local data package for the AI bubble monitor.

The script intentionally runs outside the browser. Market-data providers
restrict CORS or require identifying headers, so a local or scheduled collection job is a
more reliable and auditable place to collect the inputs than visitors' browsers.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import xml.etree.ElementTree as ET
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "latest.json"
MONEY_STRATEGIST_OUTPUT = ROOT / "data" / "money-strategist-history.json"
USER_AGENT = "mxe050-ai-bubble-monitor/1.0 (https://github.com/mxe050)"
JST = timezone(timedelta(hours=9))
NOW = datetime.now(timezone.utc)


COMPANIES: dict[str, dict[str, Any]] = {
    "NVDA": {
        "name": "NVIDIA",
        "group": "AI accelerator",
        "ir": "https://investor.nvidia.com/financial-info/quarterly-results/default.aspx",
        "discount": 0.105,
        "terminal": 0.030,
        "growth": {"bear": 0.08, "base": 0.14, "bull": 0.20},
    },
    "AVGO": {
        "name": "Broadcom",
        "group": "AI networking / ASIC",
        "ir": "https://investors.broadcom.com/financial-information/quarterly-results",
        "discount": 0.095,
        "terminal": 0.030,
        "growth": {"bear": 0.06, "base": 0.11, "bull": 0.16},
    },
    "AMD": {
        "name": "AMD",
        "group": "AI accelerator / CPU",
        "ir": "https://ir.amd.com/financial-information/quarterly-results",
        "discount": 0.105,
        "terminal": 0.030,
        "growth": {"bear": 0.05, "base": 0.11, "bull": 0.18},
    },
    "MU": {
        "name": "Micron",
        "group": "Memory / HBM",
        "ir": "https://investors.micron.com/quarterly-results",
        "discount": 0.110,
        "terminal": 0.025,
        "growth": {"bear": 0.00, "base": 0.07, "bull": 0.13},
    },
    "ARM": {
        "name": "Arm Holdings",
        "group": "CPU architecture",
        "country": "GB",
        "ir": "https://investors.arm.com/financials/quarterly-results",
        "discount": 0.110,
        "terminal": 0.030,
        "growth": {"bear": 0.08, "base": 0.16, "bull": 0.24},
    },
    "MRVL": {
        "name": "Marvell Technology",
        "group": "AI networking / custom silicon",
        "ir": "https://investor.marvell.com/quarterly-results",
        "discount": 0.110,
        "terminal": 0.030,
        "growth": {"bear": 0.04, "base": 0.10, "bull": 0.16},
    },
    "MSFT": {
        "name": "Microsoft",
        "group": "Hyperscaler / software",
        "ir": "https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q3/press-release-webcast",
        "discount": 0.085,
        "terminal": 0.030,
        "growth": {"bear": 0.05, "base": 0.09, "bull": 0.13},
    },
    "GOOGL": {
        "name": "Alphabet",
        "group": "Hyperscaler / advertising",
        "ir": "https://abc.xyz/investor/",
        "discount": 0.090,
        "terminal": 0.030,
        "growth": {"bear": 0.04, "base": 0.08, "bull": 0.12},
    },
    "AMZN": {
        "name": "Amazon",
        "group": "Hyperscaler / commerce",
        "ir": "https://ir.aboutamazon.com/quarterly-results/default.aspx",
        "discount": 0.095,
        "terminal": 0.030,
        "growth": {"bear": 0.05, "base": 0.10, "bull": 0.15},
    },
    "META": {
        "name": "Meta Platforms",
        "group": "Hyperscaler / advertising",
        "ir": "https://investor.atmeta.com/investor-events/",
        "discount": 0.090,
        "terminal": 0.030,
        "growth": {"bear": 0.03, "base": 0.08, "bull": 0.12},
    },
    "6857.T": {
        "name": "アドバンテスト",
        "group": "半導体テスト装置 / AI・HPC",
        "ir": "https://www.advantest.com/en/investors/",
        "discount": 0.105,
        "terminal": 0.020,
        "growth": {"bear": -0.05, "base": 0.04, "bull": 0.10},
        "category": "japan-ai",
        "categoryLabel": "日本・AI連動",
        "displayTicker": "6857",
        "chartLabel": "アドバンテスト",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "半導体テスト装置が主力で、会社自身がAI・HPC向け高性能半導体のテスター需要を成長要因として説明しています。",
        "classificationSourceUrl": "https://www.advantest.com/en/investors/financial-highlights/review/",
        "valuationCaveat": "AI向け需要が強い局面のFCFをそのまま10年延長すると過大評価になり得ます。半導体設備投資サイクルを通した平準化が必要です。",
    },
    "8035.T": {
        "name": "東京エレクトロン",
        "group": "半導体製造装置",
        "ir": "https://www.tel.com/ir/",
        "discount": 0.100,
        "terminal": 0.020,
        "growth": {"bear": -0.03, "base": 0.04, "bull": 0.09},
        "category": "japan-ai",
        "categoryLabel": "日本・AI連動",
        "displayTicker": "8035",
        "chartLabel": "東京エレクトロン",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "先端ロジック・メモリ向け半導体製造装置が主力で、生成AI向け計算基盤の設備投資に収益が連動しやすい企業です。",
        "classificationSourceUrl": "https://www.tel.com/ir/",
        "valuationCaveat": "装置売上は顧客の設備投資計画と輸出規制で大きく変動します。単年FCFより、景気循環を通した平均FCFが重要です。",
    },
    "9984.T": {
        "name": "ソフトバンクグループ",
        "group": "AI投資持株会社 / Arm",
        "ir": "https://group.softbank/en/ir",
        "discount": 0.110,
        "terminal": 0.020,
        "growth": {"bear": -0.10, "base": 0.03, "bull": 0.12},
        "category": "japan-ai",
        "categoryLabel": "日本・AI連動",
        "displayTicker": "9984",
        "chartLabel": "ソフトバンクG",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "ArmとAI関連投資を中核に置く戦略的投資持株会社で、AI資産の評価変動が株主価値へ直接反映されやすい企業です。",
        "classificationSourceUrl": "https://group.softbank/en/ir/financials/annual_reports/2025/who_we_are",
        "valuationCaveat": "投資持株会社は連結FCF型DCFより、保有資産価値から純有利子負債を引くNAV/SOTPが基本です。DCFが算定不可でも企業価値ゼロを意味しません。",
    },
    "6702.T": {
        "name": "富士通",
        "group": "ITサービス / AI・DX",
        "ir": "https://global.fujitsu/en-global/ir/library",
        "discount": 0.090,
        "terminal": 0.015,
        "growth": {"bear": 0.00, "base": 0.03, "bull": 0.07},
        "category": "japan-ai",
        "categoryLabel": "日本・AI連動",
        "displayTicker": "6702",
        "chartLabel": "富士通",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "企業向けITサービスを基盤にAI・DXを提供します。半導体純粋株より間接的ですが、AI導入期待が成長評価へ乗りやすい分類です。",
        "classificationSourceUrl": "https://global.fujitsu/en-global/about",
        "valuationCaveat": "事業再編、資産売却、運転資本でFCFが振れます。継続事業の調整後FCFと受注残を併読する必要があります。",
    },
    "6861.T": {
        "name": "キーエンス",
        "group": "FAセンサー / 画像検査 / 自動化",
        "ir": "https://www.keyence.co.jp/company/financial-info/",
        "discount": 0.090,
        "terminal": 0.020,
        "growth": {"bear": 0.00, "base": 0.04, "bull": 0.07},
        "category": "japan-ai",
        "categoryLabel": "日本・AI連動",
        "displayTicker": "6861",
        "chartLabel": "キーエンス",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "世界各地の製造業へFAセンサー、画像検査、測定機器を直接販売する企業です。AI専業ではありませんが、先端工場、電子部品、データセンター関連の自動化投資と評価が連動しやすい企業として分類します。",
        "classificationSourceUrl": "https://www.keyence.com/about-us/corporate/",
        "valuationCaveat": "高利益率と豊富な現金を持つため、単純なFCF成長率だけでは価値を捉え切れません。製造業の設備投資循環、為替、余剰現金を企業IRで再確認します。",
    },
    "6501.T": {
        "name": "日立製作所",
        "group": "デジタル / 電力・鉄道 / 産業",
        "ir": "https://www.hitachi.com/en/ir/",
        "discount": 0.090,
        "terminal": 0.015,
        "growth": {"bear": 0.00, "base": 0.03, "bull": 0.06},
        "category": "japan-ai",
        "categoryLabel": "日本・AI連動",
        "displayTicker": "6501",
        "chartLabel": "日立製作所",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "Lumadaを軸とするデジタル事業に、電力、鉄道、産業機器の世界的な実装基盤を組み合わせています。純粋なAI企業ではありませんが、AI・DX投資の収益化を企業価値の柱に置くため、この群に分類します。",
        "classificationSourceUrl": "https://www.hitachi.com/en/ir/library/integrated/",
        "valuationCaveat": "事業売却・買収とポートフォリオ再編でFCFが動きます。継続事業の調整後利益、GlobalLogicを含むデジタル成長、受注型事業の運転資本を照合します。",
    },
    "4063.T": {
        "name": "信越化学工業",
        "group": "半導体シリコン / PVC / 機能材料",
        "ir": "https://www.shinetsu.co.jp/en/ir/",
        "discount": 0.095,
        "terminal": 0.015,
        "growth": {"bear": -0.01, "base": 0.03, "bull": 0.06},
        "category": "japan-ai",
        "categoryLabel": "日本・AI連動",
        "displayTicker": "4063",
        "chartLabel": "信越化学",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "半導体シリコンとPVCで世界的な事業基盤を持ち、AI向け半導体の数量拡大と高機能材料需要の恩恵を受けます。PVCという非AIの大型事業もあるため、純粋なAI銘柄ではありません。",
        "classificationSourceUrl": "https://www.shinetsu.co.jp/en/company/",
        "valuationCaveat": "半導体とPVCはいずれも需給循環の影響を受けます。好況期の価格・稼働率を10年延長せず、製品別マージンと設備増強の回収を確認します。",
    },
    "7741.T": {
        "name": "HOYA",
        "group": "医療・眼鏡 / 半導体用光学",
        "ir": "https://www.hoya.com/en/investor/",
        "discount": 0.090,
        "terminal": 0.020,
        "growth": {"bear": 0.01, "base": 0.04, "bull": 0.07},
        "category": "japan-ai",
        "categoryLabel": "日本・AI連動",
        "displayTicker": "7741",
        "chartLabel": "HOYA",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "眼鏡・医療のLife Careと、半導体製造に使うマスクブランクスなどのInformation Technologyを持つ世界的な光学企業です。AI半導体投資への感応部分が明確なため、この群に置きます。",
        "classificationSourceUrl": "https://www.hoya.com/en/company/",
        "valuationCaveat": "医療と半導体関連では成長率と景気感応度が異なります。全社FCFを一つの成長率で延長せず、Life CareとInformation Technologyを分けて確認します。",
    },
    "7267.T": {
        "name": "本田技研工業（ホンダ）",
        "group": "自動車 / 二輪 / 金融サービス",
        "ir": "https://global.honda/en/investors/",
        "discount": 0.095,
        "terminal": 0.010,
        "growth": {"bear": -0.02, "base": 0.015, "bull": 0.04},
        "category": "japan-diversified",
        "categoryLabel": "日本・分散型",
        "displayTicker": "7267",
        "chartLabel": "ホンダ",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "利益の中心は二輪、自動車、金融サービスです。AIを利用していても、現在の利益はAI投資テーマだけで決まる構造ではありません。",
        "classificationSourceUrl": "https://global.honda/en/investors/financial_data/segment.html?links=false",
        "valuationCaveat": "DCFには、Honda公式の非金融事業FCF（FY2022～FY2026）の5年中央値を使用します。自動取得の連結TTM FCFには金融サービスの貸付・回収やリース投資が混ざるため、製造事業の稼ぐ力としてそのまま使いません。なお金融サービス事業の価値は別途加算していないため、基準DCFは全社価値を保守的に見る参考値です。",
        "valuationFcf": 685_867_000_000,
        "valuationFcfBasis": "Honda公式・非金融事業FCFのFY2022～FY2026における5年中央値",
        "valuationFcfFormula": "公式開示FCFの5年中央値。年度値は6781億円、6859億円、1兆4610億円、6659億円、1兆580億円。",
        "valuationFcfPeriod": "FY2022-FY2026",
        "valuationFcfSourceUrl": "https://global.honda/en/investors/financial_data/cashflow.html",
        "valuationFcfSourceLabel": "Honda Cash Flows (Non-financial Services Businesses)",
        "financialServicesTreatment": "金融サービス事業の価値を別加算していないため、残差を直ちに割高・バブルとは判定しません。",
    },
    "7751.T": {
        "name": "キヤノン",
        "group": "印刷 / 映像 / 医療 / 産業機器",
        "ir": "https://global.canon/en/ir/library/results.html",
        "discount": 0.090,
        "terminal": 0.010,
        "growth": {"bear": -0.01, "base": 0.02, "bull": 0.04},
        "category": "japan-diversified",
        "categoryLabel": "日本・分散型",
        "displayTicker": "7751",
        "chartLabel": "キヤノン",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "印刷、映像、医療、産業機器の複数事業を持ちます。半導体製造装置も含みますが、AI需要だけに依存しない分散型です。",
        "classificationSourceUrl": "https://global.canon/en/ir/finance/business-unit-q.html",
        "valuationCaveat": "産業機器には半導体サイクル感応部分があります。全社FCFだけでなく、4事業の構成変化を確認する必要があります。",
    },
    "7203.T": {
        "name": "トヨタ自動車",
        "group": "自動車 / モビリティ / 金融サービス",
        "ir": "https://global.toyota/en/ir/library/",
        "discount": 0.095,
        "terminal": 0.010,
        "growth": {"bear": -0.02, "base": 0.02, "bull": 0.045},
        "category": "japan-diversified",
        "categoryLabel": "日本・分散型",
        "displayTicker": "7203",
        "chartLabel": "トヨタ",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "自動車販売と金融サービスが現在の収益基盤です。AI・自動運転投資は重要でも、AI期待だけで全社価値が決まる企業ではありません。",
        "classificationSourceUrl": "https://global.toyota/en/ir/finance/",
        "valuationCaveat": "DCFには、Toyota公式の非金融事業CFから算出した調整後FCF（FY2022～FY2026）の5年中央値を使用します。自動取得の連結TTM FCFは金融事業、車両リース、証券売買などで大きく振れるため、そのまま全社DCFへ入れません。なお金融サービス事業の価値は別途加算していないため、基準DCFは全社価値を保守的に見る参考値です。",
        "valuationFcf": 2_492_282_000_000,
        "valuationFcfBasis": "Toyota公式・非金融事業CFから算出した調整後FCFのFY2022～FY2026における5年中央値",
        "valuationFcfFormula": "各年の非金融事業営業CF－固定資産取得－リース用設備取得－無形資産取得。5年値は1.45兆円、1.76兆円、4.68兆円、2.49兆円、2.96兆円。",
        "valuationFcfPeriod": "FY2022-FY2026",
        "valuationFcfSourceUrl": "https://global.toyota/pages/global_toyota/ir/financial-results/2026_4q_summary_en.pdf",
        "valuationFcfSourceLabel": "Toyota FY2026 Financial Summary（過去5年は各年度版）",
        "financialServicesTreatment": "金融サービス事業の価値を別加算していないため、残差を直ちに割高・バブルとは判定しません。",
    },
    "9983.T": {
        "name": "ファーストリテイリング",
        "group": "アパレル小売 / 消費",
        "ir": "https://www.fastretailing.com/eng/ir/index.html",
        "discount": 0.095,
        "terminal": 0.020,
        "growth": {"bear": 0.02, "base": 0.05, "bull": 0.08},
        "category": "japan-diversified",
        "categoryLabel": "日本・分散型",
        "displayTicker": "9983",
        "chartLabel": "ファーストリテイリング",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "UNIQLOを中心とする世界的な衣料小売で、主な価値要因は店舗生産性、商品、為替、消費需要です。AI相場との直接連動は比較的小さい分類です。",
        "classificationSourceUrl": "https://www.fastretailing.com/eng/ir/financial/summary.html",
        "valuationCaveat": "海外出店、為替、在庫、リース負債の影響が大きく、単純な成熟小売の成長率を当てはめないことが重要です。",
    },
    "6758.T": {
        "name": "ソニーグループ",
        "group": "ゲーム / 音楽・映画 / イメージセンサー",
        "ir": "https://www.sony.com/en/SonyInfo/IR/",
        "discount": 0.095,
        "terminal": 0.015,
        "growth": {"bear": 0.00, "base": 0.03, "bull": 0.06},
        "category": "japan-diversified",
        "categoryLabel": "日本・分散型",
        "displayTicker": "6758",
        "chartLabel": "ソニーG",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "PlayStation、音楽、映画、イメージセンサーという世界市場の複数事業を持ちます。AI半導体の恩恵はありますが、コンテンツとネットワーク収益が大きいため分散型に分類します。",
        "classificationSourceUrl": "https://www.sony.com/en/SonyInfo/IR/library/presen/business_segment_meeting/",
        "valuationCaveat": "ゲーム機サイクル、ヒット作品、音楽権利、イメージセンサー投資で利益の質が異なります。全社FCFだけでなくセグメント別資本配分を確認します。",
    },
    "7974.T": {
        "name": "任天堂",
        "group": "ゲーム機 / ソフトウェア / IP",
        "ir": "https://www.nintendo.co.jp/ir/en/index.html",
        "discount": 0.095,
        "terminal": 0.015,
        "growth": {"bear": -0.02, "base": 0.02, "bull": 0.06},
        "category": "japan-diversified",
        "categoryLabel": "日本・分散型",
        "displayTicker": "7974",
        "chartLabel": "任天堂",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "世界的なゲーム機・ソフトウェアと自社IPを持ち、価値の中心はハード普及台数、ソフト販売、デジタル比率、IP活用です。AI設備投資相場との直接連動は小さい群です。",
        "classificationSourceUrl": "https://www.nintendo.co.jp/ir/en/index.html",
        "valuationCaveat": "新型機の発売前後で売上・FCFが大きく振れます。単年FCFではなく、ハード1世代を通した平均FCF、為替、豊富な現金を確認します。",
    },
    "6098.T": {
        "name": "リクルートホールディングス",
        "group": "Indeed / 人材・販促 / SaaS",
        "ir": "https://recruit-holdings.com/en/ir/",
        "discount": 0.095,
        "terminal": 0.020,
        "growth": {"bear": 0.01, "base": 0.05, "bull": 0.08},
        "category": "japan-diversified",
        "categoryLabel": "日本・分散型",
        "displayTicker": "6098",
        "chartLabel": "リクルートHD",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "Indeed・Glassdoorを含む世界的なHR Technologyに、国内販促・SaaSと人材派遣を組み合わせています。AIを活用しますが、雇用市場とマッチング収益が主因なので分散型に分類します。",
        "classificationSourceUrl": "https://recruit-holdings.com/en/about/business/",
        "valuationCaveat": "求人市況、クリック単価、採用効率、株式報酬で評価が動きます。景気回復時のFCFだけを延長せず、米国求人需要とIndeedの収益性を確認します。",
    },
    "6367.T": {
        "name": "ダイキン工業",
        "group": "空調・冷凍 / 化学",
        "ir": "https://www.daikin.com/investor",
        "discount": 0.090,
        "terminal": 0.015,
        "growth": {"bear": 0.00, "base": 0.03, "bull": 0.05},
        "category": "japan-diversified",
        "categoryLabel": "日本・分散型",
        "displayTicker": "6367",
        "chartLabel": "ダイキン",
        "currency": "JPY",
        "market": "東証プライム",
        "classificationNote": "世界各地域で空調・冷凍機器とサービスを展開し、海外売上比率が高い企業です。データセンター冷却の成長余地はありますが、住宅・商業空調という幅広い実需が収益を支えます。",
        "classificationSourceUrl": "https://www.daikin.com/investor/financial",
        "valuationCaveat": "地域別需要、為替、在庫、原材料、設備投資でFCFが振れます。データセンター需要だけでなく、北米・アジアの空調販売とアフターサービスを確認します。",
    },
}

OVERSEAS_AI_TICKERS = (
    "NVDA", "AVGO", "AMD", "MU", "ARM", "MRVL", "MSFT", "GOOGL", "AMZN", "META",
)
JAPAN_AI_TICKERS = tuple(
    symbol for symbol, profile in COMPANIES.items() if profile.get("category") == "japan-ai"
)
CHART_TICKERS = tuple(symbol for symbol in OVERSEAS_AI_TICKERS if symbol != "ARM")
PRICE_SYMBOLS = {
    "SOX": "^SOX",
    "NASDAQ": "^IXIC",
    "SP500": "^GSPC",
    "NIKKEI": "^N225",
    "VIX": "^VIX",
    "KIOXIA": "285A.T",
    **{k: k for k in COMPANIES},
}
HYPERSCALERS = {"MSFT", "GOOGL", "AMZN", "META"}


BERKSHIRE_BALANCE_SNAPSHOTS = [
    {
        "periodEnd": "2026-03-31",
        "filingDate": "2026-05-04",
        "cashAndEquivalentsBillion": 51.478,
        "treasuryBillsBillion": 339.261,
        "unsettledTreasuryPayableBillion": 17.229,
        "equitySecuritiesBillion": 288.034,
        "fixedMaturityBillion": 17.669,
        "totalAssetsBillion": 1252.271,
        "sourceUrl": "https://www.sec.gov/Archives/edgar/data/1067983/000119312526202243/brka-20260331.htm",
    },
    {
        "periodEnd": "2025-12-31",
        "filingDate": "2026-02-23",
        "cashAndEquivalentsBillion": 47.719,
        "treasuryBillsBillion": 321.434,
        "unsettledTreasuryPayableBillion": 0.167,
        "equitySecuritiesBillion": 297.778,
        "fixedMaturityBillion": 17.816,
        "totalAssetsBillion": 1222.176,
        "sourceUrl": "https://www.berkshirehathaway.com/2025ar/2025ar.pdf",
    },
]

BERKSHIRE_13F_FALLBACK = [
    {
        "reportDate": "2026-03-31",
        "filingDate": "2026-05-15",
        "accession": "0001193125-26-226661",
        "xmlUrl": "https://www.sec.gov/Archives/edgar/data/1067983/000119312526226661/53405.xml",
        "sourceUrl": "https://www.sec.gov/Archives/edgar/data/1067983/000119312526226661/0001193125-26-226661-index.htm",
    },
    {
        "reportDate": "2025-12-31",
        "filingDate": "2026-02-17",
        "accession": "0001193125-26-054580",
        "xmlUrl": "https://www.sec.gov/Archives/edgar/data/1067983/000119312526054580/50240.xml",
        "sourceUrl": "https://www.sec.gov/Archives/edgar/data/1067983/000119312526054580/0001193125-26-054580-index.html",
    },
]

BERKSHIRE_13F_CHANGE_FALLBACK = {
    "buys": [
        {"name": "Alphabet", "securityClass": "Class A", "latestShares": 54249798, "previousShares": 17846142, "changeShares": 36403656, "changePct": 204.0, "status": "買い増し"},
        {"name": "Delta Air Lines", "securityClass": "Common", "latestShares": 39809456, "previousShares": 0, "changeShares": 39809456, "changePct": None, "status": "新規"},
        {"name": "New York Times", "securityClass": "Class A", "latestShares": 15146535, "previousShares": 5065744, "changeShares": 10080791, "changePct": 199.0, "status": "買い増し"},
        {"name": "Alphabet", "securityClass": "Class C", "latestShares": 3585215, "previousShares": 0, "changeShares": 3585215, "changePct": None, "status": "新規"},
        {"name": "Lennar", "securityClass": "Class A", "latestShares": 10099642, "previousShares": 7050950, "changeShares": 3048692, "changePct": 43.2, "status": "買い増し"},
        {"name": "Macy's", "securityClass": "Common", "latestShares": 3038355, "previousShares": 0, "changeShares": 3038355, "changePct": None, "status": "新規"},
    ],
    "sells": [
        {"name": "Chevron", "securityClass": "Common", "latestShares": 84375856, "previousShares": 130156362, "changeShares": -45780506, "changePct": -35.2, "status": "縮小"},
        {"name": "Constellation Brands", "securityClass": "Class A", "latestShares": 632890, "previousShares": 13000000, "changeShares": -12367110, "changePct": -95.1, "status": "縮小"},
        {"name": "Visa", "securityClass": "Class A", "latestShares": 0, "previousShares": 8297460, "changeShares": -8297460, "changePct": -100.0, "status": "全売却"},
        {"name": "UnitedHealth Group", "securityClass": "Common", "latestShares": 0, "previousShares": 5039564, "changeShares": -5039564, "changePct": -100.0, "status": "全売却"},
        {"name": "Mastercard", "securityClass": "Class A", "latestShares": 0, "previousShares": 3986648, "changeShares": -3986648, "changePct": -100.0, "status": "全売却"},
        {"name": "Amazon", "securityClass": "Common", "latestShares": 0, "previousShares": 2276000, "changeShares": -2276000, "changePct": -100.0, "status": "全売却"},
    ],
}

OVERSEAS_NEWS_QUERIES = (
    "AI semiconductor earnings guidance capex financing when:3d",
    "OpenAI Anthropic IPO tender secondary shares when:7d",
)

NEWS_TOPIC_TERMS = {
    "業績・見通し": ("earnings", "guidance", "revenue", "margin", "forecast", "profit"),
    "AI投資・需要": ("capex", "data center", "datacenter", "gpu", "chip", "semiconductor", "ai spending", "hyperscaler spending"),
    "資金調達・信用": ("financing", "debt", "bond", "default", "credit", "funding"),
    "IPO・株式供給": ("ipo", "lockup", "lock-up", "secondary", "tender", "share sale"),
    "政策・輸出規制": ("export", "tariff", "restriction", "antitrust", "regulation", "sanction"),
    "雇用・コスト": ("layoff", "hiring", "headcount", "jobs", "cost cutting"),
}

PREFERRED_NEWS_SOURCES = (
    "Reuters", "Associated Press", "AP News", "Bloomberg", "Financial Times",
    "The Wall Street Journal", "CNBC", "BBC", "Nikkei Asia", "Morningstar",
)
LOW_SIGNAL_NEWS_SOURCES = ("AOL.com", "24/7 Wall St.", "finance.biggo.com")

HISTORICAL_EPISODES: list[dict[str, str]] = [
    {
        "id": "japan-bubble-first-leg",
        "name": "日本の資産バブル・最初の下落局面",
        "symbol": "^N225",
        "index": "日経平均",
        "start": "1989-01-01",
        "end": "1993-01-01",
        "note": "1989年末の高値から、1992年の安値まで。長期停滞の全期間ではありません。",
    },
    {
        "id": "japan-bubble-secular",
        "name": "日本の資産バブル・長期的な最低値",
        "symbol": "^N225",
        "index": "日経平均",
        "start": "1989-01-01",
        "end": "2009-04-01",
        "note": "複数の景気循環と金融危機を含むため、単一の崩壊局面としては扱いません。",
    },
    {
        "id": "dotcom",
        "name": "米国ITバブル",
        "symbol": "^IXIC",
        "index": "NASDAQ総合",
        "start": "1999-01-01",
        "end": "2003-01-01",
        "note": "技術普及が続いても、過大な期待と無収益企業の評価は大きく修正されました。",
    },
    {
        "id": "gfc-japan",
        "name": "世界金融危機",
        "symbol": "^N225",
        "index": "日経平均",
        "start": "2007-01-01",
        "end": "2009-04-01",
        "note": "信用収縮と世界景気後退が同時に進んだ深い下落です。",
    },
    {
        "id": "covid-japan",
        "name": "コロナ急落",
        "symbol": "^N225",
        "index": "日経平均",
        "start": "2020-01-01",
        "peakEnd": "2020-02-21",
        "end": "2020-12-31",
        "note": "政策対応が速く、底までの期間が短かった外生ショックです。",
    },
    {
        "id": "growth-reset-2021",
        "name": "2021年以降の成長株再評価",
        "symbol": "^IXIC",
        "index": "NASDAQ総合",
        "start": "2021-01-01",
        "end": "2023-02-01",
        "note": "金利上昇で高い評価倍率が縮小した局面です。信用危機とは異なります。",
    },
]

DOTCOM_GROUP_LABELS = {
    "direct-tech": "IT・半導体直撃群",
    "broad-market": "市場全体",
    "tech-sensitive": "技術感応型の複合企業",
    "non-tech": "非ITの実業・ディフェンシブ例",
}

# Fixed historical audit set. Values use Yahoo Finance adjusted closes, retrieved
# and independently recalculated on 2026-07-19. Historical values do not need
# to be downloaded every six hours with the live monitoring data.
DOTCOM_COMPARISON_ROWS: list[dict[str, Any]] = [
    {
        "id": "sox", "symbol": "^SOX", "name": "SOX", "region": "米国", "group": "direct-tech",
        "startDate": "2000-03-10", "endDate": "2002-10-09",
        "startAdjustedClose": 1332.08544921875, "endAdjustedClose": 213.9564666748047,
        "windowReturnPct": -83.93823258107899, "maxDrawdownPct": 83.93823258107899,
        "peakDate": "2000-03-10", "peakAdjustedClose": 1332.08544921875,
        "troughDate": "2002-10-09", "troughAdjustedClose": 213.9564666748047,
        "note": "半導体株の直撃例。AI相場で現在使うSOXの前回サイクルです。",
        "sourceUrl": "https://finance.yahoo.com/quote/%5ESOX/history/",
        "classificationSourceUrl": "https://indexes.nasdaqomx.com/docs/methodology_SOX.pdf",
    },
    {
        "id": "nasdaq", "symbol": "^IXIC", "name": "NASDAQ総合", "region": "米国", "group": "direct-tech",
        "startDate": "2000-03-10", "endDate": "2002-10-09",
        "startAdjustedClose": 5048.6201171875, "endAdjustedClose": 1114.1099853515625,
        "windowReturnPct": -77.93238628593402, "maxDrawdownPct": 77.93238628593402,
        "peakDate": "2000-03-10", "peakAdjustedClose": 5048.6201171875,
        "troughDate": "2002-10-09", "troughAdjustedClose": 1114.1099853515625,
        "note": "ITバブル全体の基準。無収益企業だけでなく大型技術株も大きく再評価されました。",
        "sourceUrl": "https://finance.yahoo.com/quote/%5EIXIC/history/",
        "classificationSourceUrl": "https://indexes.nasdaq.com/docs/Nasdaq-100_A%20Tale%20of%20Three%20Crises%20over%20Two%20Decades.pdf",
    },
    {
        "id": "softbank", "symbol": "9984.T", "name": "ソフトバンクグループ", "region": "日本", "group": "direct-tech",
        "startDate": "2000-03-10", "endDate": "2002-10-09",
        "startAdjustedClose": 1210.5811767578125, "endAdjustedClose": 35.00177001953125,
        "windowReturnPct": -97.10868046756903, "maxDrawdownPct": 97.70544407718896,
        "peakDate": "2000-03-21", "peakAdjustedClose": 1525.4267578125,
        "troughDate": "2002-10-09", "troughAdjustedClose": 35.00177001953125,
        "extendedMaxDrawdownPct": 97.99739155185597, "extendedPeakDate": "2000-03-21",
        "extendedPeakAdjustedClose": 1525.4266357421875, "extendedTroughDate": "2002-11-18",
        "extendedTroughAdjustedClose": 30.548322677612305,
        "note": "当時のインターネット投資・Yahoo! JAPAN関連の代表例です。",
        "sourceUrl": "https://finance.yahoo.com/quote/9984.T/history/",
        "classificationSourceUrl": "https://group.softbank/en/ir/financials/annual_reports",
    },
    {
        "id": "fujitsu", "symbol": "6702.T", "name": "富士通", "region": "日本", "group": "direct-tech",
        "startDate": "2000-03-10", "endDate": "2002-10-09",
        "startAdjustedClose": 2474.442626953125, "endAdjustedClose": 320.2995910644531,
        "windowReturnPct": -87.05568730608032, "maxDrawdownPct": 88.34897914472022,
        "peakDate": "2000-07-04", "peakAdjustedClose": 2749.11181640625,
        "troughDate": "2002-10-09", "troughAdjustedClose": 320.2995910644531,
        "extendedMaxDrawdownPct": 91.89260966920956, "extendedPeakDate": "2000-07-04",
        "extendedPeakAdjustedClose": 2749.11181640625, "extendedTroughDate": "2003-04-14",
        "extendedTroughAdjustedClose": 222.8812255859375,
        "note": "2000年当時『Everything on the Internet』を掲げた日本IT企業の例です。",
        "sourceUrl": "https://finance.yahoo.com/quote/6702.T/history/",
        "classificationSourceUrl": "https://www.fujitsu.com/downloads/IR/annual/2000/all.pdf",
    },
    {
        "id": "sp500", "symbol": "^GSPC", "name": "S&P 500", "region": "米国", "group": "broad-market",
        "startDate": "2000-03-10", "endDate": "2002-10-09",
        "startAdjustedClose": 1395.0699462890625, "endAdjustedClose": 776.760009765625,
        "windowReturnPct": -44.3210706508419, "maxDrawdownPct": 49.14694789846552,
        "peakDate": "2000-03-24", "peakAdjustedClose": 1527.4599609375,
        "troughDate": "2002-10-09", "troughAdjustedClose": 776.760009765625,
        "note": "IT以外も含む米国大型株全体。同時期に景気・利益見通し・リスク許容度の悪化も重なりました。",
        "sourceUrl": "https://finance.yahoo.com/quote/%5EGSPC/history/",
        "classificationSourceUrl": "https://www.spglobal.com/spdji/en/indices/equity/sp-500/",
    },
    {
        "id": "nikkei", "symbol": "^N225", "name": "日経平均", "region": "日本", "group": "broad-market",
        "startDate": "2000-03-10", "endDate": "2002-10-09",
        "startAdjustedClose": 19750.400390625, "endAdjustedClose": 8539.33984375,
        "windowReturnPct": -56.76371276096559, "maxDrawdownPct": 59.01092793920164,
        "peakDate": "2000-04-12", "peakAdjustedClose": 20833.2109375,
        "troughDate": "2002-10-09", "troughAdjustedClose": 8539.33984375,
        "extendedMaxDrawdownPct": 63.48196201902686, "extendedPeakDate": "2000-04-12",
        "extendedPeakAdjustedClose": 20833.2109375, "extendedTroughDate": "2003-04-28",
        "extendedTroughAdjustedClose": 7607.8798828125,
        "note": "日本市場全体の代表。日本では米国の底後も下落が続きました。",
        "sourceUrl": "https://finance.yahoo.com/quote/%5EN225/history/",
        "classificationSourceUrl": "https://indexes.nikkei.co.jp/70th/historyofthemarket-article.html",
    },
    {
        "id": "sony", "symbol": "6758.T", "name": "ソニーグループ", "region": "日本", "group": "tech-sensitive",
        "startDate": "2000-03-10", "endDate": "2002-10-09",
        "startAdjustedClose": 2168.676025390625, "endAdjustedClose": 840.874755859375,
        "windowReturnPct": -61.22635442018522, "maxDrawdownPct": 73.32381565173569,
        "peakDate": "2000-04-03", "peakAdjustedClose": 2478.468505859375,
        "troughDate": "2001-10-03", "troughAdjustedClose": 661.1608276367188,
        "extendedMaxDrawdownPct": 81.63850780457115, "extendedPeakDate": "2000-04-03",
        "extendedPeakAdjustedClose": 2478.468505859375, "extendedTroughDate": "2003-04-28",
        "extendedTroughAdjustedClose": 455.08380126953125,
        "note": "純粋な非ITではありません。当時も電子、ゲーム、半導体、情報技術を持つ技術感応型企業でした。",
        "sourceUrl": "https://finance.yahoo.com/quote/6758.T/history/",
        "classificationSourceUrl": "https://www.sony.com/SonyInfo/IR/library/ar/ar_sony_2000.pdf",
    },
    {
        "id": "canon", "symbol": "7751.T", "name": "キヤノン", "region": "日本", "group": "tech-sensitive",
        "startDate": "2000-03-10", "endDate": "2002-10-09",
        "startAdjustedClose": 1282.737060546875, "endAdjustedClose": 1147.6290283203125,
        "windowReturnPct": -10.53279244687616, "maxDrawdownPct": 41.409101776608914,
        "peakDate": "2000-07-10", "peakAdjustedClose": 1648.12646484375,
        "troughDate": "2001-09-27", "troughAdjustedClose": 965.652099609375,
        "extendedMaxDrawdownPct": 41.409101776608914, "extendedPeakDate": "2000-07-10",
        "extendedPeakAdjustedClose": 1648.12646484375, "extendedTroughDate": "2001-09-27",
        "extendedTroughAdjustedClose": 965.652099609375,
        "note": "情報機器・映像を持つ技術感応型ですが、同じ技術群でもソニーほどは下落しませんでした。",
        "sourceUrl": "https://finance.yahoo.com/quote/7751.T/history/",
        "classificationSourceUrl": "https://global.canon/en/ir/finance/business-unit-q.html",
    },
    {
        "id": "toyota", "symbol": "7203.T", "name": "トヨタ自動車", "region": "日本", "group": "non-tech",
        "startDate": "2000-03-10", "endDate": "2002-10-09",
        "startAdjustedClose": 533.2467041015625, "endAdjustedClose": 328.50933837890625,
        "windowReturnPct": -38.39449248310063, "maxDrawdownPct": 51.13091658380207,
        "peakDate": "2000-04-25", "peakAdjustedClose": 629.9470825195312,
        "troughDate": "2001-09-21", "troughAdjustedClose": 307.849365234375,
        "extendedMaxDrawdownPct": 55.163174726454756, "extendedPeakDate": "2000-04-25",
        "extendedPeakAdjustedClose": 629.9470825195312, "extendedTroughDate": "2003-04-14",
        "extendedTroughAdjustedClose": 282.4482727050781,
        "note": "自動車の実需企業でも最大約51%下落。ITから離れていても、景気・為替・市場全体のリスク回避にさらされます。",
        "sourceUrl": "https://finance.yahoo.com/quote/7203.T/history/",
        "classificationSourceUrl": "https://global.toyota/en/ir/finance/",
    },
    {
        "id": "honda", "symbol": "7267.T", "name": "本田技研工業", "region": "日本", "group": "non-tech",
        "startDate": "2000-03-10", "endDate": "2002-10-09",
        "startAdjustedClose": 337.1329040527344, "endAdjustedClose": 423.2189636230469,
        "windowReturnPct": 25.53475455390344, "maxDrawdownPct": 37.804889508330106,
        "peakDate": "2001-08-02", "peakAdjustedClose": 506.63275146484375,
        "troughDate": "2001-09-20", "troughAdjustedClose": 315.1007995605469,
        "extendedMaxDrawdownPct": 38.56274909704577, "extendedPeakDate": "2002-05-01",
        "extendedPeakAdjustedClose": 528.4743041992188, "extendedTroughDate": "2003-04-25",
        "extendedTroughAdjustedClose": 324.6800842285156,
        "note": "期間末では上昇していても、途中では約38%下落しました。終点だけでは損失体験を捉えられません。",
        "sourceUrl": "https://finance.yahoo.com/quote/7267.T/history/",
        "classificationSourceUrl": "https://global.honda/en/investors/financial_data/segment.html?links=false",
    },
    {
        "id": "kao", "symbol": "4452.T", "name": "花王", "region": "日本", "group": "non-tech",
        "startDate": "2000-03-10", "endDate": "2002-10-09",
        "startAdjustedClose": 855.8982543945312, "endAdjustedClose": 810.174560546875,
        "windowReturnPct": -5.342188001072801, "maxDrawdownPct": 39.882577604212756,
        "peakDate": "2000-04-21", "peakAdjustedClose": 1193.1292724609375,
        "troughDate": "2002-02-06", "troughAdjustedClose": 717.278564453125,
        "extendedMaxDrawdownPct": 43.034734401501765, "extendedPeakDate": "2000-04-21",
        "extendedPeakAdjustedClose": 1193.129150390625, "extendedTroughDate": "2003-04-28",
        "extendedTroughAdjustedClose": 679.669189453125,
        "note": "生活必需品でも途中の最大下落は約40%。ディフェンシブは無傷という意味ではありません。",
        "sourceUrl": "https://finance.yahoo.com/quote/4452.T/history/",
        "classificationSourceUrl": "https://www.kao.com/global/en/investor-relations/",
    },
    {
        "id": "takeda", "symbol": "4502.T", "name": "武田薬品工業", "region": "日本", "group": "non-tech",
        "startDate": "2000-03-10", "endDate": "2002-10-09",
        "startAdjustedClose": 2587.107421875, "endAdjustedClose": 2067.109619140625,
        "windowReturnPct": -20.09958296812847, "maxDrawdownPct": 41.145476885384426,
        "peakDate": "2000-04-04", "peakAdjustedClose": 3308.33740234375,
        "troughDate": "2001-09-12", "troughAdjustedClose": 1947.106201171875,
        "extendedMaxDrawdownPct": 49.85744541895587, "extendedPeakDate": "2000-04-04",
        "extendedPeakAdjustedClose": 3308.33740234375, "extendedTroughDate": "2003-04-16",
        "extendedTroughAdjustedClose": 1658.8848876953125,
        "note": "医薬品でも最大約41%。企業固有要因と市場全体の売却が重なります。",
        "sourceUrl": "https://finance.yahoo.com/quote/4502.T/history/",
        "classificationSourceUrl": "https://www.takeda.com/investors/",
    },
]

FUNDAMENTAL_TYPES = [
    "trailingTotalRevenue",
    "trailingOperatingIncome",
    "trailingFreeCashFlow",
    "trailingCapitalExpenditure",
    "trailingMarketCap",
    "trailingNetIncome",
    "quarterlyTotalRevenue",
    "quarterlyFreeCashFlow",
    "quarterlyCapitalExpenditure",
    "quarterlyCashCashEquivalentsAndShortTermInvestments",
    "quarterlyCashAndCashEquivalents",
    "quarterlyTotalDebt",
    "quarterlyStockholdersEquity",
]


@dataclass
class SourceStatus:
    name: str
    url: str
    ok: bool
    retrieved_at: str
    note: str = ""


def request(
    url: str, *, timeout: int = 35, attempts: int = 3, extra_headers: dict[str, str] | None = None
) -> bytes:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/csv,text/plain,*/*",
    }
    if extra_headers:
        headers.update(extra_headers)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Unable to retrieve {url}: {last_error}")


def get_json(url: str) -> dict[str, Any]:
    return json.loads(request(url).decode("utf-8"))


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


def median(values: Iterable[float | None]) -> float | None:
    usable = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return statistics.median(usable) if usable else None


def moving_average(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < window:
        return out
    total = sum(values[:window])
    out[window - 1] = total / window
    for index in range(window, len(values)):
        total += values[index] - values[index - window]
        out[index] = total / window
    return out


def fetch_price_series(symbol: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(symbol, safe="")
    history_range = "20y" if symbol == "^VIX" else "5y"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range={history_range}&interval=1d&events=div%2Csplits"
    payload = get_json(url)
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    quote = result["indicators"]["quote"][0]
    closes = quote.get("close", [])
    highs = quote.get("high", [])
    lows = quote.get("low", [])
    points: list[dict[str, Any]] = []
    for index, (timestamp, close) in enumerate(zip(timestamps, closes)):
        value = finite(close)
        if value is None:
            continue
        high = finite(highs[index]) if index < len(highs) else None
        low = finite(lows[index]) if index < len(lows) else None
        date = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
        points.append({
            "date": date,
            "close": value,
            "high": high if high is not None else value,
            "low": low if low is not None else value,
        })
    if len(points) < 210:
        raise RuntimeError(f"Insufficient price history for {symbol}")

    values = [row["close"] for row in points]
    sma50 = moving_average(values, 50)
    sma200 = moving_average(values, 200)
    last = values[-1]
    three_year = points[-756:] if len(points) >= 756 else points
    peak_row = max(three_year, key=lambda row: row["close"])
    rows_2026 = [row for row in points if row["date"] >= "2026-01-01"]
    peak_2026_row = max(rows_2026, key=lambda row: row["high"]) if rows_2026 else None
    low_2026_row = min(rows_2026, key=lambda row: row["low"]) if rows_2026 else None
    latest_market_day = datetime.fromisoformat(points[-1]["date"]).date()
    dividend_cutoff = latest_market_day - timedelta(days=365)
    dividends = (result.get("events") or {}).get("dividends") or {}
    trailing_dividend = sum(
        finite(event.get("amount")) or 0.0
        for event in dividends.values()
        if dividend_cutoff <= datetime.fromtimestamp(event["date"], timezone.utc).date() <= latest_market_day
    )
    below_days = 0
    for value, average in reversed(list(zip(values, sma200))):
        if average is not None and value < average:
            below_days += 1
        else:
            break
    latest_sma = sma200[-1]
    latest_sma50 = sma50[-1]
    prior_sma50 = sma50[-21] if len(sma50) >= 21 else None
    recent_120 = points[-120:]
    low_120_index, low_120_row = min(enumerate(recent_120), key=lambda item: item[1]["close"])
    days_since_low_120 = len(recent_120) - 1 - low_120_index
    return {
        "symbol": symbol,
        "date": points[-1]["date"],
        "close": last,
        "change1dPct": pct_change(last, values[-2]) if len(values) > 1 else None,
        "change5dPct": pct_change(last, values[-6]) if len(values) > 5 else None,
        "change20dPct": pct_change(last, values[-21]) if len(values) > 20 else None,
        "change60dPct": pct_change(last, values[-61]) if len(values) > 60 else None,
        "peak3y": peak_row["close"],
        "peak3yDate": peak_row["date"],
        "drawdown3yPct": (1.0 - last / peak_row["close"]) * 100.0,
        "peak2026": peak_2026_row["high"] if peak_2026_row else None,
        "peak2026Date": peak_2026_row["date"] if peak_2026_row else None,
        "drawdownFrom2026HighPct": (1.0 - last / peak_2026_row["high"]) * 100.0 if peak_2026_row else None,
        "low2026": low_2026_row["low"] if low_2026_row else None,
        "low2026Date": low_2026_row["date"] if low_2026_row else None,
        "riseFrom2026LowToHighPct": pct_change(peak_2026_row["high"], low_2026_row["low"]) if peak_2026_row and low_2026_row else None,
        "trailingDividendPerShare": trailing_dividend,
        "trailingDividendYieldPct": trailing_dividend / last * 100.0 if last else None,
        "sma200": latest_sma,
        "belowSma200": bool(latest_sma is not None and last < latest_sma),
        "weeksBelowSma200": below_days / 5.0,
        "sma50": latest_sma50,
        "aboveSma50": bool(latest_sma50 is not None and last > latest_sma50),
        "sma50Slope20dPct": pct_change(latest_sma50, prior_sma50),
        "low120d": low_120_row["close"],
        "low120dDate": low_120_row["date"],
        "tradingDaysSince120dLow": days_since_low_120,
        "reboundFrom120dLowPct": pct_change(last, low_120_row["close"]),
        "history": points,
        "sourceUrl": f"https://finance.yahoo.com/quote/{urllib.parse.quote(symbol)}",
    }



def fetch_topix_series() -> dict[str, Any]:
    """Fetch recent TOPIX closes from Yahoo! Finance Japan's public history table."""

    start_day = NOW.date() - timedelta(days=430)
    end_day = NOW.date() + timedelta(days=1)
    points_by_date: dict[str, dict[str, Any]] = {}
    base = "https://finance.yahoo.co.jp/quote/998405/history"
    for page in range(1, 31):
        query = urllib.parse.urlencode({
            "from": start_day.strftime("%Y%m%d"),
            "to": end_day.strftime("%Y%m%d"),
            "timeFrame": "d",
            "page": page,
        })
        html = request(f"{base}?{query}").decode("utf-8", errors="replace")
        page_rows: list[dict[str, Any]] = []
        for date_text, body in re.findall(
            r'<tr[^>]*>\s*<th[^>]*scope="row"[^>]*>(\d{4}/\d{1,2}/\d{1,2})</th>(.*?)</tr>',
            html,
            flags=re.DOTALL,
        ):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", body, flags=re.DOTALL)
            values: list[float] = []
            for cell in cells[:4]:
                text = re.sub(r"<[^>]+>", "", cell).strip().replace(",", "")
                value = finite(text)
                if value is not None:
                    values.append(value)
            if len(values) != 4:
                continue
            date_value = datetime.strptime(date_text, "%Y/%m/%d").date().isoformat()
            row = {
                "date": date_value,
                "open": values[0],
                "high": values[1],
                "low": values[2],
                "close": values[3],
            }
            points_by_date[date_value] = row
            page_rows.append(row)
        if not page_rows:
            break
        if min(datetime.fromisoformat(row["date"]).date() for row in page_rows) <= start_day:
            break

    points = sorted(points_by_date.values(), key=lambda row: row["date"])
    if len(points) < 120:
        raise RuntimeError("Insufficient TOPIX history from Yahoo! Finance Japan")
    values = [row["close"] for row in points]
    sma50 = moving_average(values, 50)
    sma200 = moving_average(values, 200)
    peak_row = max(points, key=lambda row: row["close"])
    rows_2026 = [row for row in points if row["date"] >= "2026-01-01"]
    peak_2026 = max(rows_2026, key=lambda row: row["high"]) if rows_2026 else None
    last = values[-1]
    return {
        "symbol": "998405",
        "date": points[-1]["date"],
        "close": last,
        "change1dPct": pct_change(last, values[-2]) if len(values) > 1 else None,
        "change5dPct": pct_change(last, values[-6]) if len(values) > 5 else None,
        "change20dPct": pct_change(last, values[-21]) if len(values) > 20 else None,
        "change60dPct": pct_change(last, values[-61]) if len(values) > 60 else None,
        "peak3y": peak_row["close"],
        "peak3yDate": peak_row["date"],
        "drawdown3yPct": (1.0 - last / peak_row["close"]) * 100.0,
        "peak2026": peak_2026["high"] if peak_2026 else None,
        "peak2026Date": peak_2026["date"] if peak_2026 else None,
        "drawdownFrom2026HighPct": (1.0 - last / peak_2026["high"]) * 100.0 if peak_2026 else None,
        "sma50": sma50[-1],
        "sma200": sma200[-1],
        "history": points,
        "sourceUrl": "https://finance.yahoo.co.jp/quote/998405/history",
        "sourceNote": "Yahoo!ファイナンス日本版のTOPIX日次履歴。直近約430日を取得。",
    }


def fetch_mof_jgb_yield() -> dict[str, Any]:
    """Return the latest 10-year constant-maturity JGB yield from MOF Japan."""

    url = "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"
    text = request(url).decode("cp932", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 3:
        raise RuntimeError("MOF JGB CSV has no data rows")
    header = rows[1]
    ten_year_index = header.index("10年")
    observations: list[dict[str, Any]] = []
    for row in rows[2:]:
        if len(row) <= ten_year_index:
            continue
        match = re.fullmatch(r"R(\d+)\.(\d+)\.(\d+)", row[0].strip())
        value = finite(row[ten_year_index])
        if not match or value is None:
            continue
        year = 2018 + int(match.group(1))
        date_value = datetime(year, int(match.group(2)), int(match.group(3))).date().isoformat()
        observations.append({"date": date_value, "tenYearPct": value})
    if not observations:
        raise RuntimeError("MOF JGB CSV contains no valid 10-year observation")
    latest_row = observations[-1]
    return {
        **latest_row,
        "sourceUrl": url,
        "definitionUrl": "https://www.mof.go.jp/jgbs/reference/interest_rate/qa.htm",
        "definition": "財務省が公表する、15時時点の流通市場価格から算出したコンスタント・マチュリティー・ベースの10年国債金利。",
    }


def basket_summary(
    companies: list[dict[str, Any]],
    tickers: tuple[str, ...],
    nikkei: dict[str, Any],
) -> dict[str, Any]:
    rows = [company for company in companies if company["ticker"] in tickers]
    count = len(rows)
    result: dict[str, Any] = {
        "constituents": [row["ticker"] for row in rows],
        "count": count,
    }
    for days in (1, 5, 20, 60):
        key = f"change{days}dPct"
        values = [finite(row.get(key)) for row in rows]
        usable = [value for value in values if value is not None]
        nikkei_value = finite(nikkei.get(key))
        result[f"medianChange{days}dPct"] = median(usable)
        result[f"positive{days}dCount"] = sum(1 for value in usable if value > 0)
        result[f"positive{days}dCoverage"] = len(usable)
        result[f"outperformNikkei{days}dCount"] = (
            sum(1 for value in usable if nikkei_value is not None and value > nikkei_value)
            if nikkei_value is not None else None
        )
    return result


def relative_rank_points(
    rows: list[dict[str, Any]],
    key: str,
    max_points: float,
    *,
    higher_is_better: bool,
) -> dict[str, float | None]:
    usable = [(row["ticker"], finite(row.get(key))) for row in rows]
    usable = [(ticker, value) for ticker, value in usable if value is not None and value > 0]
    if not usable:
        return {row["ticker"]: None for row in rows}
    ordered = sorted(usable, key=lambda item: item[1], reverse=higher_is_better)
    if len(ordered) == 1:
        return {ordered[0][0]: max_points / 2.0}
    return {
        ticker: max_points * (len(ordered) - 1 - index) / (len(ordered) - 1)
        for index, (ticker, _value) in enumerate(ordered)
    }


def build_en_ai_proxy(
    companies: list[dict[str, Any]],
    nikkei: dict[str, Any],
) -> list[dict[str, Any]]:
    """Transparent proxy for the article's proprietary EN-AI universe."""

    rows = [company for company in companies if company.get("category") == "japan-diversified"]
    pe_points = relative_rank_points(rows, "approxTrailingPe", 10.0, higher_is_better=False)
    pb_points = relative_rank_points(rows, "approxPriceToBook", 8.0, higher_is_better=False)
    dividend_points = relative_rank_points(rows, "trailingDividendYieldPct", 7.0, higher_is_better=True)
    nikkei_5d = finite(nikkei.get("change5dPct"))
    nikkei_20d = finite(nikkei.get("change20dPct"))
    output: list[dict[str, Any]] = []
    for company in rows:
        available = 0.0
        earned = 0.0
        quality_earned = 0.0
        quality_available = 0.0

        def add_quality(value: Any, maximum: float, points: float) -> None:
            nonlocal available, earned, quality_earned, quality_available
            if value is None:
                return
            available += maximum
            quality_available += maximum
            earned += points
            quality_earned += points

        fcf = finite(company.get("ttmFreeCashFlow"))
        operating_income = finite(company.get("ttmOperatingIncome"))
        operating_margin = finite(company.get("operatingMarginPct"))
        fcf_margin = finite(company.get("freeCashFlowMarginPct"))
        add_quality(fcf, 12.0, 12.0 if fcf is not None and fcf > 0 else 0.0)
        add_quality(operating_income, 8.0, 8.0 if operating_income is not None and operating_income > 0 else 0.0)
        add_quality(
            operating_margin,
            10.0,
            10.0 if operating_margin is not None and operating_margin >= 15
            else 6.0 if operating_margin is not None and operating_margin >= 8
            else 3.0 if operating_margin is not None and operating_margin > 0 else 0.0,
        )
        add_quality(
            fcf_margin,
            10.0,
            10.0 if fcf_margin is not None and fcf_margin >= 10
            else 6.0 if fcf_margin is not None and fcf_margin >= 5
            else 3.0 if fcf_margin is not None and fcf_margin > 0 else 0.0,
        )

        value_earned = 0.0
        value_available = 0.0
        for points_map, maximum in ((pe_points, 10.0), (pb_points, 8.0), (dividend_points, 7.0)):
            points = points_map.get(company["ticker"])
            if points is None:
                continue
            available += maximum
            value_available += maximum
            earned += points
            value_earned += points

        drawdown = finite(company.get("drawdownFrom2026HighPct"))
        oversold_earned = 0.0
        oversold_available = 0.0
        if drawdown is not None:
            oversold_available = 15.0
            available += 15.0
            oversold_earned = 15.0 if drawdown >= 20 else 10.0 if drawdown >= 10 else 5.0 if drawdown >= 5 else 0.0
            earned += oversold_earned

        rotation_earned = 0.0
        rotation_available = 0.0
        change_20d = finite(company.get("change20dPct"))
        change_5d = finite(company.get("change5dPct"))
        if change_20d is not None and nikkei_20d is not None:
            rotation_available += 10.0
            available += 10.0
            points = 10.0 if change_20d - nikkei_20d >= 5 else 6.0 if change_20d > nikkei_20d else 0.0
            rotation_earned += points
            earned += points
        if change_5d is not None and nikkei_5d is not None:
            rotation_available += 5.0
            available += 5.0
            points = 5.0 if change_5d - nikkei_5d >= 3 else 3.0 if change_5d > nikkei_5d else 0.0
            rotation_earned += points
            earned += points

        output.append({
            "ticker": company["ticker"],
            "name": company["name"],
            "score": earned / available * 100.0 if available >= 50 else None,
            "coveragePct": available / 95.0 * 100.0,
            "qualityScore": quality_earned,
            "qualityMax": quality_available,
            "valueScore": value_earned,
            "valueMax": value_available,
            "oversoldScore": oversold_earned,
            "oversoldMax": oversold_available,
            "rotationScore": rotation_earned,
            "rotationMax": rotation_available,
            "approxTrailingPe": company.get("approxTrailingPe"),
            "approxPriceToBook": company.get("approxPriceToBook"),
            "trailingDividendYieldPct": company.get("trailingDividendYieldPct"),
            "drawdownFrom2026HighPct": company.get("drawdownFrom2026HighPct"),
            "change5dPct": company.get("change5dPct"),
            "change20dPct": company.get("change20dPct"),
        })
    output.sort(key=lambda row: (row["score"] is not None, row["score"] or -1), reverse=True)
    return output


def score_at_or_above(value: Any, bands: list[tuple[float, float]]) -> float | None:
    numeric = finite(value)
    if numeric is None:
        return None
    for threshold, score in bands:
        if numeric >= threshold:
            return score
    return 0.0


def score_at_or_below(value: Any, bands: list[tuple[float, float]]) -> float | None:
    numeric = finite(value)
    if numeric is None:
        return None
    for threshold, score in bands:
        if numeric <= threshold:
            return score
    return 0.0


def market_path_component(
    component_id: str,
    label: str,
    parts: list[tuple[float | None, float]],
    detail: str,
) -> dict[str, Any]:
    maximum = sum(maximum for _, maximum in parts)
    known_maximum = sum(maximum for score, maximum in parts if score is not None)
    observed = sum(score for score, _ in parts if score is not None)
    return {
        "id": component_id,
        "label": label,
        "score": round(observed, 2),
        "knownMax": round(known_maximum, 2),
        "maxScore": round(maximum, 2),
        "coveragePct": round(known_maximum / maximum * 100.0, 1) if maximum else 0.0,
        "detail": detail,
    }


def market_path_axis(components: list[dict[str, Any]]) -> dict[str, Any]:
    raw_score = sum(component["score"] for component in components)
    known_maximum = sum(component["knownMax"] for component in components)
    total_maximum = sum(component["maxScore"] for component in components)
    normalized = raw_score / known_maximum * 100.0 if known_maximum >= 60.0 else None
    return {
        "score": round(normalized, 1) if normalized is not None else None,
        "rawScore": round(raw_score, 2),
        "knownMax": round(known_maximum, 2),
        "maxScore": round(total_maximum, 2),
        "coveragePct": round(known_maximum / total_maximum * 100.0, 1) if total_maximum else 0.0,
        "components": components,
    }


def format_path_value(value: Any, suffix: str = "%") -> str:
    numeric = finite(value)
    if numeric is None:
        return "未確認"
    sign = "+" if numeric > 0 else ""
    return f"{sign}{numeric:.1f}{suffix}"


def threshold_sample(
    rows: list[dict[str, Any]],
    value_key: str,
    thresholds: list[float],
) -> dict[str, Any]:
    usable = [
        {"date": row.get("date"), "value": finite(row.get(value_key))}
        for row in rows
        if finite(row.get(value_key)) is not None
    ]
    if not usable:
        return {"sampleCount": 0, "thresholds": []}
    values = [row["value"] for row in usable]
    return {
        "sampleStartDate": usable[0]["date"],
        "sampleEndDate": usable[-1]["date"],
        "sampleCount": len(values),
        "minimum": min(values),
        "maximum": max(values),
        "thresholds": [
            {
                "value": threshold,
                "percentileRank": round(
                    sum(1 for value in values if value <= threshold) / len(values) * 100.0,
                    1,
                ),
            }
            for threshold in thresholds
        ],
    }


def build_market_path_indicator(
    nikkei: dict[str, Any],
    topix: dict[str, Any],
    vix: dict[str, Any],
    high_yield_oas: dict[str, Any] | None,
    distortion: bool,
    nt_drawdown: float | None,
    nt_change_20d: float | None,
    topix_advantage_5d: float | None,
    topix_advantage_20d: float | None,
    basket_advantage_5d: float | None,
    basket_advantage_20d: float | None,
    japan_diversified: dict[str, Any],
    earnings_fair_value: float,
    book_fair_value: float,
) -> dict[str, Any]:
    diversified_coverage = finite(japan_diversified.get("positive5dCoverage"))
    diversified_positive = finite(japan_diversified.get("positive5dCount"))
    diversified_outperform = finite(japan_diversified.get("outperformNikkei5dCount"))
    positive_pct = (
        diversified_positive / diversified_coverage * 100.0
        if diversified_positive is not None and diversified_coverage else None
    )
    outperform_pct = (
        diversified_outperform / diversified_coverage * 100.0
        if diversified_outperform is not None and diversified_coverage else None
    )

    normalization_components = [
        market_path_component(
            "ntReversal",
            "NT倍率の反転",
            [
                (score_at_or_above(nt_drawdown, [(8.0, 15.0), (5.0, 10.0), (2.5, 5.0)]), 15.0),
                (score_at_or_below(nt_change_20d, [(-6.0, 10.0), (-3.0, 7.0), (-0.01, 3.0)]), 10.0),
            ],
            f"直近ピークから{format_path_value(nt_drawdown).lstrip('+')}低下、20日変化は{format_path_value(nt_change_20d)}。",
        ),
        market_path_component(
            "topixRelative",
            "TOPIXの相対的な強さ",
            [
                (score_at_or_above(topix_advantage_5d, [(3.0, 12.0), (1.0, 8.0), (0.1, 4.0)]), 12.0),
                (score_at_or_above(topix_advantage_20d, [(5.0, 13.0), (2.0, 9.0), (0.1, 4.0)]), 13.0),
            ],
            f"TOPIX優位は5日{format_path_value(topix_advantage_5d, 'ポイント')}、20日{format_path_value(topix_advantage_20d, 'ポイント')}。",
        ),
        market_path_component(
            "basketRotation",
            "分散型株への相対回復",
            [
                (score_at_or_above(basket_advantage_5d, [(6.0, 15.0), (2.0, 10.0), (0.1, 5.0)]), 15.0),
                (score_at_or_above(basket_advantage_20d, [(8.0, 15.0), (4.0, 10.0), (0.1, 5.0)]), 15.0),
            ],
            f"分散型8社のAI連動8社に対する優位は5日{format_path_value(basket_advantage_5d, 'ポイント')}、20日{format_path_value(basket_advantage_20d, 'ポイント')}。",
        ),
        market_path_component(
            "breadth",
            "分散型株への広がり",
            [
                (score_at_or_above(outperform_pct, [(75.0, 10.0), (50.0, 5.0)]), 10.0),
                (score_at_or_above(positive_pct, [(75.0, 10.0), (50.0, 6.0), (25.0, 3.0)]), 10.0),
            ],
            (
                f"5日で日経平均を上回った分散型株は{int(diversified_outperform) if diversified_outperform is not None else '未確認'}/"
                f"{int(diversified_coverage) if diversified_coverage is not None else '未確認'}社、上昇は"
                f"{int(diversified_positive) if diversified_positive is not None else '未確認'}/"
                f"{int(diversified_coverage) if diversified_coverage is not None else '未確認'}社。"
            ),
        ),
    ]

    vix_close = finite(vix.get("close"))
    vix_change_5d = finite(vix.get("change5dPct"))
    oas = high_yield_oas or {}
    oas_value = finite(oas.get("valuePct"))
    oas_rise = finite(oas.get("riseFrom3mLowPctPoints"))
    vix_calibration = threshold_sample(vix.get("history", []), "close", [20.0, 25.0, 30.0, 40.0])
    vix_calibration["historyNote"] = "Yahoo Financeで取得した20年の日次終値。標本内順位は将来確率ではない。"

    panic_components = [
        market_path_component(
            "nikkeiSpeed",
            "日経平均の下落速度",
            [
                (score_at_or_below(nikkei.get("change1dPct"), [(-7.0, 10.0), (-5.0, 7.0), (-3.0, 4.0)]), 10.0),
                (score_at_or_below(nikkei.get("change5dPct"), [(-12.0, 10.0), (-8.0, 7.0), (-5.0, 4.0)]), 10.0),
                (score_at_or_below(nikkei.get("change20dPct"), [(-20.0, 10.0), (-12.0, 7.0), (-8.0, 4.0)]), 10.0),
            ],
            f"日経平均は1日{format_path_value(nikkei.get('change1dPct'))}、5日{format_path_value(nikkei.get('change5dPct'))}、20日{format_path_value(nikkei.get('change20dPct'))}。",
        ),
        market_path_component(
            "broadContagion",
            "市場全体への波及",
            [
                (score_at_or_below(topix.get("change1dPct"), [(-5.0, 8.0), (-3.0, 5.0), (-2.0, 3.0)]), 8.0),
                (score_at_or_below(topix.get("change5dPct"), [(-10.0, 8.0), (-6.0, 5.0), (-3.0, 3.0)]), 8.0),
                (score_at_or_below(topix.get("change20dPct"), [(-15.0, 8.0), (-10.0, 5.0), (-5.0, 3.0)]), 8.0),
                (score_at_or_below(positive_pct, [(25.0, 6.0), (50.0, 3.0)]), 6.0),
            ],
            (
                f"TOPIXは1日{format_path_value(topix.get('change1dPct'))}、5日{format_path_value(topix.get('change5dPct'))}、"
                f"20日{format_path_value(topix.get('change20dPct'))}。分散型8社の5日上昇比率は"
                f"{format_path_value(positive_pct).lstrip('+')}。"
            ),
        ),
        market_path_component(
            "volatility",
            "予想変動率の急上昇",
            [
                (score_at_or_above(vix_close, [(40.0, 12.0), (30.0, 9.0), (25.0, 6.0), (20.0, 3.0)]), 12.0),
                (score_at_or_above(vix_change_5d, [(100.0, 8.0), (50.0, 6.0), (25.0, 3.0), (20.0, 2.0)]), 8.0),
            ],
            f"VIXは{format_path_value(vix_close, '').lstrip('+')}、5日変化は{format_path_value(vix_change_5d)}。VIXは米国S&P 500の30日予想変動率です。",
        ),
        market_path_component(
            "credit",
            "信用市場への波及",
            [
                (score_at_or_above(oas_value, [(6.0, 12.0), (5.0, 9.0), (4.0, 6.0), (3.5, 3.0)]), 12.0),
                (score_at_or_above(oas_rise, [(2.0, 8.0), (1.0, 5.0), (0.5, 3.0)]), 8.0),
            ],
            f"米国HY OASは{format_path_value(oas_value).lstrip('+')}、3か月低値から{format_path_value(oas_rise, 'ポイント')}。信用不安が強いほど上昇します。",
        ),
    ]

    normalization = market_path_axis(normalization_components)
    panic = market_path_axis(panic_components)
    normalization_score = finite(normalization.get("score"))
    panic_score = finite(panic.get("score"))
    route_index = (
        max(-100.0, min(100.0, normalization_score - panic_score))
        if normalization_score is not None and panic_score is not None else None
    )

    if route_index is None:
        status_code = "insufficient"
        label = "データ不足"
    elif panic_score is not None and panic_score >= 65.0 and route_index <= -15.0:
        status_code = "panic"
        label = "パニック型暴落が優勢"
    elif panic_score is not None and panic_score >= 50.0:
        status_code = "mixed"
        label = "正常化にパニックが重なる移行局面"
    elif not distortion:
        status_code = "neutral"
        label = "一極集中の歪みは未確認"
    elif route_index >= 40.0:
        status_code = "normalization-strong"
        label = "揺り戻し・評価正常化が優勢"
    elif route_index >= 15.0:
        status_code = "normalization-watch"
        label = "評価正常化方向だが確認途上"
    elif route_index <= -40.0:
        status_code = "panic"
        label = "パニック型暴落が優勢"
    elif route_index <= -15.0:
        status_code = "panic-watch"
        label = "パニック方向への警戒"
    else:
        status_code = "unclear"
        label = "二つの経路が拮抗"

    current_price = finite(nikkei.get("close"))
    peak_price = finite(nikkei.get("peak2026"))
    lower_anchor = min(earnings_fair_value, book_fair_value)
    upper_anchor = max(earnings_fair_value, book_fair_value)
    valuation_anchor = {
        "currentPrice": current_price,
        "peak2026": peak_price,
        "lower": lower_anchor,
        "upper": upper_anchor,
        "moveFromCurrentToUpperPct": pct_change(upper_anchor, current_price) if current_price else None,
        "moveFromCurrentToLowerPct": pct_change(lower_anchor, current_price) if current_price else None,
        "drawdownFromPeakToUpperPct": (1.0 - upper_anchor / peak_price) * 100.0 if peak_price else None,
        "drawdownFromPeakToLowerPct": (1.0 - lower_anchor / peak_price) * 100.0 if peak_price else None,
    }

    return {
        "label": label,
        "statusCode": status_code,
        "horizon": "直近1・5・20営業日を使うルールベースの方向判定",
        "routeIndex": round(route_index, 1) if route_index is not None else None,
        "normalization": normalization,
        "panic": panic,
        "valuationAnchor": valuation_anchor,
        "inputs": {
            "nikkei1dPct": nikkei.get("change1dPct"),
            "nikkei5dPct": nikkei.get("change5dPct"),
            "nikkei20dPct": nikkei.get("change20dPct"),
            "topix1dPct": topix.get("change1dPct"),
            "topix5dPct": topix.get("change5dPct"),
            "topix20dPct": topix.get("change20dPct"),
            "vix": vix_close,
            "vix5dPct": vix_change_5d,
            "highYieldOasPct": oas_value,
            "highYieldOasRise3mPctPoints": oas_rise,
            "diversifiedPositive5dPct": positive_pct,
        },
        "rules": {
            "formula": "市場経路指数 = 正常化スコア - パニックスコア（-100～+100）",
            "positiveMeaning": "プラスほど、AI期待の剥落と優良Non-AIへの相対回復による評価正常化が優勢。",
            "negativeMeaning": "マイナスほど、TOPIX・分散型株・予想変動率・信用市場まで悪化するパニック型暴落が優勢。",
            "thresholdCaveat": "各配点と閾値は公式の売買基準ではなく、本サイト独自の早期警戒ルール。統計モデルによる確率予測ではない。",
            "weightingRationale": "対象が日経平均の経路なので、日本株の下落速度30点と市場全体への波及30点に計60点を置き、米国の予想変動率20点と信用20点を確認指標として計40点置く。配点は役割分担であり、最適化された暴落確率ではない。",
        },
        "calibration": {
            "vix": vix_calibration,
            "oas": oas.get("calibration"),
            "basket": {
                "constituentCount": int(diversified_coverage) if diversified_coverage is not None else 0,
                "oneStockSharePct": round(100.0 / diversified_coverage, 1) if diversified_coverage else None,
                "medianPivot": "8社の中央値は4番目と5番目の平均で決まり、1～2社の順位変化でも動く小標本。",
                "selectionWarning": "現存し、データ取得でき、現在の事業分類で選んだ代表企業であり、無作為標本ではない。生存者・選択バイアスが入り得る。",
            },
        },
    }


def build_sakakibara_analysis(
    prices: dict[str, dict[str, Any]],
    companies: list[dict[str, Any]],
    jgb: dict[str, Any] | None,
    high_yield_oas: dict[str, Any] | None,
) -> dict[str, Any]:
    nikkei = prices.get("NIKKEI") or {}
    topix = prices.get("TOPIX") or {}
    nikkei_map = {row["date"]: row["close"] for row in nikkei.get("history", [])}
    topix_map = {row["date"]: row["close"] for row in topix.get("history", [])}
    dates = sorted(set(nikkei_map).intersection(topix_map))
    nt_rows = [
        {
            "date": date,
            "nikkei": nikkei_map[date],
            "topix": topix_map[date],
            "ntRatio": nikkei_map[date] / topix_map[date],
        }
        for date in dates
        if topix_map[date] > 0
    ]
    if len(nt_rows) < 60:
        raise RuntimeError("Insufficient aligned Nikkei/TOPIX history for NT ratio")
    recent_nt = nt_rows[-252:]
    peak_nt = max(recent_nt, key=lambda row: row["ntRatio"])
    latest_nt = nt_rows[-1]
    nt_values = [row["ntRatio"] for row in nt_rows]
    nt_change_5d = pct_change(nt_values[-1], nt_values[-6]) if len(nt_values) > 5 else None
    nt_change_20d = pct_change(nt_values[-1], nt_values[-21]) if len(nt_values) > 20 else None
    nt_drawdown = (1.0 - latest_nt["ntRatio"] / peak_nt["ntRatio"]) * 100.0

    japan_ai = basket_summary(companies, JAPAN_AI_TICKERS, nikkei)
    diversified_tickers = tuple(
        company["ticker"] for company in companies
        if company.get("category") == "japan-diversified"
    )
    japan_diversified = basket_summary(companies, diversified_tickers, nikkei)

    topix_advantage_5d = None
    topix_advantage_20d = None
    if finite(topix.get("change5dPct")) is not None and finite(nikkei.get("change5dPct")) is not None:
        topix_advantage_5d = topix["change5dPct"] - nikkei["change5dPct"]
    if finite(topix.get("change20dPct")) is not None and finite(nikkei.get("change20dPct")) is not None:
        topix_advantage_20d = topix["change20dPct"] - nikkei["change20dPct"]

    ai_5d = finite(japan_ai.get("medianChange5dPct"))
    ai_20d = finite(japan_ai.get("medianChange20dPct"))
    diversified_5d = finite(japan_diversified.get("medianChange5dPct"))
    diversified_20d = finite(japan_diversified.get("medianChange20dPct"))
    basket_advantage_5d = diversified_5d - ai_5d if diversified_5d is not None and ai_5d is not None else None
    basket_advantage_20d = diversified_20d - ai_20d if diversified_20d is not None and ai_20d is not None else None

    breadth_coverage = japan_diversified.get("positive5dCoverage") or 0
    outperform_count = japan_diversified.get("outperformNikkei5dCount")
    positive_count = japan_diversified.get("positive5dCount") or 0
    distortion = latest_nt["ntRatio"] >= 15.5 or peak_nt["ntRatio"] >= 16.0
    nt_reversal = nt_drawdown >= 5.0 and nt_change_20d is not None and nt_change_20d < 0
    broad_outperformance = (
        (topix_advantage_5d is not None and topix_advantage_5d >= 1.0)
        or (topix_advantage_20d is not None and topix_advantage_20d >= 2.0)
    )
    basket_rotation = (
        (basket_advantage_5d is not None and basket_advantage_5d >= 2.0)
        or (basket_advantage_20d is not None and basket_advantage_20d >= 4.0)
    )
    breadth_confirmation = bool(
        breadth_coverage
        and outperform_count is not None
        and (
            outperform_count / breadth_coverage >= 0.75
            or (
                finite(nikkei.get("change5dPct")) is not None
                and nikkei["change5dPct"] < 0
                and positive_count / breadth_coverage >= 0.5
            )
        )
    )
    gates = {
        "distortion": distortion,
        "ntReversal": nt_reversal,
        "broadOutperformance": broad_outperformance,
        "basketRotation": basket_rotation,
        "breadthConfirmation": breadth_confirmation,
    }
    confirmation_count = sum(1 for key, value in gates.items() if key != "distortion" and value)
    if not distortion:
        stage = "通常域"
    elif confirmation_count >= 4:
        stage = "揺り戻しを強く確認"
    elif confirmation_count == 3:
        stage = "揺り戻し進行と整合"
    elif confirmation_count == 2:
        stage = "初期兆候"
    else:
        stage = "歪みはあるが揺り戻し未確認"

    kioxia = prices.get("KIOXIA") or {}
    kioxia_article_start = next(
        (row for row in kioxia.get("history", []) if row["date"] == "2026-03-31"),
        None,
    )
    target_pb = 1.106 ** 5
    article_earnings_fair_value = 3682.0 * 16.6
    article_book_fair_value = 34859.0 * target_pb
    market_path = build_market_path_indicator(
        nikkei,
        topix,
        prices.get("VIX") or {},
        high_yield_oas,
        distortion,
        nt_drawdown,
        nt_change_20d,
        topix_advantage_5d,
        topix_advantage_20d,
        basket_advantage_5d,
        basket_advantage_20d,
        japan_diversified,
        article_earnings_fair_value,
        article_book_fair_value,
    )
    return {
        "asOfDate": latest_nt["date"],
        "methodLabel": "榊原式 proxy v1.1",
        "stage": stage,
        "confirmationCount": confirmation_count,
        "confirmationMax": 4,
        "gates": gates,
        "ntRatio": {
            "latest": latest_nt["ntRatio"],
            "latestDate": latest_nt["date"],
            "peak252d": peak_nt["ntRatio"],
            "peak252dDate": peak_nt["date"],
            "declineFromPeakPct": nt_drawdown,
            "change5dPct": nt_change_5d,
            "change20dPct": nt_change_20d,
            "average20d": statistics.mean(nt_values[-20:]),
            "average60d": statistics.mean(nt_values[-60:]),
            "history": nt_rows[-260:],
            "historicalReference": [
                {"date": "2021-03", "value": 15.68},
                {"date": "2025-11", "value": 15.78},
                {"date": "2026-06-25", "value": 18.02},
            ],
        },
        "relativeMarket": {
            "nikkei": {
                "change5dPct": nikkei.get("change5dPct"),
                "change20dPct": nikkei.get("change20dPct"),
            },
            "topix": {
                "change5dPct": topix.get("change5dPct"),
                "change20dPct": topix.get("change20dPct"),
            },
            "topixAdvantage5dPctPoints": topix_advantage_5d,
            "topixAdvantage20dPctPoints": topix_advantage_20d,
        },
        "japanAiBasket": japan_ai,
        "japanDiversifiedBasket": japan_diversified,
        "basketAdvantage5dPctPoints": basket_advantage_5d,
        "basketAdvantage20dPctPoints": basket_advantage_20d,
        "marketPath": market_path,
        "kioxiaCase": {
            "date": kioxia.get("date"),
            "close": kioxia.get("close"),
            "low2026": kioxia.get("low2026"),
            "low2026Date": kioxia.get("low2026Date"),
            "peak2026": kioxia.get("peak2026"),
            "peak2026Date": kioxia.get("peak2026Date"),
            "riseFrom2026LowToHighPct": kioxia.get("riseFrom2026LowToHighPct"),
            "articleStartDate": kioxia_article_start["date"] if kioxia_article_start else None,
            "articleStartLow": kioxia_article_start["low"] if kioxia_article_start else None,
            "articleStartClose": kioxia_article_start["close"] if kioxia_article_start else None,
            "riseFromArticleStartToPeakPct": (
                pct_change(kioxia.get("peak2026"), kioxia_article_start["low"])
                if kioxia_article_start and finite(kioxia.get("peak2026")) is not None else None
            ),
            "drawdownFrom2026HighPct": kioxia.get("drawdownFrom2026HighPct"),
            "sourceUrl": kioxia.get("sourceUrl"),
        },
        "jgb": jgb,
        "articleScenario": {
            "asOfDate": "2026-07-17",
            "eps": 3682.0,
            "bps": 34859.0,
            "roePct": 10.6,
            "targetPe": 16.6,
            "growthYears": 5,
            "targetPb": target_pb,
            "earningsFairValue": article_earnings_fair_value,
            "bookFairValue": article_book_fair_value,
            "interpretation": "ユーザー提供の榊原先生『市況展望』（2026年7月18日執筆）に記載された入力を、そのまま再計算した参考シナリオ。",
        },
        "enAiProxy": build_en_ai_proxy(companies, nikkei),
        "methodNotes": {
            "indexCorrection": "日経平均は価格加重指数、TOPIXは浮動株調整時価総額加重指数。原文の『日経平均は時価総額加重』は公式定義に合わせて補正。",
            "flowCaveat": "相対騰落だけでは資金の移動元・移動先を直接証明できないため、『資金移動と整合する値動き』として判定。",
            "classificationCaveat": "AI連動8社と日本・分散型8社は本サイト独自の固定監視群。榊原先生の正式な投資対象銘柄やEN-AI推奨銘柄ではない。",
            "scoreCaveat": "EN-AI proxyは品質40、相対割安25、年初来高値からの調整15、直近の相対回復15を、取得できた項目だけで100点換算した研究用スクリーニング。",
        },
    }


def fetch_episode(episode: dict[str, str]) -> dict[str, Any]:
    start = datetime.fromisoformat(episode["start"]).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(episode["end"]).replace(tzinfo=timezone.utc)
    encoded = urllib.parse.quote(episode["symbol"], safe="")
    query = urllib.parse.urlencode({
        "period1": int(start.timestamp()),
        "period2": int(end.timestamp()),
        "interval": "1d",
        "events": "history",
    })
    payload = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?{query}")
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    closes = result["indicators"]["quote"][0].get("close", [])
    points: list[dict[str, Any]] = []
    for timestamp, close in zip(timestamps, closes):
        value = finite(close)
        if value is None:
            continue
        points.append({
            "date": datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat(),
            "close": value,
        })
    if len(points) < 20:
        raise RuntimeError(f"Insufficient historical data for {episode['id']}")
    peak_end = episode.get("peakEnd", episode["end"])
    peak_index, peak = max(
        ((index, row) for index, row in enumerate(points) if row["date"] <= peak_end),
        key=lambda item: item[1]["close"],
    )
    trough = min(points[peak_index:], key=lambda row: row["close"])
    peak_date = datetime.fromisoformat(peak["date"]).date()
    trough_date = datetime.fromisoformat(trough["date"]).date()
    return {
        "id": episode["id"],
        "name": episode["name"],
        "index": episode["index"],
        "peak": peak["close"],
        "peakDate": peak["date"],
        "trough": trough["close"],
        "troughDate": trough["date"],
        "drawdownPct": (1.0 - trough["close"] / peak["close"]) * 100.0,
        "durationDays": (trough_date - peak_date).days,
        "note": episode["note"],
        "sourceUrl": f"https://finance.yahoo.com/quote/{urllib.parse.quote(episode['symbol'])}/history/",
    }


def parse_timeseries_result(result: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    types = result.get("meta", {}).get("type", [])
    key = types[0] if types else None
    if not key:
        return None, []
    rows = result.get(key) or []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        raw = finite((row.get("reportedValue") or {}).get("raw"))
        if raw is None:
            continue
        normalized.append({
            "date": row.get("asOfDate"),
            "periodType": row.get("periodType"),
            "currency": row.get("currencyCode"),
            "value": raw,
        })
    normalized.sort(key=lambda row: row.get("date") or "")
    return key, normalized


def fetch_fundamentals(symbol: str) -> dict[str, list[dict[str, Any]]]:
    period1 = int((NOW - timedelta(days=365 * 6)).timestamp())
    period2 = int((NOW + timedelta(days=3)).timestamp())
    query = urllib.parse.urlencode({
        "symbol": symbol,
        "type": ",".join(FUNDAMENTAL_TYPES),
        "merge": "false",
        "period1": period1,
        "period2": period2,
    }, safe=",")
    url = f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}?{query}"
    payload = get_json(url)
    series: dict[str, list[dict[str, Any]]] = {}
    for result in payload.get("timeseries", {}).get("result", []):
        key, rows = parse_timeseries_result(result)
        if key:
            series[key] = rows
    return series


def latest(series: dict[str, list[dict[str, Any]]], key: str) -> float | None:
    rows = series.get(key) or []
    return rows[-1]["value"] if rows else None


def latest_date(series: dict[str, list[dict[str, Any]]], key: str) -> str | None:
    rows = series.get(key) or []
    return rows[-1].get("date") if rows else None


def year_ago_pair(
    series: dict[str, list[dict[str, Any]]], key: str, tolerance_days: int = 45
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return the latest quarter and the matching quarter a year earlier.

    Yahoo's trailing series is irregular: adjacent observations may be nine months
    apart and are not necessarily year-over-year comparisons. Quarterly rows are
    matched by date instead, and are rejected when the prior-year quarter is absent.
    """
    rows = series.get(key) or []
    if len(rows) < 2 or not rows[-1].get("date"):
        return None
    latest_row = rows[-1]
    latest_day = datetime.fromisoformat(latest_row["date"]).date()
    target = latest_day - timedelta(days=365)
    candidates = [row for row in rows[:-1] if row.get("date")]
    if not candidates:
        return None
    prior_row = min(
        candidates,
        key=lambda row: abs((datetime.fromisoformat(row["date"]).date() - target).days),
    )
    gap = abs((datetime.fromisoformat(prior_row["date"]).date() - target).days)
    if gap > tolerance_days:
        return None
    return latest_row, prior_row


def quarterly_yoy_growth(
    series: dict[str, list[dict[str, Any]]],
    key: str,
    *,
    use_absolute_values: bool = False,
    require_positive_prior: bool = False,
) -> float | None:
    pair = year_ago_pair(series, key)
    if pair is None:
        return None
    current = finite(pair[0].get("value"))
    prior = finite(pair[1].get("value"))
    if current is None or prior is None or (require_positive_prior and prior <= 0):
        return None
    if use_absolute_values:
        current, prior = abs(current), abs(prior)
    return pct_change(current, prior)


def quarterly_fcf_deteriorated(series: dict[str, list[dict[str, Any]]]) -> bool | None:
    pair = year_ago_pair(series, "quarterlyFreeCashFlow")
    if pair is None:
        return None
    current = finite(pair[0].get("value"))
    prior = finite(pair[1].get("value"))
    if current is None or prior is None:
        return None
    if prior > 0:
        return current <= prior * 0.8
    if prior < 0:
        return current < prior
    return current < 0


def first_available(series: dict[str, list[dict[str, Any]]], keys: list[str]) -> float | None:
    for key in keys:
        value = latest(series, key)
        if value is not None:
            return value
    return None


def build_company(symbol: str, price: dict[str, Any]) -> dict[str, Any]:
    profile = COMPANIES[symbol]
    data = fetch_fundamentals(symbol)
    revenue = latest(data, "trailingTotalRevenue")
    operating_income = latest(data, "trailingOperatingIncome")
    fcf = latest(data, "trailingFreeCashFlow")
    capex = latest(data, "trailingCapitalExpenditure")
    market_cap = latest(data, "trailingMarketCap")
    net_income = latest(data, "trailingNetIncome")
    stockholders_equity = latest(data, "quarterlyStockholdersEquity")
    cash = first_available(data, [
        "quarterlyCashCashEquivalentsAndShortTermInvestments",
        "quarterlyCashAndCashEquivalents",
    ])
    debt = latest(data, "quarterlyTotalDebt")
    enterprise_value = None
    if market_cap is not None:
        enterprise_value = market_cap + (debt or 0.0) - (cash or 0.0)
    valuation_fcf = profile.get("valuationFcf", fcf)
    revenue_pair = year_ago_pair(data, "quarterlyTotalRevenue")
    fcf_pair = year_ago_pair(data, "quarterlyFreeCashFlow")
    capex_pair = year_ago_pair(data, "quarterlyCapitalExpenditure")
    return {
        "ticker": symbol,
        "displayTicker": profile.get("displayTicker", symbol),
        "chartLabel": profile.get("chartLabel", profile["name"] if profile.get("currency") == "JPY" else symbol),
        "name": profile["name"],
        "group": profile["group"],
        "category": profile.get("category", "overseas-ai"),
        "categoryLabel": profile.get("categoryLabel", "海外・AI関連"),
        "currency": profile.get("currency", "USD"),
        "market": profile.get("market", "米国市場"),
        "country": profile.get("country", "JP" if profile.get("currency") == "JPY" else "US"),
        "classificationNote": profile.get("classificationNote", "海外AIバスケットを構成する主要企業。従来の崩壊判定と企業価値評価の対象です。"),
        "classificationSourceUrl": profile.get("classificationSourceUrl", profile["ir"]),
        "valuationCaveat": profile.get("valuationCaveat", "標準化されたTTM FCFによるスクリーニングです。企業IRの事業別開示と一時要因を必ず照合してください。"),
        "price": price["close"],
        "priceDate": price["date"],
        "change1dPct": price["change1dPct"],
        "change5dPct": price["change5dPct"],
        "change20dPct": price.get("change20dPct"),
        "change60dPct": price.get("change60dPct"),
        "drawdown3yPct": price["drawdown3yPct"],
        "peak2026": price.get("peak2026"),
        "peak2026Date": price.get("peak2026Date"),
        "drawdownFrom2026HighPct": price.get("drawdownFrom2026HighPct"),
        "low2026": price.get("low2026"),
        "low2026Date": price.get("low2026Date"),
        "trailingDividendPerShare": price.get("trailingDividendPerShare"),
        "trailingDividendYieldPct": price.get("trailingDividendYieldPct"),
        "belowSma200": price["belowSma200"],
        "weeksBelowSma200": price["weeksBelowSma200"],
        "marketCap": market_cap,
        "trailingNetIncome": net_income,
        "stockholdersEquity": stockholders_equity,
        "approxTrailingPe": market_cap / net_income if market_cap is not None and net_income is not None and net_income > 0 else None,
        "approxPriceToBook": market_cap / stockholders_equity if market_cap is not None and stockholders_equity is not None and stockholders_equity > 0 else None,
        "enterpriseValue": enterprise_value,
        "cash": cash,
        "debt": debt,
        "ttmRevenue": revenue,
        "revenueGrowthYoYPct": quarterly_yoy_growth(data, "quarterlyTotalRevenue"),
        "revenueGrowthBasis": "最新四半期の前年同期比",
        "revenueGrowthCurrentDate": revenue_pair[0]["date"] if revenue_pair else None,
        "revenueGrowthPriorDate": revenue_pair[1]["date"] if revenue_pair else None,
        "ttmOperatingIncome": operating_income,
        "operatingMarginPct": (operating_income / revenue * 100.0) if operating_income is not None and revenue else None,
        "ttmFreeCashFlow": fcf,
        "freeCashFlowGrowthYoYPct": quarterly_yoy_growth(
            data, "quarterlyFreeCashFlow", require_positive_prior=True
        ),
        "freeCashFlowGrowthBasis": "最新四半期の前年同期比（前年が正のFCFの場合のみ）",
        "freeCashFlowDeteriorated": quarterly_fcf_deteriorated(data),
        "freeCashFlowGrowthCurrentDate": fcf_pair[0]["date"] if fcf_pair else None,
        "freeCashFlowGrowthPriorDate": fcf_pair[1]["date"] if fcf_pair else None,
        "freeCashFlowMarginPct": (fcf / revenue * 100.0) if fcf is not None and revenue else None,
        "freeCashFlowYieldPct": (fcf / market_cap * 100.0) if fcf is not None and market_cap else None,
        "valuationFcf": valuation_fcf,
        "valuationFcfYieldPct": (valuation_fcf / market_cap * 100.0) if valuation_fcf is not None and market_cap else None,
        "valuationFcfBasis": profile.get("valuationFcfBasis", "標準化された連結TTM FCF"),
        "valuationFcfFormula": profile.get("valuationFcfFormula", "自動取得した連結TTM FCFを使用。"),
        "valuationFcfPeriod": profile.get("valuationFcfPeriod", "TTM"),
        "valuationFcfSourceUrl": profile.get("valuationFcfSourceUrl", f"https://finance.yahoo.com/quote/{symbol}/financials/"),
        "valuationFcfSourceLabel": profile.get("valuationFcfSourceLabel", "Yahoo Finance fundamentals"),
        "financialServicesTreatment": profile.get("financialServicesTreatment"),
        "ttmCapex": abs(capex) if capex is not None else None,
        "capexGrowthYoYPct": quarterly_yoy_growth(
            data, "quarterlyCapitalExpenditure", use_absolute_values=True
        ),
        "capexGrowthBasis": "最新四半期の設備投資額（絶対値）の前年同期比",
        "capexGrowthCurrentDate": capex_pair[0]["date"] if capex_pair else None,
        "capexGrowthPriorDate": capex_pair[1]["date"] if capex_pair else None,
        "filingDate": latest_date(data, "trailingTotalRevenue"),
        "assumptions": {
            "discountRatePct": profile["discount"] * 100.0,
            "terminalGrowthPct": profile["terminal"] * 100.0,
            "bearGrowthPct": profile["growth"]["bear"] * 100.0,
            "baseGrowthPct": profile["growth"]["base"] * 100.0,
            "bullGrowthPct": profile["growth"]["bull"] * 100.0,
            "forecastYears": 10,
        },
        "irUrl": profile["ir"],
        "marketSourceUrl": price["sourceUrl"],
        "fundamentalsSourceUrl": f"https://finance.yahoo.com/quote/{symbol}/financials/",
    }


def decimal_year_from_iso_date(value: str) -> float:
    observed = datetime.strptime(value, "%Y-%m-%d")
    year_start = datetime(observed.year, 1, 1)
    next_year = datetime(observed.year + 1, 1, 1)
    return observed.year + (observed - year_start).days / (next_year - year_start).days


def fetch_cpi_history(series_id: str = "CPIAUCNS") -> dict[str, Any]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={urllib.parse.quote(series_id)}"
    text = request(url).decode("utf-8-sig")
    history: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(text)):
        value = finite(row.get(series_id))
        date_value = row.get("observation_date")
        if value is None or not date_value:
            continue
        history.append({
            "date": date_value,
            "x": round(decimal_year_from_iso_date(date_value), 6),
            "value": round(value, 3),
        })
    if not history:
        raise RuntimeError(f"No observations for FRED {series_id}")
    return {
        "seriesId": series_id,
        "name": "米国CPI-U 全品目・U.S. city average",
        "definition": "BLSの全都市消費者物価指数。食品、住居、燃料、交通、医療などの価格変化を家計支出ウエートで集約する。",
        "units": "Index 1982-1984=100",
        "frequency": "Monthly, not seasonally adjusted",
        "comparisonBaseDate": "1913-01-01",
        "latestDate": history[-1]["date"],
        "latestValue": history[-1]["value"],
        "history": history,
        "sourceUrl": f"https://fred.stlouisfed.org/series/{series_id}",
        "sourceAgencyUrl": "https://www.bls.gov/cpi/",
        "importantLimit": "橙線はBLS/FREDのCPI-U実績で、最新公式月で停止します。将来の物価を外挿せず、株価とは別の右軸で表示します。",
    }


def fetch_fred(series_id: str) -> dict[str, Any]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={urllib.parse.quote(series_id)}"
    text = request(url).decode("utf-8-sig")
    rows: list[tuple[str, float]] = []
    for row in csv.DictReader(io.StringIO(text)):
        raw = finite(row.get(series_id))
        if raw is not None:
            rows.append((row["observation_date"], raw))
    if not rows:
        raise RuntimeError(f"No observations for FRED {series_id}")
    last_date, last_value = rows[-1]
    cutoff = datetime.fromisoformat(last_date).date() - timedelta(days=95)
    prior = next((value for date, value in reversed(rows) if datetime.fromisoformat(date).date() <= cutoff), rows[0][1])
    low_3m = min(value for date, value in rows if datetime.fromisoformat(date).date() >= cutoff)
    high_3m = max(value for date, value in rows if datetime.fromisoformat(date).date() >= cutoff)
    calibration = threshold_sample(
        [{"date": date, "value": value} for date, value in rows],
        "value",
        [3.5, 4.0, 5.0, 6.0],
    )
    calibration["historyNote"] = (
        "FRED注記により2026年4月以降は直近3年のみ公開。5%・6%は現在の公開標本上限を超える。"
    )
    return {
        "seriesId": series_id,
        "date": last_date,
        "valuePct": last_value,
        "change3mPctPoints": last_value - prior,
        "riseFrom3mLowPctPoints": last_value - low_3m,
        "declineFrom3mHighPctPoints": high_3m - last_value,
        "high3mPct": high_3m,
        "calibration": calibration,
        "sourceUrl": f"https://fred.stlouisfed.org/series/{series_id}",
    }



def fetch_fred_level(
    series_id: str,
    *,
    name: str,
    units: str,
    thresholds: list[float],
) -> dict[str, Any]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={urllib.parse.quote(series_id)}"
    text = request(url).decode("utf-8-sig")
    rows: list[tuple[str, float]] = []
    for row in csv.DictReader(io.StringIO(text)):
        value = finite(row.get(series_id))
        if value is not None:
            rows.append((row["observation_date"], value))
    if not rows:
        raise RuntimeError(f"No observations for FRED {series_id}")
    last_date, last_value = rows[-1]
    cutoff = datetime.fromisoformat(last_date).date() - timedelta(days=95)
    prior = next(
        (value for date_value, value in reversed(rows) if datetime.fromisoformat(date_value).date() <= cutoff),
        rows[0][1],
    )
    calibration = threshold_sample(
        [{"date": date_value, "value": value} for date_value, value in rows],
        "value",
        thresholds,
    )
    return {
        "seriesId": series_id,
        "name": name,
        "units": units,
        "date": last_date,
        "value": last_value,
        "change3m": last_value - prior,
        "calibration": calibration,
        "sourceUrl": f"https://fred.stlouisfed.org/series/{series_id}",
    }


def us_risk_component(
    component_id: str,
    label: str,
    parts: list[tuple[float | None, float]],
    detail: str,
) -> dict[str, Any]:
    maximum = sum(maximum for _score, maximum in parts)
    known_maximum = sum(maximum for score, maximum in parts if score is not None)
    observed = sum(score for score, _maximum in parts if score is not None)
    return {
        "id": component_id,
        "label": label,
        "score": round(observed, 2),
        "knownMax": round(known_maximum, 2),
        "maxScore": round(maximum, 2),
        "detail": detail,
    }


def build_us_bubble_risk(
    prices: dict[str, dict[str, Any]],
    ai_basket: dict[str, Any],
    macro: dict[str, Any],
    derived: dict[str, Any],
) -> dict[str, Any]:
    sp500 = prices.get("SP500") or {}
    sox = prices.get("SOX") or {}
    vix = prices.get("VIX") or {}
    oas = macro.get("highYieldOas") or {}
    nfci = macro.get("financialConditions") or {}

    sp_drawdown = finite(sp500.get("drawdown3yPct"))
    sp_below_200 = sp500.get("belowSma200") if "belowSma200" in sp500 else None
    sp_above_50 = sp500.get("aboveSma50") if "aboveSma50" in sp500 else None
    sp_slope = finite(sp500.get("sma50Slope20dPct"))
    short_trend_score = None
    if sp_above_50 is not None and sp_slope is not None:
        short_trend_score = 4.0 if (not sp_above_50 and sp_slope < 0) else 2.0 if (not sp_above_50 or sp_slope < 0) else 0.0
    price_component = us_risk_component(
        "price",
        "S&P 500の下落とトレンド",
        [
            (score_at_or_above(sp_drawdown, [(30, 18), (20, 14), (10, 8), (5, 3)]), 18),
            (8.0 if sp_below_200 else 0.0 if sp_below_200 is not None else None, 8),
            (short_trend_score, 4),
        ],
        f"S&P 500は3年高値から{sp_drawdown:.1f}%下。200日線は{'下' if sp_below_200 else '上'}、50日線は{'上' if sp_above_50 else '下'}。" if sp_drawdown is not None and sp_below_200 is not None and sp_above_50 is not None else "S&P 500の高値からの下落と移動平均を確認中。",
    )

    sox_drawdown = finite(sox.get("drawdown3yPct"))
    breadth = finite(ai_basket.get("breadthBelowSma200Pct"))
    tech_component = us_risk_component(
        "tech",
        "半導体とAI銘柄への波及",
        [
            (score_at_or_above(sox_drawdown, [(50, 12), (35, 10), (20, 6), (10, 3)]), 12),
            (score_at_or_above(breadth, [(75, 8), (50, 5), (25, 2)]), 8),
        ],
        f"SOXは高値から{sox_drawdown:.1f}%下落し、監視AI 10社のうち200日線割れは{breadth:.0f}%です。" if sox_drawdown is not None and breadth is not None else "SOXとAI銘柄の市場幅を確認中。",
    )

    vix_value = finite(vix.get("close"))
    oas_value = finite(oas.get("valuePct"))
    stress_component = us_risk_component(
        "stress",
        "恐怖と信用市場",
        [
            (score_at_or_above(vix_value, [(40, 12), (30, 9), (25, 6), (20, 3)]), 12),
            (score_at_or_above(oas_value, [(6, 13), (5, 10), (4, 6), (3.5, 3)]), 13),
        ],
        f"VIXは{vix_value:.1f}、米国HY OASは{oas_value:.2f}%です。株安だけでなく資金調達不安へ広がったかを見ます。" if vix_value is not None and oas_value is not None else "VIXと米国HY OASを確認中。",
    )

    fcf_breadth = finite(derived.get("fcfDeteriorationBreadthPct"))
    revenue_growth = finite(derived.get("medianLatestQuarterRevenueGrowthYoYPct"))
    fundamentals_component = us_risk_component(
        "fundamentals",
        "AI企業の利益・現金創出",
        [
            (score_at_or_above(fcf_breadth, [(70, 10), (50, 7), (30, 4), (10, 1)]), 10),
            (score_at_or_below(revenue_growth, [(0, 5), (10, 4), (20, 2)]), 5),
        ],
        f"監視AI企業のFCF悪化は{fcf_breadth:.0f}%、売上成長率中央値は{revenue_growth:.1f}%です。価格下落が業績悪化を先取りしているかを確認します。" if fcf_breadth is not None and revenue_growth is not None else "AI企業の売上とFCFを確認中。",
    )

    nfci_value = finite(nfci.get("value"))
    conditions_component = us_risk_component(
        "conditions",
        "米国の金融環境",
        [(score_at_or_above(nfci_value, [(0.75, 10), (0.50, 8), (0.25, 5), (0.0, 2)]), 10)],
        f"Chicago Fed NFCIは{nfci_value:+.2f}。0より上は平均より引き締まった金融環境です。" if nfci_value is not None else "Chicago Fed NFCIを確認中。",
    )

    components = [price_component, tech_component, stress_component, fundamentals_component, conditions_component]
    raw_score = sum(component["score"] for component in components)
    known_maximum = sum(component["knownMax"] for component in components)
    maximum = sum(component["maxScore"] for component in components)
    score = raw_score / known_maximum * 100 if known_maximum >= 70 else None
    if score is None:
        stage_code, stage_label = "insufficient", "データ不足"
    elif score < 20:
        stage_code, stage_label = "watch", "期待は高いが、崩壊の確認は限定的"
    elif score < 40:
        stage_code, stage_label = "deterioration", "初期劣化"
    elif score < 60:
        stage_code, stage_label = "correction", "調整局面"
    elif score < 75:
        stage_code, stage_label = "bear", "弱気相場への移行"
    else:
        stage_code, stage_label = "panic", "パニック・信用ストレス"

    peak = finite(sp500.get("peak3y"))
    current = finite(sp500.get("close"))
    scenario_defs = [
        ("correction", "一般的な調整", 10.0, "高値から10%。崩壊の断定ではなく、通常の調整域。"),
        ("bear", "弱気相場の目安", 20.0, "高値から20%。価格トレンドの明確な悪化を確認する水準。"),
        ("recession", "景気後退型", 30.0, "高値から30%。利益下方修正と信用悪化の有無が重要。"),
        ("dotcom", "S&P 500のITバブル実績", 49.1, "2000～02年のS&P 500実績を機械的に換算。今回の予測値ではない。"),
    ]
    scenarios = []
    if peak is not None and current is not None:
        for scenario_id, label, drawdown, note in scenario_defs:
            level = peak * (1 - drawdown / 100)
            scenarios.append({
                "id": scenario_id,
                "label": label,
                "drawdownFromPeakPct": drawdown,
                "level": round(level, 2),
                "moveFromCurrentPct": (level / current - 1) * 100,
                "note": note,
            })

    strongest = max(components, key=lambda row: row["score"] / row["knownMax"] if row["knownMax"] else -1)
    if score is None:
        narrative = "主要データの取得が不足しているため、進行度を計算できません。欠測を0点として扱いません。"
    else:
        narrative = (
            f"崩壊進行度は{score:.0f}/100で『{stage_label}』です。最も強い警戒材料は「{strongest['label']}」。"
            f"現在はS&P 500本体、信用市場、企業業績が同じ方向へ悪化しているかを重視します。"
        )
    return {
        "method": "US breakdown progression index v1.0",
        "asOfDate": sp500.get("date"),
        "score": round(score, 1) if score is not None else None,
        "rawScore": round(raw_score, 2),
        "knownMax": round(known_maximum, 2),
        "maxScore": round(maximum, 2),
        "coveragePct": round(known_maximum / maximum * 100, 1) if maximum else 0,
        "stageCode": stage_code,
        "stageLabel": stage_label,
        "narrative": narrative,
        "components": components,
        "scenarios": scenarios,
        "rules": {
            "meaning": "バブルの存在確率ではなく、価格下落が市場幅、信用、企業の現金創出、金融環境へ広がった程度を0～100で表す。",
            "thresholdBasis": "10%は調整、20%は弱気相場を考える一般的な価格区分。VIX 20/30/40、HY OAS 3.5/4/5/6%、NFCI 0超を段階化し、単一指標で断定しない。",
            "notProbability": "過去データで確率校正した暴落確率ではない。将来の時期や底値を一意に予測しない。",
        },
    }


def xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def xml_descendant_text(node: ET.Element, name: str) -> str:
    for child in node.iter():
        if xml_local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def discover_berkshire_13f_filings() -> tuple[list[dict[str, Any]], bool]:
    try:
        submissions = get_json("https://data.sec.gov/submissions/CIK0001067983.json")
        recent = submissions["filings"]["recent"]
        found: list[dict[str, Any]] = []
        for index, form in enumerate(recent.get("form", [])):
            if form != "13F-HR":
                continue
            accession = recent["accessionNumber"][index]
            accession_compact = accession.replace("-", "")
            base = f"https://www.sec.gov/Archives/edgar/data/1067983/{accession_compact}/"
            directory = get_json(base + "index.json")
            names = [item.get("name", "") for item in directory.get("directory", {}).get("item", [])]
            xml_name = next((name for name in names if name.lower().endswith(".xml") and name.lower() != "primary_doc.xml"), None)
            if not xml_name:
                continue
            found.append({
                "reportDate": recent["reportDate"][index],
                "filingDate": recent["filingDate"][index],
                "accession": accession,
                "xmlUrl": base + xml_name,
                "sourceUrl": base + accession + "-index.htm",
            })
            if len(found) == 2:
                return found, False
    except Exception:
        pass
    return [dict(row) for row in BERKSHIRE_13F_FALLBACK], True


def parse_13f_holdings(filing: dict[str, Any]) -> dict[str, dict[str, Any]]:
    root = ET.fromstring(request(filing["xmlUrl"]))
    holdings: dict[str, dict[str, Any]] = {}
    for node in root.iter():
        if xml_local_name(node.tag) != "infoTable":
            continue
        cusip = xml_descendant_text(node, "cusip")
        if not cusip:
            continue
        shares = finite(xml_descendant_text(node, "sshPrnamt")) or 0.0
        value = finite(xml_descendant_text(node, "value")) or 0.0
        row = holdings.setdefault(cusip, {
            "cusip": cusip,
            "name": xml_descendant_text(node, "nameOfIssuer").title(),
            "securityClass": xml_descendant_text(node, "titleOfClass"),
            "shares": 0.0,
            "reportedValue": 0.0,
        })
        row["shares"] += shares
        row["reportedValue"] += value
    if not holdings:
        raise RuntimeError("SEC 13F information table has no holdings")
    return holdings


def compare_13f_holdings(
    latest: dict[str, dict[str, Any]], previous: dict[str, dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    buys: list[dict[str, Any]] = []
    sells: list[dict[str, Any]] = []
    for cusip in set(latest) | set(previous):
        current = latest.get(cusip) or {}
        prior = previous.get(cusip) or {}
        current_shares = finite(current.get("shares")) or 0.0
        prior_shares = finite(prior.get("shares")) or 0.0
        delta = current_shares - prior_shares
        if abs(delta) < 1:
            continue
        change_pct = delta / prior_shares * 100 if prior_shares else None
        if prior_shares and abs(change_pct or 0) < 0.5:
            continue
        row = {
            "cusip": cusip,
            "name": current.get("name") or prior.get("name") or cusip,
            "securityClass": current.get("securityClass") or prior.get("securityClass") or "",
            "latestShares": round(current_shares),
            "previousShares": round(prior_shares),
            "changeShares": round(delta),
            "changePct": round(change_pct, 1) if change_pct is not None else None,
            "status": "新規" if not prior_shares else "全売却" if not current_shares else "買い増し" if delta > 0 else "縮小",
            "sortValue": finite(current.get("reportedValue")) or finite(prior.get("reportedValue")) or abs(delta),
        }
        (buys if delta > 0 else sells).append(row)
    buys.sort(key=lambda row: row["sortValue"], reverse=True)
    sells.sort(key=lambda row: row["sortValue"], reverse=True)
    for row in buys + sells:
        row.pop("sortValue", None)
    return {"buys": buys[:6], "sells": sells[:6]}


def build_berkshire_monitor() -> dict[str, Any]:
    snapshots = [dict(row) for row in BERKSHIRE_BALANCE_SNAPSHOTS]
    for row in snapshots:
        row["netLiquidReserveBillion"] = (
            row["cashAndEquivalentsBillion"] + row["treasuryBillsBillion"] - row["unsettledTreasuryPayableBillion"]
        )
        pool = row["netLiquidReserveBillion"] + row["equitySecuritiesBillion"] + row["fixedMaturityBillion"]
        row["investmentPoolLiquidRatioPct"] = row["netLiquidReserveBillion"] / pool * 100
        row["liquidReserveToTotalAssetsPct"] = row["netLiquidReserveBillion"] / row["totalAssetsBillion"] * 100
    latest_balance, previous_balance = snapshots
    filings, discovery_fallback = discover_berkshire_13f_filings()
    direct_13f = False
    changes = {"buys": [], "sells": []}
    try:
        latest_holdings = parse_13f_holdings(filings[0])
        previous_holdings = parse_13f_holdings(filings[1])
        changes = compare_13f_holdings(latest_holdings, previous_holdings)
        direct_13f = True
    except Exception:
        changes = {
            "buys": [dict(row) for row in BERKSHIRE_13F_CHANGE_FALLBACK["buys"]],
            "sells": [dict(row) for row in BERKSHIRE_13F_CHANGE_FALLBACK["sells"]],
        }
    reserve_change = latest_balance["netLiquidReserveBillion"] - previous_balance["netLiquidReserveBillion"]
    ratio_change = latest_balance["investmentPoolLiquidRatioPct"] - previous_balance["investmentPoolLiquidRatioPct"]
    return {
        "checkedAtUtc": NOW.isoformat(),
        "balanceLatest": latest_balance,
        "balancePrevious": previous_balance,
        "reserveChangeBillion": reserve_change,
        "reserveChangePct": reserve_change / previous_balance["netLiquidReserveBillion"] * 100,
        "investmentPoolLiquidRatioChangePctPoints": ratio_change,
        "equitySecuritiesChangeBillion": latest_balance["equitySecuritiesBillion"] - previous_balance["equitySecuritiesBillion"],
        "thirteenF": {
            "latest": filings[0],
            "previous": filings[1],
            "buys": changes["buys"],
            "sells": changes["sells"],
            "directSecRefresh": direct_13f,
            "discoveryFallback": discovery_fallback,
        },
        "narrative": (
            f"保険・その他の純流動性は{previous_balance['netLiquidReserveBillion']:.1f}から"
            f"{latest_balance['netLiquidReserveBillion']:.1f}十億ドルへ増え、投資プール内の比率は"
            f"{previous_balance['investmentPoolLiquidRatioPct']:.1f}%から{latest_balance['investmentPoolLiquidRatioPct']:.1f}%へ上昇しました。"
            "同時に13Fでは買い増しと売却の双方があるため、『現金が多い＝全面弱気』とは読まず、準備資金と個別銘柄選択を分けて確認します。"
        ),
        "calculationNote": "純流動性＝現金・現金同等物＋米国短期国債－未決済の短期国債購入債務。投資プール内比率＝純流動性÷（純流動性＋株式＋債券）。Berkshire公式指標ではなく比較用の当サイト算式。",
        "thirteenFLimit": "13Fは四半期末から最大45日遅れ、米国上場株中心で、現金・完全子会社・一部海外株を含みません。株数で比較し、時価の増減を売買と誤認しません。",
    }


def classify_news_topic(text: str) -> str:
    lowered = text.lower()
    for label, terms in NEWS_TOPIC_TERMS.items():
        if any(term in lowered for term in terms):
            return label
    return "その他の海外材料"


def fetch_google_news() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in OVERSEAS_NEWS_QUERIES:
        encoded = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
        root = ET.fromstring(request(url))
        for node in root.findall("./channel/item"):
            title = (node.findtext("title") or "").strip()
            link = (node.findtext("link") or "").strip()
            published = (node.findtext("pubDate") or "").strip()
            source_node = node.find("source")
            source = (source_node.text or "").strip() if source_node is not None else "海外報道"
            if source in LOW_SIGNAL_NEWS_SOURCES:
                continue
            preferred = any(label.lower() in source.lower() for label in PREFERRED_NEWS_SOURCES)
            dedupe = re.sub(r"\s+", " ", title.lower())
            if not title or not link or dedupe in seen:
                continue
            seen.add(dedupe)
            items.append({
                "title": title,
                "url": link,
                "published": published,
                "source": source,
                "evidenceLevel": "主要海外報道" if preferred else "海外報道",
                "topic": classify_news_topic(title),
                "_priority": 0 if preferred else 1,
            })
    items.sort(key=lambda row: row["_priority"])
    for row in items:
        row.pop("_priority", None)
    return items[:12]


def fetch_x_watch() -> dict[str, Any]:
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token:
        return {"status": "not-configured", "items": [], "message": "X接続は未設定。海外報道と公式資料を更新しました。"}
    query = '(AI OR semiconductor OR OpenAI OR Anthropic) (earnings OR guidance OR capex OR financing OR IPO OR lockup) lang:en -is:retweet'
    params = urllib.parse.urlencode({
        "query": query,
        "max_results": 20,
        "tweet.fields": "created_at,author_id,lang",
        "expansions": "author_id",
        "user.fields": "username,name,verified",
    })
    url = "https://api.x.com/2/tweets/search/recent?" + params
    payload = json.loads(request(url, extra_headers={"Authorization": f"Bearer {token}"}).decode("utf-8"))
    users = {row["id"]: row for row in payload.get("includes", {}).get("users", [])}
    output = []
    for row in payload.get("data", []):
        user = users.get(row.get("author_id"), {})
        username = user.get("username", "")
        text = re.sub(r"\s+", " ", row.get("text", "")).strip()
        output.append({
            "title": text[:240],
            "url": f"https://x.com/{username}/status/{row['id']}" if username else f"https://x.com/i/web/status/{row['id']}",
            "published": row.get("created_at"),
            "source": "@" + username if username else "X",
            "verified": bool(user.get("verified")),
            "evidenceLevel": "X上の早期情報",
            "topic": classify_news_topic(text),
        })
    return {"status": "connected", "items": output, "message": f"Xから{len(output)}件の候補を取得しました。"}


def build_overseas_intelligence() -> dict[str, Any]:
    news_items = fetch_google_news()
    try:
        x_watch = fetch_x_watch()
    except Exception as exc:
        x_watch = {"status": "failed", "items": [], "message": f"X取得に失敗: {exc}"}
    all_items = news_items + x_watch["items"]
    topic_counts: dict[str, int] = {}
    for row in all_items:
        topic_counts[row["topic"]] = topic_counts.get(row["topic"], 0) + 1
    ranked = sorted(topic_counts.items(), key=lambda item: (-item[1], item[0]))
    focus = "、".join(f"{label}{count}件" for label, count in ranked[:3]) or "新着なし"
    return {
        "checkedAtUtc": NOW.isoformat(),
        "newsItems": news_items,
        "x": x_watch,
        "topicCounts": topic_counts,
        "summary": f"直近の海外情報は{len(all_items)}件。主な論点は{focus}です。見出しや投稿を起点に、決算、SEC提出、会社IRで確認します。",
        "readingRule": "海外報道とXは変化を早く見つける入口。数値や会社行動は決算、SEC、会社IRで確認できた時点で企業価値・崩壊進行度へ反映する。",
    }


def sampled_chart(price_data: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    start = (NOW.date() - timedelta(days=365 * 3)).isoformat()
    symbols = [symbol for symbol in CHART_TICKERS if symbol in price_data]
    if len(symbols) != len(CHART_TICKERS):
        return []
    maps = {
        symbol: {row["date"]: row["close"] for row in price_data[symbol]["history"] if row["date"] >= start}
        for symbol in symbols
    }
    sox_map = {row["date"]: row["close"] for row in price_data["SOX"]["history"] if row["date"] >= start}
    dates = sorted(set(sox_map).intersection(*(set(values) for values in maps.values())))
    if not dates:
        return []
    base_date = dates[0]
    base_sox = sox_map[base_date]
    bases = {symbol: maps[symbol][base_date] for symbol in symbols}
    output: list[dict[str, Any]] = []
    for index, date in enumerate(dates):
        if index % 5 != 0 and index != len(dates) - 1:
            continue
        basket = statistics.mean(maps[symbol][date] / bases[symbol] * 100.0 for symbol in symbols)
        output.append({
            "date": date,
            "sox": sox_map[date] / base_sox * 100.0,
            "aiBasket": basket,
        })
    return output


def build_dotcom_comparison() -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for group, label in DOTCOM_GROUP_LABELS.items():
        rows = [row for row in DOTCOM_COMPARISON_ROWS if row["group"] == group]
        summaries.append({
            "group": group,
            "label": label,
            "count": len(rows),
            "medianWindowReturnPct": median(row["windowReturnPct"] for row in rows),
            "medianMaxDrawdownPct": median(row["maxDrawdownPct"] for row in rows),
            "medianExtendedMaxDrawdownPct": median(
                row.get("extendedMaxDrawdownPct") for row in rows if row.get("extendedMaxDrawdownPct") is not None
            ),
        })
    return {
        "window": {
            "startDate": "2000-03-10",
            "endDate": "2002-10-09",
            "definition": "NASDAQ終値の最高値から最安値まで",
        },
        "japanExtendedEndDate": "2003-04-28",
        "priceBasis": "Yahoo Financeの調整後終値（株式分割・配当調整後）",
        "auditDate": "2026-07-19",
        "rows": DOTCOM_COMPARISON_ROWS,
        "groupSummaries": summaries,
        "overlapWarning": "2000～2003年にはITバブル崩壊だけでなく、米国景気後退、同時多発テロ、日本のデフレ・銀行不安、イラク情勢が重なります。下落率をIT崩壊だけの因果効果とは解釈できません。",
        "selectionWarning": "現在まで存続する代表企業を選んだ小標本であり、生存者バイアスがあります。個別銘柄の将来下落率を予測する表ではありません。",
    }


def strip_history(price_data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    compact: dict[str, dict[str, Any]] = {}
    for symbol, data in price_data.items():
        compact[symbol] = {key: value for key, value in data.items() if key != "history"}
    return compact


def sync_money_strategist_latest(
    sp500: dict[str, Any] | None, cpi_history: dict[str, Any] | None = None
) -> None:
    """Synchronize independently available S&P and CPI observations."""
    if not MONEY_STRATEGIST_OUTPUT.exists() or (not sp500 and not cpi_history):
        return

    package = json.loads(MONEY_STRATEGIST_OUTPUT.read_text(encoding="utf-8"))
    changed = False
    if sp500:
        latest_date = sp500.get("date")
        latest_value = sp500.get("close")
        if latest_date and isinstance(latest_value, (int, float)) and math.isfinite(latest_value):
            history = package.get("series", {}).get("history")
            if not isinstance(history, list):
                raise ValueError("Money Strategist history is missing")
            point = {
                "date": latest_date,
                "x": round(decimal_year_from_iso_date(latest_date), 6),
                "value": round(float(latest_value), 4),
                "sourceType": "S&P 500 live close appended by the local data update",
            }
            matches = [index for index, row in enumerate(history) if row.get("date") == latest_date]
            if matches:
                history[matches[-1]] = point
            else:
                history.append(point)
                history.sort(key=lambda row: row.get("date", ""))
            package["series"]["latestDate"] = latest_date
            package["series"]["latestValue"] = round(float(latest_value), 2)
            changed = True

    if cpi_history:
        package["inflation"] = cpi_history
        changed = True
    if changed:
        MONEY_STRATEGIST_OUTPUT.write_text(
            json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def main() -> None:
    previous_payload: dict[str, Any] = {}
    if OUTPUT.exists():
        try:
            previous_payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        except Exception:
            previous_payload = {}
    statuses: list[SourceStatus] = []
    errors: list[str] = []
    prices: dict[str, dict[str, Any]] = {}
    companies: list[dict[str, Any]] = []
    historical_episodes: list[dict[str, Any]] = []
    cpi_history: dict[str, Any] | None = None

    for label, symbol in PRICE_SYMBOLS.items():
        try:
            prices[label] = fetch_price_series(symbol)
            statuses.append(SourceStatus("Yahoo Finance chart", prices[label]["sourceUrl"], True, NOW.isoformat(), label))
        except Exception as exc:  # keep other sources usable if one ticker fails
            errors.append(f"Price {label}: {exc}")
            statuses.append(SourceStatus("Yahoo Finance chart", f"https://finance.yahoo.com/quote/{symbol}", False, NOW.isoformat(), str(exc)))

    try:
        prices["TOPIX"] = fetch_topix_series()
        statuses.append(SourceStatus(
            "Yahoo!ファイナンス日本版 TOPIX",
            prices["TOPIX"]["sourceUrl"],
            True,
            NOW.isoformat(),
            prices["TOPIX"].get("sourceNote", ""),
        ))
    except Exception as exc:
        errors.append(f"TOPIX: {exc}")
        statuses.append(SourceStatus(
            "Yahoo!ファイナンス日本版 TOPIX",
            "https://finance.yahoo.co.jp/quote/998405/history",
            False,
            NOW.isoformat(),
            str(exc),
        ))

    for symbol in COMPANIES:
        if symbol not in prices:
            continue
        try:
            companies.append(build_company(symbol, prices[symbol]))
            statuses.append(SourceStatus("Yahoo Finance fundamentals", f"https://finance.yahoo.com/quote/{symbol}/financials/", True, NOW.isoformat(), symbol))
            profile = COMPANIES[symbol]
            if profile.get("valuationFcfSourceUrl"):
                statuses.append(SourceStatus(
                    profile.get("valuationFcfSourceLabel", "Official valuation cash flow"),
                    profile["valuationFcfSourceUrl"],
                    True,
                    NOW.isoformat(),
                    f"{symbol}: {profile.get('valuationFcfBasis', 'valuation FCF override')}",
                ))
        except Exception as exc:
            errors.append(f"Fundamentals {symbol}: {exc}")
            statuses.append(SourceStatus("Yahoo Finance fundamentals", f"https://finance.yahoo.com/quote/{symbol}/financials/", False, NOW.isoformat(), str(exc)))

    for episode in HISTORICAL_EPISODES:
        try:
            historical_episodes.append(fetch_episode(episode))
            statuses.append(SourceStatus("Yahoo Finance historical chart", historical_episodes[-1]["sourceUrl"], True, NOW.isoformat(), episode["name"]))
        except Exception as exc:
            errors.append(f"Historical episode {episode['id']}: {exc}")
            statuses.append(SourceStatus("Yahoo Finance historical chart", f"https://finance.yahoo.com/quote/{episode['symbol']}/history/", False, NOW.isoformat(), str(exc)))

    macro: dict[str, Any] = {}
    jgb_yield: dict[str, Any] | None = None
    try:
        jgb_yield = fetch_mof_jgb_yield()
        macro["jgb10y"] = jgb_yield
        statuses.append(SourceStatus(
            "財務省 国債金利情報",
            jgb_yield["sourceUrl"],
            True,
            NOW.isoformat(),
            jgb_yield["definition"],
        ))
    except Exception as exc:
        errors.append(f"MOF JGB: {exc}")
        statuses.append(SourceStatus(
            "財務省 国債金利情報",
            "https://www.mof.go.jp/jgbs/reference/interest_rate/index.htm",
            False,
            NOW.isoformat(),
            str(exc),
        ))

    for key, series in {"highYieldOas": "BAMLH0A0HYM2"}.items():
        try:
            macro[key] = fetch_fred(series)
            statuses.append(SourceStatus("FRED", macro[key]["sourceUrl"], True, NOW.isoformat(), series))
        except Exception as exc:
            errors.append(f"FRED {series}: {exc}")
            statuses.append(SourceStatus("FRED", f"https://fred.stlouisfed.org/series/{series}", False, NOW.isoformat(), str(exc)))

    try:
        macro["financialConditions"] = fetch_fred_level(
            "NFCI",
            name="Chicago Fed National Financial Conditions Index",
            units="Index; positive is tighter than average",
            thresholds=[0.0, 0.25, 0.5, 0.75],
        )
        statuses.append(SourceStatus("FRED / Chicago Fed NFCI", macro["financialConditions"]["sourceUrl"], True, NOW.isoformat(), macro["financialConditions"]["date"]))
    except Exception as exc:
        errors.append(f"FRED NFCI: {exc}")
        statuses.append(SourceStatus("FRED / Chicago Fed NFCI", "https://fred.stlouisfed.org/series/NFCI", False, NOW.isoformat(), str(exc)))

    try:
        cpi_history = fetch_cpi_history()
        statuses.append(SourceStatus("FRED CPI-U", cpi_history["sourceUrl"], True, NOW.isoformat(), cpi_history["latestDate"]))
    except Exception as exc:
        errors.append(f"FRED CPIAUCNS: {exc}")
        statuses.append(SourceStatus("FRED CPI-U", "https://fred.stlouisfed.org/series/CPIAUCNS", False, NOW.isoformat(), f"既存のMoney Strategist CPI系列を保持: {exc}"))

    overseas_ai_companies = [company for company in companies if company["ticker"] in OVERSEAS_AI_TICKERS]
    japan_ai_companies = [company for company in companies if company["ticker"] in JAPAN_AI_TICKERS]
    company_drawdowns = [company.get("drawdown3yPct") for company in overseas_ai_companies]
    below_count = sum(1 for company in overseas_ai_companies if company.get("belowSma200"))
    japan_company_drawdowns = [company.get("drawdown3yPct") for company in japan_ai_companies]
    japan_below_count = sum(1 for company in japan_ai_companies if company.get("belowSma200"))
    revenue_growth = [
        company.get("revenueGrowthYoYPct")
        for company in overseas_ai_companies
        if company.get("revenueGrowthYoYPct") is not None
    ]
    fcf_deterioration = [
        company.get("freeCashFlowDeteriorated")
        for company in overseas_ai_companies
        if company.get("freeCashFlowDeteriorated") is not None
    ]
    hyperscaler_capex = [
        company.get("capexGrowthYoYPct") for company in overseas_ai_companies if company["ticker"] in HYPERSCALERS
    ]
    sakakibara_analysis: dict[str, Any] = {}
    try:
        sakakibara_analysis = build_sakakibara_analysis(
            prices, companies, jgb_yield, macro.get("highYieldOas")
        )
    except Exception as exc:
        errors.append(f"Sakakibara analysis: {exc}")


    ai_basket = {
        "constituents": [company["ticker"] for company in overseas_ai_companies],
        "medianDrawdown3yPct": median(company_drawdowns),
        "breadthBelowSma200Pct": (below_count / len(overseas_ai_companies) * 100.0) if overseas_ai_companies else None,
        "medianChange1dPct": median(company.get("change1dPct") for company in overseas_ai_companies),
        "medianChange5dPct": median(company.get("change5dPct") for company in overseas_ai_companies),
    }
    derived_metrics = {
        "medianLatestQuarterRevenueGrowthYoYPct": median(revenue_growth),
        "latestQuarterRevenueGrowthCoverage": len(revenue_growth),
        "fcfDeteriorationCount": sum(1 for value in fcf_deterioration if value),
        "fcfDeteriorationCoverage": len(fcf_deterioration),
        "fcfDeteriorationBreadthPct": (
            sum(1 for value in fcf_deterioration if value) / len(fcf_deterioration) * 100.0
            if fcf_deterioration else None
        ),
        "medianHyperscalerCapexGrowthYoYPct": median(hyperscaler_capex),
        "hyperscalerCapexCoverage": sum(1 for value in hyperscaler_capex if value is not None),
        "hyperscalersWithCapexCuts": sum(1 for value in hyperscaler_capex if value is not None and value <= -10.0),
    }
    us_bubble_risk = build_us_bubble_risk(prices, ai_basket, macro, derived_metrics)
    previous_risk = (previous_payload.get("market") or {}).get("usBubbleRisk") or {}
    if not previous_risk and previous_payload:
        try:
            previous_risk = build_us_bubble_risk(
                (previous_payload.get("market") or {}).get("series") or {},
                (previous_payload.get("market") or {}).get("aiBasket") or {},
                previous_payload.get("macro") or {},
                previous_payload.get("derived") or {},
            )
        except Exception:
            previous_risk = {}
    us_bubble_risk["previousUpdate"] = {
        "generatedAtUtc": previous_payload.get("generatedAtUtc"),
        "marketDate": previous_risk.get("asOfDate"),
        "score": previous_risk.get("score"),
        "scoreChange": (
            us_bubble_risk["score"] - previous_risk["score"]
            if us_bubble_risk.get("score") is not None and previous_risk.get("score") is not None else None
        ),
    }

    try:
        berkshire_monitor = build_berkshire_monitor()
        source_note = "SEC原表を再取得" if berkshire_monitor["thirteenF"]["directSecRefresh"] else "SEC公表済み原表の監査済み控えを使用"
        statuses.append(SourceStatus("SEC Berkshire 10-Q / 13F", berkshire_monitor["thirteenF"]["latest"]["sourceUrl"], True, NOW.isoformat(), source_note))
    except Exception as exc:
        berkshire_monitor = {}
        errors.append(f"Berkshire monitor: {exc}")
        statuses.append(SourceStatus("SEC Berkshire 10-Q / 13F", BERKSHIRE_13F_FALLBACK[0]["sourceUrl"], False, NOW.isoformat(), str(exc)))

    try:
        overseas_intelligence = build_overseas_intelligence()
        statuses.append(SourceStatus("Google News English RSS", "https://news.google.com/", True, NOW.isoformat(), f"{len(overseas_intelligence['newsItems'])} headlines"))
        statuses.append(SourceStatus("X recent search", "https://developer.x.com/en/docs/x-api", True, NOW.isoformat(), overseas_intelligence["x"]["message"]))
    except Exception as exc:
        overseas_intelligence = {"checkedAtUtc": NOW.isoformat(), "newsItems": [], "x": {"status": "failed", "items": [], "message": str(exc)}, "topicCounts": {}, "summary": "海外情報を更新できませんでした。", "readingRule": "数値は公式資料で確認する。"}
        errors.append(f"Overseas intelligence: {exc}")
        statuses.append(SourceStatus("Google News English RSS", "https://news.google.com/", False, NOW.isoformat(), str(exc)))

    payload = {
        "schemaVersion": 13,
        "generatedAtUtc": NOW.isoformat(),
        "generatedAtJst": NOW.astimezone(JST).isoformat(),
        "marketDate": prices.get("SOX", {}).get("date"),
        "dataQuality": {
            "successfulRequests": sum(1 for status in statuses if status.ok),
            "failedRequests": sum(1 for status in statuses if not status.ok),
            "companyCoverage": len(companies),
            "expectedCompanies": len(COMPANIES),
            "warnings": errors,
        },
        "market": {
            "series": strip_history(prices),
            "aiBasket": ai_basket,
            "usBubbleRisk": us_bubble_risk,
            "berkshireMonitor": berkshire_monitor,
            "japanAiBasket": {
                "label": "日本AI・半導体連動8社（本サイト独自・等ウェイト監視群）",
                "constituents": [company["ticker"] for company in japan_ai_companies],
                "medianDrawdown3yPct": median(japan_company_drawdowns),
                "breadthBelowSma200Pct": (japan_below_count / len(japan_ai_companies) * 100.0) if japan_ai_companies else None,
                "medianChange1dPct": median(company.get("change1dPct") for company in japan_ai_companies),
                "medianChange5dPct": median(company.get("change5dPct") for company in japan_ai_companies),
            },
            "normalizedChart": sampled_chart(prices) if "SOX" in prices else [],
            "historicalEpisodes": historical_episodes,
            "dotComComparison": build_dotcom_comparison(),
            "sakakibaraAnalysis": sakakibara_analysis,
            "nikkeiValuationReference": {
                "date": "2026-07-17",
                "indexPe": 22.99,
                "indexPb": 2.71,
                "marketCapPe": 17.42,
                "marketCapPb": 1.84,
                "impliedEps": 64141.12 / 17.42,
                "impliedBps": 64141.12 / 1.84,
                "impliedRoePct": (64141.12 / 17.42) / (64141.12 / 1.84) * 100.0,
                "price": 64141.12,
                "sourceUrl": "https://indexes.nikkei.co.jp/en/nkave/archives/summary?dt=07172026&idx=nk225",
                "note": "日経公式2026年7月17日の日次サマリー。市場全体の実力を見る時価総額ベースはPER 17.42倍・PBR 1.84倍、日経平均の値動きへの寄与を反映する指数ウエートベースはPER 22.99倍・PBR 2.71倍。終値64,141.12円。自動更新ではありません。",
            },
        },
        "macro": macro,
        "companies": companies,
        "derived": derived_metrics,
        "overseasIntelligence": overseas_intelligence,
        "manualInputs": {
            "forwardEpsRevision3mPct": None,
            "companiesWithEpsCuts": None,
            "memoryOrGpuPriceDropPct": None,
            "majorProjectCancellations90d": None,
            "supplierInventoryGapPctPoints": None,
            "note": "These fields require a consistent paid consensus series, product-level pricing, or verified project announcements. Missing is not zero.",
        },
        "sourceStatus": [status.__dict__ for status in statuses],
        "methodVersion": "4.0.0",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    sync_money_strategist_latest(prices.get("SP500"), cpi_history)
    try:
        from global_comparison import write_global_comparison
        comparison = write_global_comparison(request)
        print(f"Updated six-series comparison through {comparison['latestCommonMonth']}")
    except Exception as exc:
        print(f"Warning: retained previous six-series comparison package: {exc}")
    print(f"Wrote {OUTPUT} with {len(companies)} companies and {len(errors)} warnings")


if __name__ == "__main__":
    main()
