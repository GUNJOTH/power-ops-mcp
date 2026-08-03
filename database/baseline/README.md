# New-database baseline

For a new database, first deploy the established shared view baseline from the governed data repository, then apply every file in `../migrations/` in version order.

The production database inspected on 2026-07-31 already contains compatible definitions of:

- `vw_qa_defect_fact`
- `vw_qa_defect`
- `vw_qa_work_order`

Their definitions are intentionally not replaced by the incremental MCP migration because they expose additional fields used by other workflows. A future baseline import must preserve that compatibility surface and pass `generated/database_contract.json`.
