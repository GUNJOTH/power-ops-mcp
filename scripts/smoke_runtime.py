"""Run a bounded, read-only smoke test against the configured production database."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

import pymysql


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_database import load_env


def timed(name: str, function, *args, **kwargs) -> dict[str, object]:
    started = time.perf_counter()
    result = function(*args, **kwargs)
    data = result.get("data") if isinstance(result, dict) else None
    returned = len(data) if isinstance(data, list) else int(bool(data))
    return {
        "check": name,
        "code": result.get("code") if isinstance(result, dict) else None,
        "returned_count": returned,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    load_env(args.env_file)

    import app

    ready, readiness = app._readiness()
    report: dict[str, object] = {"ready": ready, "readiness": readiness, "checks": []}
    if not ready:
        raise SystemExit(json.dumps(report, ensure_ascii=False, indent=2))

    report["checks"].append(timed("service_status", app.get_service_status, True))
    report["checks"].append(
        timed("capabilities", app.get_maintenance_dashboard, domain="defect", view="capabilities", limit=2)
    )
    report["checks"].append(
        timed("defect_overview", app.get_maintenance_dashboard, domain="defect", view="overview")
    )
    report["checks"].append(
        timed("defect_status_summary", app.summarize_defects, group_by="status", limit=10)
    )

    connection = pymysql.connect(
        host=os.environ["MYSQL_HOST"], port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"], password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=10, read_timeout=30,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT `工单号` AS code FROM `workorder` "
                "WHERE NULLIF(TRIM(`工单号`), '') IS NOT NULL LIMIT 1"
            )
            row = cursor.fetchone()
            cursor.execute(
                "SELECT `缺陷编号` AS code FROM `sr` "
                "WHERE `缺陷编号` IS NOT NULL LIMIT 1"
            )
            defect_row = cursor.fetchone()
            cursor.execute(
                "SELECT `逻辑设备/KKS编码` AS code FROM `workorder` "
                "WHERE NULLIF(TRIM(`逻辑设备/KKS编码`), '') IS NOT NULL LIMIT 1"
            )
            kks_row = cursor.fetchone()
    finally:
        connection.close()
    if row:
        report["checks"].append(
            timed("workorder_detail", app.get_workorder_detail, str(row["code"]))
        )
    if defect_row:
        report["checks"].append(
            timed("defect_detail", app.get_defect_detail, str(defect_row["code"]))
        )
    if kks_row:
        report["checks"].append(
            timed("equipment_exact_kks", app.search_equipment, kks_code=str(kks_row["code"]), limit=2)
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
