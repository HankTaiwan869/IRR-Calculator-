# PyQt6 Portfolio Tracker Reimplementation Plan

Reimplement the original Streamlit calculator as a fast-starting, local PyQt6 desktop application for Taiwan securities. Preserve XIRR and projections while adding named portfolios, signed-share transactions, a local security master, manually refreshed daily prices, moving-average cost basis, auditable corrections, and explicit handling for fully reinvested dividends.

The interface is English-only. Chinese security names remain provider data, not interface translations. Use a persistent left navigation sidebar with a modern Qt desktop layout, clear visual hierarchy, and comfortable typography.

## Reimplementation Guardrails

- Keep domain, persistence, provider, and UI code separate. Domain services must be testable without importing PyQt6 or creating a `QApplication`.
- Keep startup offline. Do not fetch provider data, access keyring, or initialize heavy charting components before the main window is visible.
- Use one SQLAlchemy engine and short-lived sessions. Background work must create its own sessions and return immutable results to the UI through Qt signals.
- Store and calculate share quantities and TWD values as whole integers. Use floating point only for IRR, percentage rates, and chart coordinates.
- Make the package installable from the beginning with an explicit build backend and console entry point. Keep `pyproject.toml` as the only dependency source.
- Dispose SQLite engines in tests before temporary directories are removed, especially on Windows.
- Centralize colors, typography, spacing, control heights, border radii, and other UI tokens in `ui/theme.py` or a shared QSS stylesheet.
- Prefer Qt layouts over fixed positioning. Views must resize correctly across supported window sizes and display scaling.
- Use Qt's model/view architecture for nontrivial tables and lists rather than populating widgets row by row.
- Implement one vertical slice at a time: schema, domain service, focused test, then UI.

## Phase 1: Foundation and Storage

1. Replace Streamlit with a lightweight `main.py` launcher and packaged `irr_calculator` application. Use PyQt6, Plotly, SQLAlchemy, pyxirr, httpx, keyring, and pytest. Remove Streamlit, pandas, Matplotlib, CustomTkinter/Tkinter dependencies, and duplicate dependency files. Keep `uv` as the dependency and run workflow.

2. Store user data under `%LOCALAPPDATA%\IRRCalculator`. Keep the SQLite database and non-secret preferences there; store the FinMind token in Windows Credential Manager through `keyring`. Startup initializes local state only, without network access.

3. Introduce a versioned SQLite schema with `portfolios`, `securities`, `transactions`, `quotes`, `transaction_audit`, `schema_meta`, and `import_runs`. Enable SQLite foreign keys on every connection. Enforce unique portfolio names, unique provider/security symbols, soft deletion, indexed transaction filters, positive quote constraints, and integer monetary/share fields. Derive holdings from transactions instead of storing a second mutable holdings total.

4. Define `transactions` around separate accounting concepts: `kind`, signed `shares_delta`, signed `external_cash_flow`, nonnegative `trade_amount`, nonnegative `income_amount`, dates, portfolio/security references, timestamps, and `deleted_at`.

## Phase 2: Migration and Domain Rules

5. Add an idempotent legacy importer for the old `log(id, stock_code, time, amount)` table. Back up the source database, create an "Imported portfolio," create missing securities, and preserve each legacy amount as a `LEGACY_CASH_FLOW` used by XIRR. Follow import with a reconciliation workflow that records current shares and optional total/average cost per security as zero-cash `OPENING_POSITION` entries. Flag cost-basis metrics as incomplete when opening cost is omitted.

6. Implement transaction validation and audit-aware CRUD. Standard entries use signed shares and signed external cash: positive shares with negative cash for buys, negative shares with positive cash for sells, and zero shares with positive cash for paid-out dividends. Validate accounting consistency on create and edit. Edits and deletes append before/after snapshots to `transaction_audit`; deletes are soft. Replay affected ledgers after backdated changes. Prevent operations that would make holdings negative at any later date.

7. Add a dedicated `REINVESTED_DIVIDEND` transaction workflow. Record net dividend as `income_amount`, acquired shares as positive `shares_delta`, and total acquisition cost as `trade_amount`. For a fully reinvested dividend, set `external_cash_flow` to zero. Increase moving-average basis by the acquisition cost, count the dividend as income, and exclude it from XIRR external flows. If dividend cash and purchase cost differ, require the residual to be classified as a paid-out remainder or owner top-up.

8. Implement moving-average cost basis by replaying each portfolio/security ledger in date-and-ID order. Buys and reinvested dividends add shares and acquisition cost. Sells relieve the pre-sale average cost and calculate realized trading profit from net proceeds. Cash and reinvested dividends contribute dividend income. Include closed ledgers in realized-profit and dividend totals.

9. Implement analytics for individual portfolios and all portfolios combined. XIRR uses owner-level external cash flows plus one terminal market-value cash flow on the valuation date. Reinvested dividends contribute zero external flow. Preserve annual/monthly IRR and configurable 30-year scenarios. Return explicit "not calculable" states for insufficient sign changes or missing valuations.

## Phase 3: Taiwan Security Data and Prices

10. Add a provider protocol and FinMind implementation so services and tests do not depend directly on HTTP details. Use `TaiwanStockInfo` for TWSE/TPEx/emerging stocks and ETFs, and per-symbol `TaiwanStockPrice` daily closing data. Normalize provider errors, timeouts, malformed payloads, empty/zero prices, and rate-limit responses. Redact the token from all errors before they reach logs or dialogs.

11. Sync the security master into SQLite on first use or from Settings, never during blocking startup. Accept a plain exact security symbol on the Transactions form without live search or completion.

12. Add manual **Refresh Prices** actions for the selected portfolio and all portfolios. Run provider work through `QThreadPool`/`QRunnable` or dedicated `QThread` workers. Each worker owns its database session and emits progress, result, and error signals back to the GUI thread. Upsert quotes by symbol/provider/market date, retain the last cached quote on failure, and skip quotes already fetched for the current daily cycle unless the user explicitly retries.

## Phase 4: PyQt6 Desktop Experience

13. Build the application shell around `QMainWindow`. Use:
   - a persistent left sidebar for primary navigation;
   - a `QStackedWidget` for page content;
   - a top page header for title, portfolio context, and page-level actions;
   - a status bar for short-lived operational feedback where useful.

   Navigation items are Dashboard, Projection, Transactions, History, Portfolios, and Settings. Give the active item a clear selected state. Preserve the selected portfolio and relevant page state when switching views.

14. Give the UI a restrained modern desktop style rather than reproducing a web dashboard. Use Qt-native interaction patterns with a light custom QSS layer:
   - clear section hierarchy;
   - generous but compact spacing;
   - consistent control heights;
   - subtle borders and rounded panels where appropriate;
   - standard hover, focus, disabled, warning, and destructive states;
   - platform-appropriate dialogs and keyboard navigation.

   Prefer system fonts. Target roughly 13-14 pt body/control text, 17-18 pt section headings, and 22-24 pt page headings, adjusted for Qt DPI scaling. Avoid manually scaling every widget.

15. Build **Dashboard** as a scrollable summary page. Include a portfolio/all-portfolios selector, summary metric cards for total assets, total/realized/unrealized profit, dividend income, and annual/monthly IRR. Place charts below the summary area with configurable 30-year projection controls and a prominent manual refresh action. Lazily create chart widgets when Dashboard is first opened.

16. Build **Transactions** as a structured form rather than a dense grid. Use a portfolio `QComboBox`, a plain security-symbol `QLineEdit`, `QDateEdit` for dates, numeric editors with validation, and clear form sections. Provide distinct transaction modes for regular activity and **Reinvested Dividend** so the compound accounting behavior is visible rather than hidden.

17. Build **History** around `QTableView` with a custom `QAbstractTableModel` and optional `QSortFilterProxyModel`. Put filters in a compact toolbar or collapsible filter area above the table. Support sorting, portfolio/security/date/kind/deleted-state filters, selection-based actions, and context menus where appropriate. Use dialogs for edit, delete confirmation, restore, and audit details.

18. Build **Portfolios** as a list/detail management page. Show portfolios in a table or list with status and summary information. Provide create and edit through focused dialogs. Permit hard deletion only for empty portfolios; otherwise require archival.

19. Build **Settings** as grouped settings sections rather than one long form. Include the application version, FinMind token save/test, security-master sync status, legacy import/reconciliation, database backup, appearance options, and projection assumptions. Use `QFileDialog`, `QMessageBox`, progress dialogs/bars, and native Qt controls. Do not add language preferences or localization infrastructure.

20. Handle modal workflows with focused `QDialog` classes. Keep dialogs small and task-specific rather than embedding every action into the main window. Use standard accept/cancel semantics and validate before accepting.

21. Use Qt actions and shortcuts where useful. Examples: refresh prices, new transaction, edit selected record, focus search, and close dialogs. Keep destructive actions visually and behaviorally distinct.

## Phase 5: Performance, Validation, and Handoff

22. Keep startup fast by avoiding network access, keyring reads, provider initialization, and eager chart imports before the window appears. Create the application, initialize the local database, build only the shell and initial view, show the window, and defer heavier work until needed.

23. Add focused pytest coverage for schema constraints, portfolio isolation, exact-symbol transaction entry, quote caching/fallback, provider error normalization/token redaction, audit edits/deletes/restores, legacy import idempotency, opening-position reconciliation, moving-average buys/sells/closed positions, combined-dashboard isolation, and IRR/profit/projection edge cases. Include a reinvested-dividend test proving that shares, basis, and dividend income increase while external cash flow remains zero and XIRR receives no artificial contribution/distribution.

24. Add Qt UI smoke tests for main-window construction, navigation switching, selected-page state, table models, dialog validation, deferred chart creation, and responsive background refresh. Where practical, use `pytest-qt` for signal, widget, and interaction tests.

25. Verify layouts at approximately 980x680 and 1240x800, plus Windows display scaling such as 125% and 150%. Confirm labels, forms, tables, dialogs, and English strings remain readable without clipping.

26. Update `README.md` in English with setup/run instructions, FinMind token setup and attribution/disclaimer, database location/backup, transaction sign conventions, reinvested-dividend behavior, migration limitations, and current screenshots. Retire the Streamlit UI only after the desktop workflow is feature-complete and documented.

## Suggested UI Structure

```text
QMainWindow
├── Sidebar
│   ├── Dashboard
│   ├── Transactions
│   ├── History
│   ├── Portfolios
│   └── Settings
│
└── Main Area
    ├── Page Header
    │   ├── Page title
    │   ├── Portfolio context
    │   └── Page actions
    │
    └── QStackedWidget
        ├── DashboardView
        ├── TransactionsView
        ├── HistoryView
        ├── PortfoliosView
        └── SettingsImportView
```

## Relevant Files

- `main.py`: PyQt6 application launcher and `QApplication` bootstrap.
- `pyproject.toml`: runtime/test dependencies and entry point.
- `README.md`: workflow, migration, provider, accounting, and run documentation.
- `irr_calculator/models.py`: normalized SQLAlchemy entities and constraints.
- `irr_calculator/database.py`: app-data path, engine/session, and schema versioning.
- `irr_calculator/migrations.py`: legacy import and opening-position reconciliation.
- `irr_calculator/services/transactions.py`: signed transactions, reinvested-dividend handling, audit CRUD, and ledger replay.
- `irr_calculator/services/analytics.py`: holdings, moving-average basis, profit, XIRR, and projections.
- `irr_calculator/providers/finmind.py`: security master and daily quote adapter.
- `irr_calculator/ui/main_window.py`: `QMainWindow`, sidebar, page header, and `QStackedWidget`.
- `irr_calculator/ui/theme.py`: shared design tokens and QSS generation/loading.
- `irr_calculator/ui/models/*`: Qt table/list models and proxy models.
- `irr_calculator/ui/views/*`: Dashboard, Projection, Transactions, History, Portfolios, and Settings.
- `irr_calculator/ui/dialogs/*`: transaction, portfolio, audit, import, and confirmation dialogs.
- `irr_calculator/ui/workers.py`: background workers and signal/result types.
- `tests/*`: service, migration, provider-fixture, regression, and Qt smoke tests.

## Verification

1. Run `uv sync --dev`, Pylance workspace diagnostics, and `uv run pytest` after each domain/UI phase. Use fixture HTTP responses so tests do not consume API quota.

2. Verify the reinvestment case: invest $100, receive/reinvest a $10 dividend into new shares with $0 external flow, refresh price to a $120 position, and confirm total profit is $20 while IRR includes only the original investment and terminal $120 value.

3. Import a legacy fixture twice and confirm one imported portfolio, no duplicate rows, identical legacy cash totals, reconciled holdings, and matching original XIRR when the same terminal value is supplied.

4. Manually exercise every navigation page: create/rename/archive/delete-empty portfolios; enter exact security symbols; add regular and reinvested transactions; edit/delete/restore with audit history; refresh partial-failure quotes; and compare portfolio versus all-portfolios totals.

5. Verify all interface text is English, no language selector or paired translated labels exist, text remains readable at supported DPI scaling, and primary navigation remains on the left.

6. Verify table sorting/filtering, keyboard focus, default buttons, Escape-to-close behavior, disabled states, confirmation dialogs, and background-task progress/error handling follow normal Qt desktop conventions.

7. Benchmark cold and warm window-ready time on the same machine. Confirm no startup network request and that the UI remains responsive throughout multi-symbol refresh.

## Scope Boundaries

- First release supports Taiwan securities only and uses TWD.
- Interface and documentation are English-only. Chinese security names remain provider data.
- Primary navigation is a persistent left sidebar.
- FinMind is the default provider for the Taiwan security master and delayed daily prices.
- Price refresh is user-triggered and daily-cached, not realtime or scheduled.
- Standard entry uses signed shares plus signed cash.
- Reinvested dividends use a specialized compound entry because external cash flow and acquisition cost are different concepts.
- Portfolio XIRR measures owner-level external cash flows; fully reinvested dividends are internal and therefore zero-cash for XIRR.
- Moving average is the cost-basis method.
- Corrections use edit/delete/restore with an audit trail.
- Version one includes portfolio-specific and combined dashboards, legacy import/reconciliation, cost basis, and realized profit.
- Included: local single-user desktop app, named portfolios, exact-symbol Taiwan security entry, delayed daily price refresh, quote cache, signed-share transaction CRUD, reinvested cash dividends, moving-average basis, audit history, portfolio/all-portfolio analytics, legacy migration, English-only PyQt6 UI, tests, and documentation.
- Excluded: brokerage sync, automatic refresh, realtime prices, multi-currency, persistent portfolio cash account, FIFO/LIFO, tax reporting, automatic corporate actions/stock dividends/splits, cloud sync, and multi-user access.
