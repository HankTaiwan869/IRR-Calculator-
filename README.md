# IRR Calculator

IRR Calculator is a local, English-language PyQt6 desktop application for tracking Taiwan securities in TWD. It keeps named portfolios, signed-share transactions, delayed daily prices, moving-average cost basis, realized and unrealized profit, dividend income, XIRR, and 30-year projections in a local SQLite database.

The application is for personal record keeping and is not financial advice.

## Install and run

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/) are required.

```powershell
uv sync --dev
uv run irr-calculator
```

For a development launch, `uv run python main.py` is equivalent. Run the test suite with:

```powershell
uv run pytest
```

Startup is deliberately offline. The application does not read credentials, contact FinMind, or import the charting backend until the associated feature is used.

## First use

1. Open **Settings** and save a FinMind API token. The token is stored by `keyring` in Windows Credential Manager, not in SQLite or preferences.
2. Select **Sync Security Master**. Security codes are then available for exact-symbol entry on Transactions.
3. Create portfolios and add transactions.
4. Use **Refresh Prices** on the Dashboard when you want updated delayed closing prices.

FinMind is the default data provider. Its `TaiwanStockInfo` and `TaiwanStockPrice` datasets supply the local security master and delayed daily closes. Availability, quotas, and accuracy remain subject to FinMind's service; verify important values independently.

## Accounting conventions

All share quantities, TWD amounts, cached closes, cost-basis values, profits, and projection values are stored and calculated as whole integers. Provider values and legacy decimal data are rounded to the nearest integer using half-up rounding.

- A **buy** has positive shares and negative external cash. The cash flow equals the negative trade amount.
- A **sell** has negative shares and positive external cash. The cash flow equals the trade amount.
- A **paid-out dividend** has zero shares and positive income/external cash.
- A **reinvested dividend** has positive acquired shares, dividend income, and total acquisition cost. A fully reinvested dividend has zero external cash flow. If income and purchase cost differ, enter the positive paid remainder or negative owner top-up as the external cash flow.
- An **opening position** records reconciled shares with zero cash. Its optional total cost seeds moving-average basis; basis-dependent results are marked incomplete when that cost is omitted.

Holdings are derived by replaying transactions in date-and-ID order. Buys and reinvestments add acquisition cost; sells relieve the pre-sale moving-average cost. Corrections are soft deletes or edits with before/after audit records. Transactions that would make a holding negative at any later point are rejected.

XIRR measures owner-level external cash. It includes a terminal market-value flow on the valuation date, but excludes fully reinvested dividends because they are internal to the portfolio. A result is shown as **Not calculable** if prices are missing or cash flows lack both signs.

## Data, backup, and migration

The database and non-secret preferences are stored under:

```text
%LOCALAPPDATA%\IRRCalculator
```

Back up `portfolio.sqlite3` while the application is closed. Price history is cached in the same database.

The legacy importer accepts the original SQLite `log(id, stock_code, time, amount)` table. Before importing, it makes a timestamped copy beside the selected source (or in the requested backup directory). The import is content-fingerprinted and idempotent: choosing an unchanged source twice creates no duplicates. Legacy amounts remain owner cash flows in an **Imported portfolio**. Because the old data has no shares or cost information, reconcile each security with an opening position afterward. Legacy stock codes may need to be matched to current FinMind securities manually.

## Scope

Version 1 is local and single-user, supports Taiwan securities and TWD only, and refreshes delayed prices manually. It does not provide brokerage synchronization, real-time pricing, tax reporting, corporate-action automation, cloud sync, multi-currency accounting, or FIFO/LIFO basis.

The interface is English-only. Chinese security names are retained solely as provider data.
