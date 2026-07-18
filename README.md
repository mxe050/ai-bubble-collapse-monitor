# AI Bubble Collapse Monitor

An evidence-oriented Japanese dashboard that separates four questions:

1. Are AI-linked equities priced above a transparent fundamental-value scenario?
2. Has the price regime changed from momentum to a persistent drawdown?
3. Are earnings, free cash flow, and hyperscaler capital spending deteriorating?
4. Has that deterioration reached suppliers or credit markets?

The site does **not** treat a high valuation or a one-day selloff as proof that a
bubble has collapsed. It reports observed evidence, unknown inputs, model
assumptions, and scenario ranges separately.

## Data flow

GitHub Actions runs `scripts/update_data.py` every six hours and before each Pages
deployment. It retrieves:

- price histories from Yahoo Finance's public chart endpoint;
- standardized financial time series from Yahoo Finance, with links back to each
  company's investor-relations page for verification;
- high-yield credit spreads and the 10-year real yield from FRED.

Inputs that cannot be obtained consistently without a paid consensus feed or manual
verification remain `null`. The dashboard never silently converts missing data to zero.

## Local update

```powershell
python scripts/update_data.py
python -m http.server 8000
```

Then open `http://localhost:8000`.

## Important limitation

The DCF and reverse-DCF results are scenario calculations, not objective target prices
or investment recommendations. Fundamental value is unobservable and highly sensitive
to free cash flow, discount rate, terminal growth, competition, dilution, and cyclicality.

