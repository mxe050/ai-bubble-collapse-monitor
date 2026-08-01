#!/usr/bin/env python3
"""Schema and invariant audit for the strict fixed AI-exclusion package."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'nikkei-ai-three-series.json'
CONFIG = ROOT / 'config' / 'nikkei-ai-overheat-config.json'


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def has_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, list):
        return any(has_non_finite(item) for item in value)
    if isinstance(value, dict):
        return any(has_non_finite(item) for item in value.values())
    return False


def validate() -> None:
    payload = json.loads(DATA.read_text(encoding='utf-8'))
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    meta, summary, quality = payload['meta'], payload['summary'], payload['quality']
    require(config['method_version'] == '3.0', 'strict method v3 config is missing')
    require(config['mode'] == 'strict-fixed-basket-proxy', 'strict mode is missing')
    require(meta['comparison_status'] == 'strict-fixed-basket-proxy', 'strict data status is missing')
    require(meta['calculation_frequency'] == 'daily' and meta['display_frequency'] == 'weekly', 'frequency is wrong')
    require(meta['dividends_included'] is False and 'Adj Close' in meta['price_field'], 'price-field disclosure is wrong')
    require(meta['synthetic_series_are_official'] is False, 'basket comparison cannot be official')
    require(datetime.fromisoformat(meta['generated_at']).tzinfo is not None, 'generation time needs timezone')
    require(date.fromisoformat(meta['start_date']) <= date.fromisoformat(meta['market_date']) <= date.fromisoformat(meta['end_date']), 'market dates are invalid')
    require(meta['nominal_chart_unit'] == 'JPY', 'nominal chart must disclose JPY')
    require('official' in meta['proxy_disclaimer'].lower() or '公式' in meta['proxy_disclaimer'], 'official-index disclaimer is missing')

    actual = payload['actual_series']
    display = payload['series']
    require(len(actual) >= 500, '10-year actual series is incomplete')
    actual_dates = [date.fromisoformat(row['date']) for row in actual]
    require(actual_dates == sorted(actual_dates) and len(actual_dates) == len(set(actual_dates)), 'actual dates are invalid')
    require(actual[0]['nikkei_actual'] == 100, 'actual full-period base must be 100')
    base = num(actual[0]['nikkei_close'])
    require(base is not None and base > 0, 'actual base close is invalid')
    for row in actual:
        close, index = num(row['nikkei_close']), num(row['nikkei_actual'])
        require(close is not None and index is not None and abs(index - 100 * close / base) <= .02, 'actual path changed')

    require(display and display[0]['date'] == meta['display_start_date'] and display[-1]['date'] == meta['display_end_date'], 'display dates are invalid')
    require(display[0]['nikkei_actual'] == display[0]['ai_basket'] == display[0]['non_ai_core_basket'] == 100, 'three paths need common base')
    require(all(num(row['nikkei_actual']) is not None and num(row['ai_basket']) is not None and num(row['non_ai_core_basket']) is not None for row in display), 'display values are missing')

    ai, core = payload['ai_exclusion_members'], payload['non_ai_core_members']
    expected_ai = {item['code'] for item in config['ai_exclusion_basket']['members']}
    expected_core = {item['code'] for item in config['non_ai_core_basket']['members']}
    ai_codes, core_codes = {item['code'] for item in ai}, {item['code'] for item in core}
    require(ai_codes == expected_ai and core_codes == expected_core, 'published membership diverges from config')
    require(len(ai) == 20 and len(core) == 16 and not ai_codes & core_codes, 'strict baskets are incomplete or overlap')
    require(all(item['classification_status'] == 'fixed_exclusion' for item in ai), 'AI membership must be fixed')
    require(all(item['classification_status'] == 'fixed_non_ai_core' for item in core), 'non-AI membership must be fixed')
    kioxia = next((item for item in ai if item['code'] == '285A'), None)
    require(kioxia is not None and kioxia['first_price_date'] >= '2024-12-18', 'Kioxia listing date is wrong')
    require('285A' not in core_codes, 'Kioxia cannot be reintroduced into the non-AI core')

    coverage = num(quality['coverage_pct'])
    require(coverage is not None and coverage >= 99.9, 'strict common coverage is incomplete')
    require(quality['data_state'] == meta['comparison_status'], 'quality state diverges')
    require(quality['basket_return_method'] == config['basket_return_method'], 'basket formula differs from config')
    require(quality['classification_policy'] == config['classification_policy'], 'classification differs from config')
    require(quality['ai_active_member_range'][0] >= quality['ai_minimum_active_members'], 'AI basket violates its minimum membership')
    require(quality['non_ai_active_member_range'][0] >= quality['non_ai_minimum_active_members'], 'non-AI basket violates its minimum membership')
    require(len(quality['candidate_price_audit']) == 36, 'component price audit is incomplete')
    require(all(isinstance(item.get('split_events'), list) for item in quality['candidate_price_audit']), 'split-event audit is invalid')

    trump = summary['trump_window']
    require(all(num(trump[key]['return_pct']) is not None for key in ('nikkei', 'ai_basket', 'non_ai_core')), 'Trump-period comparison is incomplete')
    require(num(summary['ai_minus_non_ai_percentage_points']) is not None, 'AI minus non-AI gap is missing')

    events = payload.get('historical_events') or []
    event_dates = [date.fromisoformat(row['date']) for row in events]
    require(len(events) >= 8, 'historical event timeline is incomplete')
    require(event_dates == sorted(event_dates) and len(event_dates) == len(set(event_dates)), 'historical events must be chronological')
    require(all(item <= date.fromisoformat(meta['market_date']) for item in event_dates), 'future historical event is invalid')
    require(all(str(row.get('source_url') or '').startswith('https://') for row in events), 'historical event source must be HTTPS')
    require(all(str(row.get('url') or '').startswith('https://') for row in payload['sources']), 'sources must be HTTPS')

    app_js = (ROOT / 'app.js').read_text(encoding='utf-8')
    require('renderNikkeiAiStrictBasketV2' in app_js and 'strict-fixed-basket-proxy' in app_js, 'strict basket UI is missing')
    require(not has_non_finite(payload), 'payload contains NaN or infinity')


def main() -> None:
    validate()
    print('Strict fixed AI-exclusion validation passed')


if __name__ == '__main__':
    main()
