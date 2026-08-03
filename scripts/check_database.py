"""Read-only database connectivity, contract and index inspection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_env(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    load_env(args.env_file)

    from generated.semantic_registry import (
        DATABASE_SCHEMA_VERSION, DATASETS, EQUIPMENT_SOURCES, FAST_SOURCES,
    )
    from runtime.config import get_settings
    from runtime.database import ConnectionPool

    get_settings.cache_clear()
    settings = get_settings()
    pool = ConnectionPool(settings)
    contracts = {
        DATASETS["defect"]["source"]: set(DATASETS["defect"]["fields"]),
        FAST_SOURCES["defect"]: set(DATASETS["defect"]["fields"]),
        DATASETS["workorder"]["source"]: set(DATASETS["workorder"]["fields"]),
        FAST_SOURCES["workorder"]: set(DATASETS["workorder"]["fields"]),
        EQUIPMENT_SOURCES["defect"]: {
            "asset_code", "equipment_name", "kks_code", "location_name", "specialty_name",
        },
        EQUIPMENT_SOURCES["workorder"]: {
            "asset_code", "equipment_name", "kks_code", "kks_name", "specialty_name",
        },
    }
    report: dict[str, object] = {
        "database": settings.mysql_database,
        "expected_schema_version": DATABASE_SCHEMA_VERSION,
    }
    try:
        with pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT VERSION() AS version, CURRENT_USER() AS authenticated_user")
            report["server"] = cursor.fetchone()
            cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
            report["grants"] = [next(iter(row.values())) for row in cursor.fetchall()]
            object_names = [*contracts, "mcp_schema_version"]
            placeholders = ",".join(["%s"] * len(object_names))
            cursor.execute(
                "SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES "
                f"WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN ({placeholders}) ORDER BY TABLE_NAME",
                (settings.mysql_database, *object_names),
            )
            report["objects"] = cursor.fetchall()
            cursor.execute(
                "SELECT TABLE_NAME, INDEX_NAME, MAX(CARDINALITY) AS cardinality, "
                "GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS columns "
                "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s "
                "AND TABLE_NAME IN ('sr','workorder','mcp_defect_current') "
                "GROUP BY TABLE_NAME, INDEX_NAME "
                "ORDER BY TABLE_NAME, INDEX_NAME",
                (settings.mysql_database,),
            )
            report["indexes"] = cursor.fetchall()
            view_fingerprints: dict[str, str] = {}
            for view in contracts:
                try:
                    cursor.execute(
                        "SELECT TABLE_TYPE FROM information_schema.TABLES "
                        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
                        (settings.mysql_database, view),
                    )
                    object_row = cursor.fetchone()
                    object_type = object_row["TABLE_TYPE"] if object_row else ""
                    cursor.execute(
                        f"SHOW CREATE {'VIEW' if object_type == 'VIEW' else 'TABLE'} `{view}`"
                    )
                    row = cursor.fetchone()
                    definition = str(row.get("Create View") or row.get("Create Table") or "")
                    view_fingerprints[view] = hashlib.sha256(definition.encode("utf-8")).hexdigest()
                except Exception:
                    view_fingerprints[view] = "missing"
            report["view_definition_fingerprints"] = view_fingerprints
        report["missing_columns"] = pool.validate_views(contracts)
        try:
            report["actual_schema_version"] = pool.schema_version()
        except Exception as exc:
            report["actual_schema_version"] = ""
            report["schema_version_error"] = type(exc).__name__
    finally:
        pool.close()
    report["contract_ready"] = (
        report.get("actual_schema_version") == DATABASE_SCHEMA_VERSION
        and not report.get("missing_columns")
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
