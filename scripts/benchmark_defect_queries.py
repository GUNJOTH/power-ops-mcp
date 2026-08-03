"""Run bounded, read-only benchmarks for the defect aggregate paths."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

import pymysql

from check_database import load_env


ROOT = Path(__file__).resolve().parents[1]

QUERIES = {
    "total_distinct": """
        SELECT COUNT(DISTINCT defect_code) AS value
        FROM mcp_defect_current
        WHERE defect_code IS NOT NULL
    """,
    "open_distinct": """
        SELECT COUNT(DISTINCT defect_code) AS value
        FROM mcp_defect_current
        WHERE defect_code IS NOT NULL
          AND COALESCE(defect_status, '') NOT IN ('已关闭', '已取消', '已作废')
    """,
    "equipment_distinct": """
        SELECT COUNT(DISTINCT NULLIF(kks_code, '')) AS value
        FROM mcp_defect_current
    """,
    "status_distribution": """
        SELECT COALESCE(defect_status, '未标注状态') AS dimension_value,
               COUNT(DISTINCT defect_code) AS value
        FROM mcp_defect_current
        GROUP BY COALESCE(defect_status, '未标注状态')
    """,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--max-execution-ms", type=int, default=25_000)
    args = parser.parse_args()
    load_env(args.env_file)

    connection = pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=max(30, args.max_execution_ms // 1000 + 5),
    )
    results: list[dict[str, object]] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION MAX_EXECUTION_TIME = %s", (args.max_execution_ms,))
            for name, sql in QUERIES.items():
                started = time.perf_counter()
                try:
                    cursor.execute(sql)
                    rows = cursor.fetchall()
                    results.append(
                        {
                            "query": name,
                            "status": "ok",
                            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                            "row_count": len(rows),
                            "value": rows[0].get("value") if len(rows) == 1 else None,
                        }
                    )
                except pymysql.MySQLError as exc:
                    results.append(
                        {
                            "query": name,
                            "status": "timeout" if exc.args and exc.args[0] == 3024 else "error",
                            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                            "mysql_error_code": exc.args[0] if exc.args else None,
                        }
                    )
    finally:
        connection.close()
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
