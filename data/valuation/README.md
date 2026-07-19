# Point-in-time valuation provider files

The production chart never invents historical theoretical values. Add a licensed,
audited provider export only when it can reproduce historical membership,
availability dates, weights, corporate actions and financial statements.

Expected files:

- `sp500-point-in-time.json`
- `nikkei225-point-in-time.json`

Minimal schema:

```json
{
  "schemaVersion": 1,
  "index": "sp500",
  "updatedAt": "2026-07-20T00:00:00Z",
  "source": "Licensed provider and dataset version",
  "models": ["FCFF DCF", "FCFE", "dividend discount", "residual income"],
  "observations": [
    {
      "date": "2026-06-30",
      "theoreticalIndex": 1234.56,
      "reportAvailableDate": "2026-06-28",
      "financialAsOfDate": "2026-03-31",
      "availableCompanies": 485,
      "totalCompanies": 503,
      "coverageRatio": 0.942,
      "weightedWaccPct": 8.4,
      "weightedPerpetualGrowthPct": 2.6,
      "source": "Licensed provider and point-in-time snapshot",
      "models": ["FCFF DCF", "FCFE"]
    }
  ]
}
```

Validation rules:

- `reportAvailableDate` must not be later than the valuation `date`.
- `theoreticalIndex` must be positive.
- WACC must exceed perpetual growth.
- Coverage below 80% remains missing; companies without valuations are not zero.
- Current membership or current fundamentals must not be backfilled into history.
- A valid observation may be carried forward until the next public information
  snapshot, but future values and linear interpolation are prohibited.
