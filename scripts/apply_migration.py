"""Apply the reviewed incremental database migration with safety preconditions."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys

import pymysql


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_database import load_env


def statements(sql: str) -> list[str]:
    without_comments = re.sub(r"(?m)^\s*--.*$", "", sql)
    return [item.strip() for item in without_comments.split(";") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument(
        "--migration",
        type=Path,
        default=ROOT / "database" / "migrations" / "2026.07.31.1__runtime_contract_upgrade.sql",
    )
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        raise SystemExit("Refusing database mutation without --confirm")
    load_env(args.env_file)
    connection = pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        connect_timeout=int(os.environ.get("MYSQL_CONNECT_TIMEOUT", "10")),
        read_timeout=int(os.environ.get("MYSQL_READ_TIMEOUT", "30")),
    )
    migration_name = args.migration.name
    metadata_only = migration_name.startswith(("2026.07.31.2a", "2026.07.31.3"))
    guarded_views = (
        []
        if metadata_only
        else ["vw_qa_work_order_fact"]
        if migration_name.startswith("2026.07.31.1")
        else ["vw_qa_defect_equipment_lookup", "vw_qa_workorder_equipment_lookup"]
        if migration_name.startswith("2026.07.31.2")
        else []
    )
    if not guarded_views and not metadata_only:
        raise SystemExit(f"Migration is not allowlisted for automatic application: {migration_name}")
    try:
        with connection.cursor() as cursor:
            for view in guarded_views:
                cursor.execute(
                    "SELECT COUNT(*) AS count FROM information_schema.VIEWS "
                    "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
                    (os.environ["MYSQL_DATABASE"], view),
                )
                if int(cursor.fetchone()["count"]):
                    raise SystemExit(f"Refusing to replace existing {view}; inspect and migrate manually")
            for statement in statements(args.migration.read_text(encoding="utf-8")):
                cursor.execute(statement)
    finally:
        connection.close()
    print(f"Applied migration: {args.migration.name}")


if __name__ == "__main__":
    main()
