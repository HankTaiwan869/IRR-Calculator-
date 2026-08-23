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

The first launch of a fresh default database fetches the FinMind security master and then imports the bundled legacy history. Price refreshes and charting remain explicit user actions.

## First use

1. Launch the application. It creates the v1 database, fetches FinMind names, exchanges, and security types, and then imports `legacy-investment.db` against those records.
2. If FinMind is unavailable, the application remains usable and retries the ordered bootstrap on the next launch. A token can be saved under **Settings** when needed; it is stored by `keyring` in Windows Credential Manager, not in SQLite or preferences.
3. Create portfolios, reconcile the imported security with an opening position, and add transactions.
4. Use **Refresh Prices** on the Dashboard when you want updated delayed closing prices.

FinMind is the default data provider. Its `TaiwanStockInfo` and `TaiwanStockPrice` datasets supply the local security master and delayed daily closes. Availability, quotas, and accuracy remain subject to FinMind's service; verify important values independently.

## Accounting conventions

Share quantities and transaction TWD amounts remain whole integers. Cached quote prices are stored as `Decimal` values with two decimal places, and market values, profits, XIRR terminal values, and projections retain those decimals during calculations. User-visible TWD values are rounded to whole dollars using half-up rounding; percentage displays retain decimal places.

- The transaction form asks for unsigned **Shares** and **Amount** values. The selected activity supplies the signs before the signed values are stored in the database.
- A **buy** stores positive shares and a negative amount.
- A **sell** stores negative shares and a positive amount.
- A **paid-out dividend** stores zero shares and a positive amount. Paid-out dividends are included in the reported dividend-income total.
- A **reinvested dividend** stores positive acquired shares and an amount of zero. It is an internal portfolio action and is not included in dividend-income totals.
- An **opening position** stores positive shares and a negative amount representing the value invested when tracking begins.

Holdings are derived by replaying transactions in date-and-ID order. Corrections are edits, and deleting a transaction permanently removes it. Transactions that would make a holding negative at any later point are rejected.

Total assets are the current market value of holdings. Total profit is total assets plus the signed sum of transaction amounts. XIRR measures owner-level cash flows and includes a terminal market-value flow on the valuation date; zero-amount reinvestments are ignored because they are internal to the portfolio. A result is shown as **Not calculable** if prices are missing or cash flows lack both signs.

## Data, backup, and first-run import

The database and non-secret preferences are stored under:

```text
%LOCALAPPDATA%\IRRCalculator
```

The application creates a fresh v1 database under `%LOCALAPPDATA%\IRRCalculator`; an older application database is not migrated or read. Back up the active database while the application is closed. Price history is cached in the same database.

The one-time importer reads the original SQLite `log(id, stock_code, time, amount)` table from `legacy-investment.db` after the FinMind security master has been synced. Legacy rows remain signed owner cash amounts in an **Imported portfolio**, and their stock codes are attached to matching FinMind security records. Legacy transaction amounts are rounded to whole TWD using half-up rounding. Because the old data has no shares, reconcile each security with an opening position afterward. The importer is bootstrap functionality, not a general migration or backward-compatibility layer.

## Scope

Version 1 is local and single-user, supports Taiwan securities and TWD only, and refreshes delayed prices manually. It does not provide brokerage synchronization, real-time pricing, tax reporting, corporate-action automation, cloud sync, multi-currency accounting, or FIFO/LIFO basis.

The interface is English-only. Chinese security names are retained solely as provider data.
