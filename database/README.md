# Database contract

The MCP service does not query imported raw tables directly. Database changes are deployed separately from the read-only runtime account.

Deployment order:

1. Confirm raw imports have completed and take a backup or recoverable snapshot.
2. For the inspected existing database, execute `2026.07.31.1` and `2026.07.31.2` in order. Build and validate `mcp_defect_current`, then execute `2026.07.31.3` to publish the snapshot-backed contract.
3. Run `checks/smoke_and_quality.sql` and retain the output, including `EXPLAIN` plans.
4. Review `indexes/recommended_indexes.sql` with the DBA. The `sr` table is large; indexes require a maintenance window.
5. If account separation is introduced later, grant the MCP runtime only `SELECT` on the objects listed in `generated/database_contract.json`, plus `mcp_schema_version` and `mcp_defect_refresh_history`.
6. Start MCP. Readiness fails closed when the schema version, views, or required columns do not match.

Never run the index file automatically from application startup or CI.

## Large defect aggregates

The source `sr` table is roughly 40 million rows. The unique defect count can use
the existing defect-code index, but status and equipment aggregates exceed the
runtime query budget. Do not solve this by silently increasing the MCP timeout.
The governed one-row-per-defect snapshot is `mcp_defect_current`; its refresh and
rollback lifecycle is documented in `materialization/README.md`. Keep the active
table untouched until a build has completed all quality checks and is atomically
published.
