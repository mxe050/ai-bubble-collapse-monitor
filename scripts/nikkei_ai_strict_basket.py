#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Any

from nikkei_ai_public_proxy import (
    HISTORICAL_EVENTS, JST, OFFICIAL_DAILY_PAGE_URL, OFFICIAL_DAILY_URL,
    OFFICIAL_MONTHLY_URL, ROOT, fetch_official_csv, fetch_yahoo_close,
    monthly_check, years_before,
)

CONFIG_PATH = ROOT / 'config' / 'nikkei-ai-overheat-config.json'
OUTPUT_PATH = ROOT / 'data' / 'nikkei-ai-three-series.json'

CLASSIFICATION_SOURCES = [
    {'label':'キオクシア・AI推論時代の成長戦略','url':'https://www.kioxia-holdings.com/ja-jp/news/2026/20260602-1.html','used_for':'メモリ・SSDをAI推論インフラの構成要素として位置付ける根拠'},
    {'label':'ルネサス・Investor Relations','url':'https://www.renesas.com/en/about/investor-relations','used_for':'エッジAI・AIインフラ/コンピュートの戦略資料'},
    {'label':'DISCO・FY2025決算資料','url':'https://www.disco.co.jp/eg/ir/library/doc/film/20260422.pdf','used_for':'生成AI向け装置出荷の会社説明'},
    {'label':'レーザーテック・事業報告','url':'https://www.lasertec.co.jp/en/ir/plan/message.html','used_for':'AI起点のGPU・HBM設備投資に関する会社説明'},
    {'label':'フジクラ・事業説明資料','url':'https://www.fujikura.co.jp/eng/ir/statement/meeting/__icsFiles/afieldfile/2024/07/18/meeting_176_e.pdf','used_for':'生成AI拡大に伴うデータセンター光配線需要の会社説明'},
    {'label':'ソシオネクスト・AIデータセンターSoC','url':'https://www.socionext.com/jp/pr/TSMC_A14_chiplet/TSMC_A14_chiplet_e.pdf','used_for':'AIデータセンター向けカスタムSoCの会社発表'},
]


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


def pct(new: float | None, old: float | None) -> float | None:
    if new is None or old in (None, 0):
        return None
    return (new / old - 1) * 100


def code(value: Any, field: str) -> str:
    result = str(value or '').strip().upper()
    if not re.fullmatch(r'[0-9A-Z]{4}', result):
        raise ConfigurationError(f'{field} must be a four-character ticker')
    return result


def validate_members(value: Any, field: str, *, ai: bool) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ConfigurationError(f'{field}.members must be a non-empty list')
    result, seen = [], set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ConfigurationError(f'{field}.members[{index}] must be an object')
        item_code = code(raw.get('code'), f'{field}.members[{index}].code')
        if item_code in seen:
            raise ConfigurationError(f'{field}.members contains duplicate {item_code}')
        seen.add(item_code)
        name = str(raw.get('name') or '').strip()
        descriptor = str(raw.get('role' if ai else 'sector') or '').strip()
        if not name or not descriptor:
            raise ConfigurationError(f'{field}.members[{index}] is incomplete')
        item = {'code':item_code, 'symbol':item_code + '.T', 'name':name}
        item['role' if ai else 'sector'] = descriptor
        if ai:
            reason = str(raw.get('reason') or '').strip()
            if not reason:
                raise ConfigurationError(f'{field}.members[{index}].reason is required')
            item['reason'] = reason
        result.append(item)
    return result


def validate_config(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ConfigurationError('configuration must be an object')
    required = {'method_version','mode','lookback_years','comparison_lookback_years',
                'basket_return_method','classification_policy','minimum_active_ratio',
                'ai_exclusion_basket','non_ai_core_basket'}
    if required - set(payload):
        raise ConfigurationError('configuration keys are incomplete')
    if str(payload['method_version']) != '3.0' or payload['mode'] != 'strict-fixed-basket-proxy':
        raise ConfigurationError('strict fixed basket method v3 is required')
    if payload['lookback_years'] != 10 or payload['comparison_lookback_years'] != 3:
        raise ConfigurationError('lookback settings must be 10 years and 3 years')
    if payload['basket_return_method'] != 'daily-equal-weight-available-close-to-close':
        raise ConfigurationError('unsupported basket return method')
    if payload['classification_policy'] != 'fixed-business-exposure-list':
        raise ConfigurationError('classification must be a fixed business-exposure list')
    minimum = finite(payload['minimum_active_ratio'])
    if minimum is None or not .75 <= minimum <= 1:
        raise ConfigurationError('minimum_active_ratio must be 0.75..1')
    ai = validate_members((payload['ai_exclusion_basket'] or {}).get('members'), 'ai_exclusion_basket', ai=True)
    core = validate_members((payload['non_ai_core_basket'] or {}).get('members'), 'non_ai_core_basket', ai=False)
    if len(ai) < 16 or len(core) < 12:
        raise ConfigurationError('strict baskets are too narrow')
    overlap = {item['code'] for item in ai} & {item['code'] for item in core}
    if overlap:
        raise ConfigurationError('AI exclusion and non-AI core overlap: ' + ', '.join(sorted(overlap)))
    return {**payload, 'minimum_active_ratio':minimum,
            'ai_exclusion_basket':{**payload['ai_exclusion_basket'], 'members':ai},
            'non_ai_core_basket':{**payload['non_ai_core_basket'], 'members':core}}


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return validate_config(json.loads(path.read_text(encoding='utf-8')))


def weekly_sample(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        observed = row['date']
        iso = observed.isocalendar()
        selected[(iso.year, iso.week)] = row
    output = [selected[key] for key in sorted(selected)]
    if rows and output and output[0]['date'] != rows[0]['date']:
        output.insert(0, rows[0])
    return output


def rows_map(rows: list[dict[str, Any]]) -> dict[date, float]:
    result = {}
    for row in rows:
        observed, value = row.get('date'), finite(row.get('close'))
        if isinstance(observed, date) and value is not None and value > 0:
            result[observed] = value
    return result


def basket_path(days: list[date], prices: dict[str, dict[date, float]], members: list[dict[str, str]], minimum: int) -> list[dict[str, Any]]:
    result, index = [], None
    codes = [item['code'] for item in members]
    for position, observed in enumerate(days):
        active = [item for item in codes if observed in prices.get(item, {})]
        eligible = active if position == 0 else [item for item in codes if days[position - 1] in prices.get(item, {}) and observed in prices.get(item, {})]
        value = None
        if position == 0 and len(active) >= minimum:
            value = 100.0
        elif position and index is not None and len(eligible) >= minimum:
            change = sum(prices[item][observed] / prices[item][days[position - 1]] - 1 for item in eligible) / len(eligible)
            value = index * (1 + change)
        index = value
        result.append({'date':observed, 'value':round(value, 8) if value is not None else None,
                       'active_member_count':len(active), 'return_member_count':len(eligible)})
    return result


def component_row(item: dict[str, str], data: dict[str, Any], kind: str, start: date, end: date) -> dict[str, Any]:
    values = rows_map((data or {}).get('rows') or [])
    within = [(day, values[day]) for day in sorted(values) if start <= day <= end]
    first = within[0] if within else (None, None)
    latest = within[-1] if within else (None, None)
    peak = max(within, key=lambda row: row[1]) if within else (None, None)
    symbol = item['symbol']
    return {**item, 'basket':kind, 'classification_status':'fixed_exclusion' if kind == 'ai_exclusion' else 'fixed_non_ai_core',
            'first_price_date':first[0].isoformat() if first[0] else None, 'latest_price_date':latest[0].isoformat() if latest[0] else None,
            'latest_close':round(latest[1], 2) if latest[1] is not None else None,
            'comparison_return_pct':round(pct(latest[1], first[1]), 6) if latest[1] is not None and first[1] is not None else None,
            'peak_price_date':peak[0].isoformat() if peak[0] else None, 'peak_close':round(peak[1], 2) if peak[1] is not None else None,
            'drawdown_from_peak_pct':round(pct(latest[1], peak[1]), 6) if latest[1] is not None and peak[1] is not None else None,
            'price_source_url':(data or {}).get('source_url') or f'https://finance.yahoo.com/quote/{symbol}/history',
            'split_events':(data or {}).get('split_events') or [], 'data_status':'available' if within else 'price-unavailable'}


def window_return(rows: list[dict[str, Any]], field: str, target: date) -> dict[str, Any]:
    available = [row for row in rows if row['date'] >= target and finite(row.get(field)) is not None]
    if not available:
        return {'start_date':None, 'return_pct':None}
    first, last = available[0], available[-1]
    return {'start_date':first['date'].isoformat(), 'return_pct':round(pct(finite(last[field]), finite(first[field])), 6)}


def build_payload(config: dict[str, Any], *, yahoo_rows: list[dict[str, Any]], official_daily: list[dict[str, Any]], official_monthly: list[dict[str, Any]], prices: dict[str, dict[str, Any]], generated_at: datetime | None = None) -> dict[str, Any]:
    daily = rows_map(official_daily)
    end = max(daily)
    floor = years_before(end, int(config['lookback_years']))
    merged = {day:close for day, close in rows_map(yahoo_rows).items() if floor <= day <= end}
    merged.update({day:close for day, close in daily.items() if floor <= day <= end})
    actual = [{'date':day, 'close':close} for day, close in sorted(merged.items())]
    if len(actual) < 1000:
        raise RuntimeError('10-year Nikkei history is incomplete')
    cross = monthly_check(merged, official_monthly, actual[0]['date'])
    if cross['matched_months'] < 100:
        raise RuntimeError('monthly Nikkei cross-check is incomplete')
    comparison_floor = years_before(end, int(config['comparison_lookback_years']))
    start = next(row['date'] for row in actual if row['date'] >= comparison_floor)
    comparison = [row for row in actual if row['date'] >= start]
    days = [row['date'] for row in comparison]
    ai_members = config['ai_exclusion_basket']['members']
    core_members = config['non_ai_core_basket']['members']
    price_maps = {item_code:rows_map((data or {}).get('rows') or []) for item_code, data in prices.items()}
    ai_min = math.ceil(len(ai_members) * config['minimum_active_ratio'])
    core_min = math.ceil(len(core_members) * config['minimum_active_ratio'])
    ai_path = basket_path(days, price_maps, ai_members, ai_min)
    core_path = basket_path(days, price_maps, core_members, core_min)
    ai_by_date = {row['date']:row for row in ai_path}
    core_by_date = {row['date']:row for row in core_path}
    display_daily = []
    base_close = comparison[0]['close']
    for row in comparison:
        ai_row, core_row = ai_by_date[row['date']], core_by_date[row['date']]
        if finite(ai_row['value']) is None or finite(core_row['value']) is None:
            continue
        display_daily.append({'date':row['date'], 'nikkei_actual':100 * row['close'] / base_close,
                              'ai_basket':ai_row['value'], 'non_ai_core_basket':core_row['value'], 'nikkei_close':row['close'],
                              'ai_active_member_count':ai_row['active_member_count'], 'non_ai_active_member_count':core_row['active_member_count']})
    if len(display_daily) < 100:
        raise RuntimeError('strict basket has insufficient common daily coverage')
    display = [{**row, 'date':row['date'].isoformat(), 'nikkei_actual':round(row['nikkei_actual'], 6), 'nikkei_close':round(row['nikkei_close'], 2)} for row in weekly_sample(display_daily)]
    full = [{'date':row['date'].isoformat(), 'nikkei_actual':round(100 * row['close'] / actual[0]['close'], 6), 'nikkei_close':round(row['close'], 2)} for row in weekly_sample(actual)]
    ai_audit = [component_row(item, prices.get(item['code'], {}), 'ai_exclusion', start, end) for item in ai_members]
    core_audit = [component_row(item, prices.get(item['code'], {}), 'non_ai_core', start, end) for item in core_members]
    latest = display[-1]
    trump = date(2025, 1, 20)
    trump_window = {'reference':'2025-01-20（次の比較可能日から）', 'nikkei':window_return(display_daily, 'nikkei_actual', trump),
                    'ai_basket':window_return(display_daily, 'ai_basket', trump), 'non_ai_core':window_return(display_daily, 'non_ai_core_basket', trump)}
    return {
        'meta': {
            'title':'AI上昇銘柄を固定除外して日本株を見直す',
            'generated_at':(generated_at or datetime.now(JST)).isoformat(),
            'market_date':end.isoformat(),
            'start_date':actual[0]['date'].isoformat(),
            'end_date':end.isoformat(),
            'display_start_date':display[0]['date'],
            'display_end_date':display[-1]['date'],
            'base_value':100,
            'calculation_frequency':'daily',
            'display_frequency':'weekly',
            'nominal_chart_unit':'JPY',
            'dividends_included':False,
            'price_field':'Close（配当込みAdj Closeは使用しない）',
            'method_label':'固定AI除外・日次等ウェート比較',
            'comparison_status':'strict-fixed-basket-proxy',
            'synthetic_series_are_official':False,
            'nominal_chart_description':'日経平均は実額。AIバスケットと非AIコアは比較開始日の日経平均終値を起点に円換算する研究用比較で、公式指数・個別株価ではない。',
            'proxy_disclaimer':'AI除外は、画面に全社名を示す固定20社を比較期間を通じて除く方式です。株価が下落・反落しても再編入しません。非AIコアはAI直接受益を含まない固定16社で、日経225の公式除外指数ではありません。'
        },
        'summary': {
            'actual_full_period_return_pct':round(full[-1]['nikkei_actual'] - 100, 6),
            'comparison_actual_return_pct':round(latest['nikkei_actual'] - 100, 6),
            'ai_basket_return_pct':round(latest['ai_basket'] - 100, 6),
            'non_ai_core_return_pct':round(latest['non_ai_core_basket'] - 100, 6),
            'ai_minus_non_ai_percentage_points':round(latest['ai_basket'] - latest['non_ai_core_basket'], 6),
            'nikkei_minus_non_ai_percentage_points':round(latest['nikkei_actual'] - latest['non_ai_core_basket'], 6),
            'ai_exclusion_member_count':len(ai_members),
            'non_ai_core_member_count':len(core_members),
            'trump_window':trump_window
        },
        'quality': {
            'coverage_pct':round(100 * len(display_daily) / len(comparison), 6),
            'basket_return_method':config['basket_return_method'],
            'classification_policy':config['classification_policy'],
            'ai_minimum_active_members':ai_min,
            'non_ai_minimum_active_members':core_min,
            'ai_active_member_range':[min(row['ai_active_member_count'] for row in display_daily), max(row['ai_active_member_count'] for row in display_daily)],
            'non_ai_active_member_range':[min(row['non_ai_active_member_count'] for row in display_daily), max(row['non_ai_active_member_count'] for row in display_daily)],
            'monthly_crosscheck':cross,
            'data_state':'strict-fixed-basket-proxy',
            'membership_handling':'分類は事業エクスポージャーで固定。AIバスケットの株価反落・上場後の新規データは非AIコアへ戻さず、利用可能日のみ等ウェート計算に参加。',
            'price_method':'Yahoo Finance Close。配当込みAdj Closeは使わず、株式分割イベントを別途記録。',
            'candidate_price_audit':ai_audit + core_audit,
            'missing_items':[item['code'] for item in ai_audit + core_audit if item['data_status'] != 'available']
        },
        'ai_exclusion_members':ai_audit,
        'non_ai_core_members':core_audit,
        'actual_series':full,
        'series':display,
        'historical_events':[dict(item) for item in HISTORICAL_EVENTS if item['date'] <= end.isoformat()],
        'warnings':[
            'この比較は「AI以外の日本市場全体」を再構成した公式指数ではありません。AI直接受益を固定リストから排除した非AIコアの値動きを示します。',
            'キオクシアはAI推論用メモリ・SSDの分類を固定し、急騰後に価格が戻っても非AIコアへ再編入しません。'
        ],
        'sources':[
            {'label':'日経公式・日次終値','url':OFFICIAL_DAILY_PAGE_URL,'used_for':'日経平均の実額'},
            {'label':'日経公式・月次終値CSV','url':OFFICIAL_MONTHLY_URL,'used_for':'10年実額の月次クロスチェック'},
            {'label':'Yahoo Finance ^N225','url':'https://finance.yahoo.com/quote/%5EN225/history','used_for':'日付付きClose'},
            *CLASSIFICATION_SOURCES,
            {'label':'AI除外バスケット設定','url':'https://github.com/mxe050/ai-bubble-collapse-monitor/blob/main/config/nikkei-ai-overheat-config.json','used_for':'固定20社・非AI16社の全定義'}
        ]
    }


def atomic_write(path: Any, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def write_nikkei_ai_three_series(config_path: Any = CONFIG_PATH, output_path: Any = OUTPUT_PATH) -> dict[str, Any]:
    config = load_config(config_path)
    yahoo_data = fetch_yahoo_close('^N225')
    yahoo_rows = yahoo_data.get('rows') or []
    official_daily = fetch_official_csv(OFFICIAL_DAILY_URL)
    official_monthly = fetch_official_csv(OFFICIAL_MONTHLY_URL)
    all_members = config['ai_exclusion_basket']['members'] + config['non_ai_core_basket']['members']
    prices: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_yahoo_close, item['symbol']):item for item in all_members}
        for future in as_completed(futures):
            item = futures[future]
            symbol = item['symbol']
            try:
                prices[item['code']] = future.result()
            except Exception as error:
                prices[item['code']] = {'rows':[], 'source_url':f'https://finance.yahoo.com/quote/{symbol}/history', 'split_events':[], 'error':str(error)}
    payload = build_payload(config, yahoo_rows=yahoo_rows, official_daily=official_daily, official_monthly=official_monthly, prices=prices)
    atomic_write(output_path, payload)
    return payload


def main() -> int:
    try:
        payload = write_nikkei_ai_three_series()
    except Exception as error:
        print(f'nikkei strict basket failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps({'market_date':payload['meta']['market_date'], 'ai_members':len(payload['ai_exclusion_members']), 'non_ai_members':len(payload['non_ai_core_members'])}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
