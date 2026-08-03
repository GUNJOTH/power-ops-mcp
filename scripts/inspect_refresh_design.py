"""Inspect source metadata needed to design governed refresh tables."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pymysql

from check_database import load_env


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    load_env(ROOT / ".env")
    connection = pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=30,
    )
    report: dict[str, object] = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT TABLE_NAME,TABLE_ROWS,DATA_LENGTH,INDEX_LENGTH,UPDATE_TIME "
                "FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s "
                "AND TABLE_NAME IN ('sr','workorder')",
                (os.environ["MYSQL_DATABASE"],),
            )
            report["tables"] = cursor.fetchall()
            cursor.execute(
                "SELECT COLUMN_NAME,DATA_TYPE,COLUMN_TYPE,IS_NULLABLE,COLUMN_KEY "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s "
                "AND TABLE_NAME='sr' ORDER BY ORDINAL_POSITION",
                (os.environ["MYSQL_DATABASE"],),
            )
            report["sr_columns"] = cursor.fetchall()
            cursor.execute(
                "SELECT TABLE_NAME,SECURITY_TYPE,DEFINER,IS_UPDATABLE "
                "FROM information_schema.VIEWS WHERE TABLE_SCHEMA=%s "
                "AND TABLE_NAME LIKE 'vw_qa_%%' ORDER BY TABLE_NAME",
                (os.environ["MYSQL_DATABASE"],),
            )
            report["views"] = cursor.fetchall()
            cursor.execute(
                "SHOW VARIABLES WHERE Variable_name IN "
                "('require_secure_transport','have_ssl','event_scheduler')"
            )
            report["variables"] = cursor.fetchall()
            cursor.execute("SHOW FULL TABLES LIKE 'mcp_schema_version'")
            report["schema_version_object"] = cursor.fetchall()
            try:
                cursor.execute(
                    "SELECT component,version,applied_at FROM mcp_schema_version ORDER BY component"
                )
                report["schema_versions"] = cursor.fetchall()
            except pymysql.MySQLError as exc:
                report["schema_version_error"] = {"code": exc.args[0], "message": exc.args[1]}
            definitions: dict[str, str] = {}
            for view_name in ("vw_qa_defect", "vw_qa_defect_dedup", "vw_qa_defect_fact"):
                cursor.execute(f"SHOW CREATE VIEW `{view_name}`")
                row = cursor.fetchone()
                definitions[view_name] = row["Create View"]
            report["view_definitions"] = definitions
    finally:
        connection.close()
    print(json.dumps(report, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
