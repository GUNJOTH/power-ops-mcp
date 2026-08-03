"""Bounded MySQL connection pool, query concurrency and readiness checks."""

from __future__ import annotations

import logging
import queue
import threading
from contextlib import contextmanager
from typing import Any, Iterator

import pymysql

from .config import Settings


LOGGER = logging.getLogger("power-ops-mcp.database")


class QueryBusyError(RuntimeError):
    """Raised when the bounded database execution capacity is exhausted."""


class ConnectionPool:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._available: queue.LifoQueue[pymysql.connections.Connection] = queue.LifoQueue(
            maxsize=settings.mysql_pool_size
        )
        self._lock = threading.Lock()
        self._created = 0
        self._query_slots = threading.BoundedSemaphore(settings.max_concurrent_queries)

    def _new_connection(self) -> pymysql.connections.Connection:
        connection = pymysql.connect(
            host=self.settings.mysql_host,
            port=self.settings.mysql_port,
            user=self.settings.mysql_user,
            password=self.settings.mysql_password,
            database=self.settings.mysql_database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            read_timeout=self.settings.mysql_read_timeout,
            connect_timeout=self.settings.mysql_connect_timeout,
            init_command="SET SESSION TRANSACTION READ ONLY",
        )
        with connection.cursor() as cursor:
            cursor.execute(
                f"SET SESSION MAX_EXECUTION_TIME = {self.settings.mysql_statement_timeout_ms}"
            )
        return connection

    def _acquire_connection(self) -> pymysql.connections.Connection:
        try:
            connection = self._available.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created < self.settings.mysql_pool_size:
                    self._created += 1
                    create = True
                else:
                    create = False
            if create:
                try:
                    return self._new_connection()
                except Exception:
                    with self._lock:
                        self._created -= 1
                    raise
            try:
                connection = self._available.get(timeout=self.settings.mysql_pool_wait_seconds)
            except queue.Empty as exc:
                raise QueryBusyError("数据库连接池繁忙，请稍后重试") from exc
        try:
            connection.ping(reconnect=True)
        except Exception:
            self._discard(connection)
            return self._acquire_connection()
        return connection

    def _discard(self, connection: pymysql.connections.Connection) -> None:
        try:
            connection.close()
        finally:
            with self._lock:
                self._created = max(0, self._created - 1)

    @contextmanager
    def connection(self) -> Iterator[pymysql.connections.Connection]:
        connection = self._acquire_connection()
        try:
            yield connection
        except Exception:
            self._discard(connection)
            raise
        else:
            try:
                self._available.put_nowait(connection)
            except queue.Full:
                self._discard(connection)

    @contextmanager
    def query_slot(self) -> Iterator[None]:
        acquired = self._query_slots.acquire(timeout=self.settings.mysql_pool_wait_seconds)
        if not acquired:
            raise QueryBusyError("查询并发已达到上限，请稍后重试")
        try:
            yield
        finally:
            self._query_slots.release()

    def ping(self) -> None:
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS ok")
            cursor.fetchone()

    def validate_views(self, contracts: dict[str, set[str]]) -> dict[str, list[str]]:
        missing: dict[str, list[str]] = {}
        sql = """
        SELECT TABLE_NAME, COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({})
        """.format(",".join(["%s"] * len(contracts)))
        params: list[Any] = [self.settings.mysql_database, *contracts]
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        actual: dict[str, set[str]] = {}
        for row in rows:
            actual.setdefault(row["TABLE_NAME"], set()).add(row["COLUMN_NAME"])
        for view, expected in contracts.items():
            absent = sorted(expected - actual.get(view, set()))
            if absent:
                missing[view] = absent
        return missing

    def schema_version(self) -> str:
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT version FROM mcp_schema_version "
                "WHERE component = %s LIMIT 1",
                ("power_ops_views",),
            )
            row = cursor.fetchone()
        return str(row["version"]) if row else ""

    def snapshot_status(self) -> dict[str, Any]:
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT run_id,status,source_count,snapshot_count,finished_at,elapsed_seconds "
                "FROM mcp_defect_refresh_history WHERE status='published' "
                "ORDER BY finished_at DESC LIMIT 1"
            )
            row = cursor.fetchone() or {}
        if row.get("finished_at") is not None:
            row["finished_at"] = row["finished_at"].isoformat(sep=" ")
        if row.get("elapsed_seconds") is not None:
            row["elapsed_seconds"] = float(row["elapsed_seconds"])
        return row

    def close(self) -> None:
        while True:
            try:
                self._discard(self._available.get_nowait())
            except queue.Empty:
                return
