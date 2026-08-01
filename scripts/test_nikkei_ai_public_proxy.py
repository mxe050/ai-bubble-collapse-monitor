#!/usr/bin/env python3
"""Network-free invariants for the strict fixed AI-exclusion basket."""

from __future__ import annotations

import copy
import json
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import nikkei_ai_strict_basket as strict  # noqa: E402


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def market_days(start: date, end: date) -> list[date]:
    output: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            output.append(current)
        current += timedelta(days=1)
    return output


def fixture() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    config = strict.load_config(ROOT / 'config' / 'nikkei-ai-overheat-config.json')
    days = market_days(date(2016, 8, 1), date(2026, 7, 31))
    actual = [{'date':day, 'close':16000.0 + index * 5.0} for index, day in enumerate(days)]
    month_end: dict[tuple[int, int], dict[str, Any]] = {}
    for row in actual:
        observed = row['date']
        month_end[(observed.year, observed.month)] = row
    monthly = [{'date':date(year, month, 1), 'close':row['close']} for (year, month), row in sorted(month_end.items())]

    prices: dict[str, dict[str, Any]] = {}
    ai_codes = {item['code'] for item in config['ai_exclusion_basket']['members']}
    all_members = config['ai_exclusion_basket']['members'] + config['non_ai_core_basket']['members']
    for member_index, item in enumerate(all_members):
        start = date(2024, 12, 18) if item['code'] == '285A' else days[0]
        rows = []
        base = 900.0 + member_index * 37.0
        daily_gain = .00060 if item['code'] in ai_codes else .00024
        for index, day in enumerate(days):
            if day < start:
                continue
            close = base * ((1 + daily_gain) ** index)
            rows.append({'date':day, 'close':close})
        prices[item['code']] = {
            'rows':rows,
            'source_url':'https://example.test/' + item['symbol'],
            'split_events':[]
        }
    return config, list(actual), list(actual), monthly, prices


def finite_tree(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, list):
        return all(finite_tree(item) for item in value)
    if isinstance(value, dict):
        return all(finite_tree(item) for item in value.values())
    return False


def build_payload() -> dict[str, Any]:
    config, yahoo, official, monthly, prices = fixture()
    return strict.build_payload(
        config,
        yahoo_rows=yahoo,
        official_daily=official,
        official_monthly=monthly,
        prices=prices,
        generated_at=datetime(2026, 8, 1, 0, 0, tzinfo=strict.JST),
    )


def test_fixed_baskets_and_kioxia() -> None:
    payload = build_payload()
    meta, summary, quality = payload['meta'], payload['summary'], payload['quality']
    ai = payload['ai_exclusion_members']
    core = payload['non_ai_core_members']
    require(meta['comparison_status'] == 'strict-fixed-basket-proxy', 'strict status is missing')
    require(len(ai) == 20 and len(core) == 16, 'fixed basket counts changed')
    ai_codes = {item['code'] for item in ai}
    core_codes = {item['code'] for item in core}
    require(not ai_codes & core_codes, 'AI and non-AI baskets overlap')
    kioxia = next(item for item in ai if item['code'] == '285A')
    require(kioxia['classification_status'] == 'fixed_exclusion', 'Kioxia must remain fixed excluded')
    require(kioxia['first_price_date'] == '2024-12-18', 'Kioxia must not be backfilled before listing')
    require('285A' not in core_codes, 'Kioxia cannot enter the non-AI core after a pullback')
    require(payload['series'][0]['nikkei_actual'] == 100, 'comparison Nikkei must start at 100')
    require(payload['series'][0]['ai_basket'] == 100, 'AI basket must start at 100')
    require(payload['series'][0]['non_ai_core_basket'] == 100, 'non-AI core must start at 100')
    require(quality['coverage_pct'] == 100, 'common daily basket coverage must remain complete')
    require(quality['ai_active_member_range'][0] == 19, 'Kioxia listing gap must be explicit in AI active count')
    require(summary['ai_basket_return_pct'] > summary['non_ai_core_return_pct'], 'fixture must distinguish AI and non-AI paths')
    require(finite_tree(payload), 'payload contains non-finite values')


def test_configuration_guards() -> None:
    raw = json.loads((ROOT / 'config' / 'nikkei-ai-overheat-config.json').read_text(encoding='utf-8'))
    invalid = copy.deepcopy(raw)
    invalid['non_ai_core_basket']['members'][0]['code'] = invalid['ai_exclusion_basket']['members'][0]['code']
    try:
        strict.validate_config(invalid)
    except strict.ConfigurationError:
        pass
    else:
        raise AssertionError('overlapping baskets must be rejected')


def main() -> None:
    test_fixed_baskets_and_kioxia()
    test_configuration_guards()
    print('Strict fixed AI-exclusion basket tests passed')


if __name__ == '__main__':
    main()
