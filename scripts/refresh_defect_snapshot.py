"""Build and atomically publish the governed one-row-per-defect snapshot."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import uuid

import pymysql

from check_database import load_env


ROOT = Path(__file__).resolve().parents[1]
LOCK_NAME = "power_ops_mcp_defect_snapshot_refresh"
BUILD_TABLE = "mcp_defect_current_build"
CURRENT_TABLE = "mcp_defect_current"
PREVIOUS_TABLE = "mcp_defect_current_previous"

CREATE_BUILD_SQL = f"""
CREATE TABLE `{BUILD_TABLE}` (
  `TICKETID` INT NOT NULL,
  `DESCRIPTION` VARCHAR(2000) NULL,
  `S_QXLB` VARCHAR(50) NULL,
  `S_CLASSIFICATION` VARCHAR(50) NULL,
  `specialty_name` VARCHAR(30) NULL,
  `status` VARCHAR(100) NULL,
  `LOCATION` VARCHAR(300) NULL,
  `location_name` VARCHAR(600) NULL,
  `assetnum` VARCHAR(30) NULL,
  `equipment_name` VARCHAR(600) NULL,
  `C_JZH` VARCHAR(50) NULL,
  `TEAMNAME` VARCHAR(100) NULL,
  `S_FINISHREPORT` VARCHAR(1500) NULL,
  `S_YXYS` VARCHAR(500) NULL,
  `S_GZZJ` VARCHAR(1000) NULL,
  PRIMARY KEY (`TICKETID`),
  KEY `idx_mcp_defect_status` (`status`),
  KEY `idx_mcp_defect_kks` (`LOCATION`),
  KEY `idx_mcp_defect_asset` (`assetnum`),
  KEY `idx_mcp_defect_type` (`S_QXLB`),
  KEY `idx_mcp_defect_specialty` (`specialty_name`),
  KEY `idx_mcp_defect_team` (`TEAMNAME`),
  KEY `idx_mcp_defect_unit` (`C_JZH`),
  KEY `idx_mcp_defect_classification` (`S_CLASSIFICATION`),
  KEY `idx_mcp_defect_status_scope`
    (`status`, `specialty_name`, `TEAMNAME`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
"""

INSERT_SQL = f"""
INSERT INTO `{BUILD_TABLE}` (
  TICKETID, DESCRIPTION, S_QXLB, S_CLASSIFICATION,
  specialty_name, status, LOCATION, location_name, assetnum,
  equipment_name, C_JZH, TEAMNAME, S_FINISHREPORT,
  S_YXYS, S_GZZJ
)
SELECT
  defect_code AS TICKETID,
  defect_description AS DESCRIPTION,
  defect_type_name AS S_QXLB,
  defect_classification AS S_CLASSIFICATION,
  specialty_name,
  defect_status AS status,
  kks_code AS LOCATION,
  location_name,
  asset_code AS assetnum,
  equipment_name,
  unit_name AS C_JZH,
  maintenance_team_name AS TEAMNAME,
  treatment_result AS S_FINISHREPORT,
  acceptance_summary AS S_YXYS,
  work_summary AS S_GZZJ
FROM vw_qa_defect
"""


def object_exists(cursor: pymysql.cursors.Cursor, database: str, name: str) -> bool:
    cursor.execute(
        "SELECT COUNT(*) AS count FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
        (database, name),
    )
    return bool(cursor.fetchone()["count"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--discard-stale-build", action="store_true")
    parser.add_argument("--cleanup-previous", action="store_true")
    args = parser.parse_args()
    if not args.status and not args.confirm:
        raise SystemExit("Refusing snapshot mutation without --confirm")
    load_env(args.env_file)
    database = os.environ["MYSQL_DATABASE"]
    run_id = str(uuid.uuid4())
    started = time.perf_counter()
    connection = pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        connect_timeout=10,
        read_timeout=7200,
        write_timeout=7200,
    )
    locked = False
    try:
        with connection.cursor() as cursor:
            if args.status:
                cursor.execute("SELECT IS_USED_LOCK(%s) AS owner_connection_id", (LOCK_NAME,))
                lock = cursor.fetchone()
                process = None
                if lock["owner_connection_id"] is not None:
                    cursor.execute(
                        "SELECT ID,USER,HOST,DB,COMMAND,TIME,STATE,LEFT(INFO,200) AS INFO "
                        "FROM information_schema.PROCESSLIST WHERE ID=%s",
                        (lock["owner_connection_id"],),
                    )
                    process = cursor.fetchone()
                objects: dict[str, bool] = {}
                for name in (BUILD_TABLE, CURRENT_TABLE, PREVIOUS_TABLE):
                    objects[name] = object_exists(cursor, database, name)
                cursor.execute(
                    "SELECT TABLE_NAME,TABLE_ROWS,DATA_LENGTH,INDEX_LENGTH "
                    "FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s "
                    "AND TABLE_NAME IN (%s,%s,%s)",
                    (database, BUILD_TABLE, CURRENT_TABLE, PREVIOUS_TABLE),
                )
                storage = cursor.fetchall()
                history: list[dict[str, object]] = []
                if object_exists(cursor, database, "mcp_defect_refresh_history"):
                    cursor.execute(
                        "SELECT run_id,status,source_count,snapshot_count,started_at,"
                        "finished_at,elapsed_seconds,error_type "
                        "FROM mcp_defect_refresh_history ORDER BY started_at DESC LIMIT 5"
                    )
                    history = cursor.fetchall()
                print(json.dumps({"lock": lock, "process": process, "objects": objects, "storage": storage, "history": history}, ensure_ascii=False, default=str, indent=2))
                return
            cursor.execute("SELECT GET_LOCK(%s, 0) AS acquired", (LOCK_NAME,))
            locked = cursor.fetchone()["acquired"] == 1
            if not locked:
                raise SystemExit("Another defect snapshot refresh holds the database lock")
            cursor.execute("SET SESSION MAX_EXECUTION_TIME = 0")
            if args.cleanup_previous:
                if not object_exists(cursor, database, PREVIOUS_TABLE):
                    raise SystemExit(f"No {PREVIOUS_TABLE} table exists")
                cursor.execute(f"DROP TABLE `{PREVIOUS_TABLE}`")
                print(json.dumps({"status": "removed", "table": PREVIOUS_TABLE}), flush=True)
                return
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS mcp_defect_refresh_history ("
                "run_id CHAR(36) NOT NULL PRIMARY KEY, status VARCHAR(20) NOT NULL, "
                "source_count BIGINT NULL, snapshot_count BIGINT NULL, "
                "started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "finished_at TIMESTAMP NULL, elapsed_seconds DECIMAL(12,3) NULL, "
                "error_type VARCHAR(100) NULL"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
            )
            if args.discard_stale_build and object_exists(cursor, database, BUILD_TABLE):
                cursor.execute(f"DROP TABLE `{BUILD_TABLE}`")
                cursor.execute(
                    "UPDATE mcp_defect_refresh_history SET status='interrupted',"
                    "finished_at=CURRENT_TIMESTAMP,error_type='ClientInterrupted' "
                    "WHERE status='building'"
                )
            cursor.execute(
                "INSERT INTO mcp_defect_refresh_history (run_id,status) VALUES (%s,'building')",
                (run_id,),
            )
            if object_exists(cursor, database, BUILD_TABLE):
                raise RuntimeError(
                    f"Stale {BUILD_TABLE} exists; inspect it before a manual cleanup"
                )
            if object_exists(cursor, database, PREVIOUS_TABLE):
                raise RuntimeError(
                    f"Rollback table {PREVIOUS_TABLE} exists; retain or clean it before refresh"
                )
            print(json.dumps({"run_id": run_id, "stage": "create_build_table"}), flush=True)
            cursor.execute(CREATE_BUILD_SQL)
            print(json.dumps({"run_id": run_id, "stage": "populate_from_vw_qa_defect"}), flush=True)
            cursor.execute(INSERT_SQL)
            snapshot_count = cursor.rowcount
            print(
                json.dumps(
                    {"run_id": run_id, "stage": "validate", "inserted_rows": snapshot_count}
                ),
                flush=True,
            )
            cursor.execute(
                "SELECT COUNT(DISTINCT defect_code) AS source_count "
                "FROM vw_qa_defect_fact WHERE defect_code IS NOT NULL"
            )
            source_count = int(cursor.fetchone()["source_count"])
            cursor.execute(
                f"SELECT COUNT(*) AS row_count, COUNT(DISTINCT TICKETID) AS unique_count, "
                f"SUM(TICKETID IS NULL) AS null_keys FROM `{BUILD_TABLE}`"
            )
            quality = cursor.fetchone()
            if not (
                int(quality["row_count"]) == source_count
                and int(quality["unique_count"]) == source_count
                and int(quality["null_keys"] or 0) == 0
            ):
                raise RuntimeError(
                    f"Snapshot quality mismatch source={source_count} quality={quality}"
                )
            cursor.execute(f"ANALYZE TABLE `{BUILD_TABLE}`")
            print(json.dumps({"run_id": run_id, "stage": "atomic_publish"}), flush=True)
            if object_exists(cursor, database, CURRENT_TABLE):
                cursor.execute(
                    f"RENAME TABLE `{CURRENT_TABLE}` TO `{PREVIOUS_TABLE}`, "
                    f"`{BUILD_TABLE}` TO `{CURRENT_TABLE}`"
                )
            else:
                cursor.execute(f"RENAME TABLE `{BUILD_TABLE}` TO `{CURRENT_TABLE}`")
            elapsed = round(time.perf_counter() - started, 3)
            cursor.execute(
                "UPDATE mcp_defect_refresh_history SET status='published', "
                "source_count=%s,snapshot_count=%s,finished_at=CURRENT_TIMESTAMP,"
                "elapsed_seconds=%s WHERE run_id=%s",
                (source_count, snapshot_count, elapsed, run_id),
            )
            print(
                json.dumps(
                    {
                        "run_id": run_id,
                        "status": "published",
                        "source_count": source_count,
                        "snapshot_count": snapshot_count,
                        "elapsed_seconds": elapsed,
                    }
                ),
                flush=True,
            )
    except Exception as exc:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE mcp_defect_refresh_history SET status='failed',"
                    "finished_at=CURRENT_TIMESTAMP,elapsed_seconds=%s,error_type=%s "
                    "WHERE run_id=%s",
                    (round(time.perf_counter() - started, 3), type(exc).__name__, run_id),
                )
        except Exception:
            pass
        raise
    finally:
        if locked:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK(%s)", (LOCK_NAME,))
            except Exception:
                pass
        connection.close()


if __name__ == "__main__":
    main()
