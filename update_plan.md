# Personal Finance Feature Plan

## Objective

Extend Financial Hub to track one spending total and one income total per month, plus yearly asset snapshots. Keep data entry simple and use the existing local PyQt6 interface, SQLite storage, TWD conventions, and charting tools.

Reference workbook: `C:\Users\hank8\OneDrive - NTHU\Others\Finance\Personal Finance.xlsx`.

This document records the proposed feature design and the development database policy discussed. It does not authorize resetting or replacing an existing database.

## First-release scope

Add a **Personal Finance** navigation page with two tabs.

### Monthly Cash Flow

- Provide a year selector and a 12-row editable table.
- Fields: month, income, spending, calculated surplus, and optional notes.
- Enter income and spending as positive amounts; calculate surplus as income minus spending.
- Preserve the difference between missing entries and explicitly entered zeroes.
- Show year-to-date income, spending, surplus, average monthly spending, and savings rate, with reporting coverage clearly indicated.
- Calculate savings rate from aggregate surplus divided by aggregate income for matching completed periods; show it as unavailable when income is zero or required data is missing.
- Add an income-versus-spending chart.
- Do not require individual transactions or spending categories.

### Yearly Assets

- Store one snapshot per year with an explicit valuation date and optional notes.
- Enter cash and other funds, stocks/investments, emergency funds/time deposits, and debt manually.
- Calculate total assets as cash and other funds plus investments plus emergency funds. Keep these categories mutually exclusive to avoid double-counting.
- Calculate net worth as total assets minus debt.
- Show annual asset and net-worth trends and year-over-year changes when comparable records exist.
- Derive annual income and spending from monthly records, clearly marking incomplete years.
- Keep saved snapshots fixed when investment prices refresh.

### Excel Import

- Provide a preview before committing imported records.
- Map the workbook's monthly cash-flow records and annual balance-sheet categories into the new feature.
- Flag duplicate months and years and allow explicit conflict resolution before saving.
- Normalize the workbook's negative spending amounts to the app's positive spending convention.
- Resolve the workbook's **Earning of Previous Month** convention during import: preserve its budget-month assignment or assign income to the actual earning month. Do not silently shift periods.
- Preserve historical annual income/spending totals where monthly coverage is incomplete, with source and coverage identified. Keep these reference totals separate from monthly-derived totals so they are never added together.
- Leave the source workbook unchanged.

## Integration and Data Design

- Add separate monthly-record and annual-snapshot models to the existing database.
- Enforce one monthly record per year/month and one annual snapshot per year.
- Use the existing application structure for models, services, views, and data-change notifications.
- Keep salary and personal spending separate from investment transactions and owner cash flows used for XIRR.
- Include the new records in the existing whole-database backup workflow.
- Store monetary amounts consistently with the app's whole-TWD input conventions.

## Database Policy During Active Development

Avoid accumulating migration functions for intermediate development schemas. Maintain one canonical current schema.

- Update the canonical schema directly when adding this feature.
- Increment the schema version whenever the database structure changes, including column changes.
- Continue rejecting incompatible databases, but replace the current “Create a new database” error with actionable development rebuild guidance.
- Rebuild disposable development databases from a known seed or import source when their schema becomes incompatible.
- Make replacement of an existing database an explicit action; do not silently reset it during startup.
- Before any authorized replacement of a database containing real records, create a backup and determine how those records will be retained.
- If real records need transferring, use a one-time transfer script rather than maintaining a permanent chain of application migrations. A backup alone is not a transfer to the new schema.
- After the schema stabilizes, establish a supported release baseline and introduce migrations only for released versions that need continued support.

The current initializer in `financial_hub/database.py` rejects mismatched schema versions or table-name sets. It does not validate individual column definitions. Version bumps must therefore accompany structural changes; the table-name check alone is insufficient.

## Later Enhancements

- Optional monthly investment contributions, emergency-fund transfers, and remaining-budget columns matching the workbook. Treat transfers separately from spending.
- A **Fill investments from portfolios** action for a selected snapshot valuation date, with explicit handling of unavailable historical prices.
- Portfolio prefilling replaces the snapshot investment field rather than adding a second investment total. The saved value remains fixed until explicitly edited or refilled.

## Implementation Sequence

1. Finalize the monthly and annual record definitions and import period mapping.
2. Update the canonical models, schema version, and incompatible-database guidance without adding a migration chain.
3. Build monthly entry and yearly snapshot views with validation and summaries.
4. Add charts using the existing charting tools.
5. Add previewed Excel import and duplicate handling.
6. Verify persistence, calculations, blank-versus-zero behavior, incomplete years, duplicate protection, import signs/periods, and snapshot stability after price refreshes.
7. Run relevant existing checks to confirm investment tracking and XIRR remain unaffected, and document the development database rebuild workflow.

No database reset, transfer, or feature implementation has been performed as part of this planning task.
