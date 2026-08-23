# Financial Hub

Financial Hub is a local, English-language PyQt6 desktop application for tracking Taiwan securities in TWD. It keeps named portfolios, activity-aware transactions, delayed daily prices, owner cash flows, total profit, dividend income, XIRR, and 30-year projections in a local SQLite database.

The application is for personal record keeping and is not financial advice.

## Install and run

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/) are required.

```powershell
uv sync --dev
uv run financial-hub
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

All share quantities, TWD amounts, cached closes, profits, and projection values are stored and calculated as whole integers. Provider values and legacy decimal data are rounded to the nearest integer using half-up rounding.

- The transaction form asks for unsigned **Shares** and **Amount** values. The selected activity supplies the signs before the signed values are stored in the database.
- A **buy** stores positive shares and a negative amount.
- A **sell** stores negative shares and a positive amount.
- A **paid-out dividend** stores zero shares and a positive amount. Paid-out dividends are included in the reported dividend-income total.
- A **reinvested dividend** stores positive acquired shares and an amount of zero. It is an internal portfolio action and is not included in dividend-income totals.
- An **opening position** stores positive shares and a negative amount representing the value invested when tracking begins.

Holdings are derived by replaying transactions in date-and-ID order. Corrections are edits, and deleting a transaction permanently removes it. Transactions that would make a holding negative at any later point are rejected.

Total assets are the current market value of holdings. Total profit is total assets plus the signed sum of transaction amounts. XIRR measures owner-level cash flows and includes a terminal market-value flow on the valuation date; zero-amount reinvestments are ignored because they are internal to the portfolio. A result is shown as **Not calculable** if prices are missing or cash flows lack both signs.

## Data, backup, and migration

The database and non-secret preferences are stored under:

```text
%LOCALAPPDATA%\IRRCalculator
```

Back up `portfolio.sqlite3` while the application is closed. Price history is cached in the same database.

The legacy importer accepts the original SQLite `log(id, stock_code, time, amount)` table. Before importing, it makes a timestamped copy beside the selected source (or in the requested backup directory). The import is content-fingerprinted and idempotent: choosing an unchanged source twice creates no duplicates. Legacy amounts remain signed owner cash amounts in an **Imported portfolio**. Because the old data has no shares, reconcile each security with an opening position afterward. Legacy stock codes may need to be matched to current FinMind securities manually. Legacy opening positions are migrated to negative amounts; an opening position with no known historical value uses zero and remains unavailable for reliable profit/IRR until corrected. Any historical owner top-up or payout attached to a reinvestment is preserved as a separate legacy cash-flow record.

## Scope

Version 1 is local and single-user, supports Taiwan securities and TWD only, and refreshes delayed prices manually. It does not provide brokerage synchronization, real-time pricing, tax reporting, corporate-action automation, cloud sync, multi-currency accounting, or FIFO/LIFO basis.

The interface is English-only. Chinese security names are retained solely as provider data.
