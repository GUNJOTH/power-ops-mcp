# Defect serving model

## Decision

Use one governed current-state snapshot with one row per `defect_code` before
adding dashboard aggregate tables. The inspected `sr` source has about 37.8
million rows and no trustworthy update timestamp or monotonically increasing
ingestion key. Therefore a correct incremental refresh cannot be derived from
the current source schema.

Refresh the snapshot after each successful upstream full import:

1. Acquire a database advisory lock so only one refresh runs.
2. Build a new physical table from `vw_qa_defect` without touching the active table.
3. Add the primary key and indexes to the build table.
4. Validate non-null keys, uniqueness, row-count bounds and semantic samples.
5. Atomically rename the active and build tables.
6. Retain the previous table for rollback until acceptance, then remove it in a
   separate approved cleanup operation.

Recommended indexes on the snapshot are `defect_code` (primary key),
`defect_status`, `kks_code`, `asset_code`, `defect_type_name`, `specialty_name`,
`maintenance_team_name`, `unit_name`, and `defect_classification`. At the current
approximately 455,000-row grain, overview counts and grouped queries should run
inside the MCP budget without separate aggregate tables.

Only add a small aggregate table later if measured p95 latency on the snapshot
still misses the target. Such a table must be rebuilt from the same snapshot in
the same refresh run and carry the same `refresh_id`; never aggregate directly
from `sr`, because that would create competing business definitions.

## Source limitation and next schema improvement

For future imports, add an ingestion batch identifier and source update timestamp
outside the raw business columns. Once those are reliable, refresh can process
changed defect codes and periodically run a full reconciliation. Until then,
full rebuild plus atomic swap is the safe method.

## Operations

Run from the repository root with the workspace-managed uv environment:

```powershell
$env:UV_CACHE_DIR='.\.uv-cache'
D:\uv\bin\uv.exe run python scripts\refresh_defect_snapshot.py --status
D:\uv\bin\uv.exe run python scripts\refresh_defect_snapshot.py --confirm
```

The first refresh creates `mcp_defect_current`. Later refreshes atomically move
the old table to `mcp_defect_current_previous`. Keep that table through business
acceptance. Before the following refresh, remove the accepted rollback copy with
the explicit maintenance command:

```powershell
D:\uv\bin\uv.exe run python scripts\refresh_defect_snapshot.py --confirm --cleanup-previous
```

If a client is interrupted before publication, inspect `--status`. Only after
confirming that no refresh lock is held may the next run use
`--discard-stale-build`. Never schedule that recovery flag as a routine job.
