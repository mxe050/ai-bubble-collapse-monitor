#!/usr/bin/env python3
"""Build the public data package for the AI bubble monitor.

The script intentionally runs outside the browser. Market-data providers
restrict CORS or require identifying headers, so a scheduled GitHub Action is a
more reliable and auditable place to collect the inputs than visitors' browsers.
"""

from __future__ import annotations

import csv
import io
import json
import math
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
PRICE_SYMBOLS = {"SOX": "^SOX", "NASDAQ": "^IXIC", "NIKKEI": "^N225", **{k: k for k in COMPANIES}}
HYPERSCALERS = {"MSFT", "GOOGL", "AMZN", "META"}

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
    "quarterlyTotalRevenue",
    "quarterlyFreeCashFlow",
    "quarterlyCapitalExpenditure",
    "quarterlyCashCashEquivalentsAndShortTermInvestments",
    "quarterlyCashAndCashEquivalents",
    "quarterlyTotalDebt",
]


@dataclass
class SourceStatus:
    name: str
    url: str
    ok: bool
    retrieved_at: str
    note: str = ""


def request(url: str, *, timeout: int = 35, attempts: int = 3) -> bytes:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/csv,text/plain,*/*",
    }
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
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=5y&interval=1d&events=div%2Csplits"
    payload = get_json(url)
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    quote = result["indicators"]["quote"][0]
    closes = quote.get("close", [])
    highs = quote.get("high", [])
    points: list[dict[str, Any]] = []
    for index, (timestamp, close) in enumerate(zip(timestamps, closes)):
        value = finite(close)
        if value is None:
            continue
        high = finite(highs[index]) if index < len(highs) else None
        date = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
        points.append({"date": date, "close": value, "high": high if high is not None else value})
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
        "peak3y": peak_row["close"],
        "peak3yDate": peak_row["date"],
        "drawdown3yPct": (1.0 - last / peak_row["close"]) * 100.0,
        "peak2026": peak_2026_row["high"] if peak_2026_row else None,
        "peak2026Date": peak_2026_row["date"] if peak_2026_row else None,
        "drawdownFrom2026HighPct": (1.0 - last / peak_2026_row["high"]) * 100.0 if peak_2026_row else None,
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
        "drawdown3yPct": price["drawdown3yPct"],
        "peak2026": price.get("peak2026"),
        "peak2026Date": price.get("peak2026Date"),
        "drawdownFrom2026HighPct": price.get("drawdownFrom2026HighPct"),
        "belowSma200": price["belowSma200"],
        "weeksBelowSma200": price["weeksBelowSma200"],
        "marketCap": market_cap,
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
    return {
        "seriesId": series_id,
        "date": last_date,
        "valuePct": last_value,
        "change3mPctPoints": last_value - prior,
        "riseFrom3mLowPctPoints": last_value - low_3m,
        "declineFrom3mHighPctPoints": high_3m - last_value,
        "high3mPct": high_3m,
        "sourceUrl": f"https://fred.stlouisfed.org/series/{series_id}",
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


def main() -> None:
    statuses: list[SourceStatus] = []
    errors: list[str] = []
    prices: dict[str, dict[str, Any]] = {}
    companies: list[dict[str, Any]] = []
    historical_episodes: list[dict[str, Any]] = []

    for label, symbol in PRICE_SYMBOLS.items():
        try:
            prices[label] = fetch_price_series(symbol)
            statuses.append(SourceStatus("Yahoo Finance chart", prices[label]["sourceUrl"], True, NOW.isoformat(), label))
        except Exception as exc:  # keep other sources usable if one ticker fails
            errors.append(f"Price {label}: {exc}")
            statuses.append(SourceStatus("Yahoo Finance chart", f"https://finance.yahoo.com/quote/{symbol}", False, NOW.isoformat(), str(exc)))

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
    for key, series in {"highYieldOas": "BAMLH0A0HYM2"}.items():
        try:
            macro[key] = fetch_fred(series)
            statuses.append(SourceStatus("FRED", macro[key]["sourceUrl"], True, NOW.isoformat(), series))
        except Exception as exc:
            errors.append(f"FRED {series}: {exc}")
            statuses.append(SourceStatus("FRED", f"https://fred.stlouisfed.org/series/{series}", False, NOW.isoformat(), str(exc)))

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
    payload = {
        "schemaVersion": 8,
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
            "aiBasket": {
                "constituents": [company["ticker"] for company in overseas_ai_companies],
                "medianDrawdown3yPct": median(company_drawdowns),
                "breadthBelowSma200Pct": (below_count / len(overseas_ai_companies) * 100.0) if overseas_ai_companies else None,
                "medianChange1dPct": median(company.get("change1dPct") for company in overseas_ai_companies),
                "medianChange5dPct": median(company.get("change5dPct") for company in overseas_ai_companies),
            },
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
            "nikkeiValuationReference": {
                "date": "2026-07-17",
                "indexPe": 22.99,
                "indexPb": 2.71,
                "price": 64141.12,
                "sourceUrl": "https://indexes.nikkei.co.jp/en/nkave/archives/summary?dt=07172026&idx=nk225",
                "note": "日経公式2026年7月17日の日次サマリーにある指数ベースPER 22.99倍・PBR 2.71倍・終値64,141.12円。自動更新ではありません。",
            },
        },
        "macro": macro,
        "companies": companies,
        "derived": {
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
        },
        "manualInputs": {
            "forwardEpsRevision3mPct": None,
            "companiesWithEpsCuts": None,
            "memoryOrGpuPriceDropPct": None,
            "majorProjectCancellations90d": None,
            "supplierInventoryGapPctPoints": None,
            "note": "These fields require a consistent paid consensus series, product-level pricing, or verified project announcements. Missing is not zero.",
        },
        "sourceStatus": [status.__dict__ for status in statuses],
        "methodVersion": "3.5.0",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT} with {len(companies)} companies and {len(errors)} warnings")


if __name__ == "__main__":
    main()
