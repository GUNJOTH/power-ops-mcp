"""Small dependency-free Prometheus metrics registry."""

from __future__ import annotations

import threading
from collections import defaultdict


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count: dict[tuple[str, str], int] = defaultdict(int)
        self._duration: dict[tuple[str, str], float] = defaultdict(float)
        self._returned: dict[str, int] = defaultdict(int)

    def record(self, tool: str, status: str, duration_seconds: float, returned: int = 0) -> None:
        with self._lock:
            key = (tool, status)
            self._count[key] += 1
            self._duration[key] += duration_seconds
            self._returned[tool] += returned

    def render(self) -> str:
        with self._lock:
            count = dict(self._count)
            duration = dict(self._duration)
            returned = dict(self._returned)
        lines = [
            "# HELP power_ops_mcp_queries_total MCP database query executions.",
            "# TYPE power_ops_mcp_queries_total counter",
        ]
        for (tool, status), value in sorted(count.items()):
            lines.append(f'power_ops_mcp_queries_total{{tool="{tool}",status="{status}"}} {value}')
        lines.extend([
            "# HELP power_ops_mcp_query_duration_seconds_total Cumulative database query time.",
            "# TYPE power_ops_mcp_query_duration_seconds_total counter",
        ])
        for (tool, status), value in sorted(duration.items()):
            lines.append(
                f'power_ops_mcp_query_duration_seconds_total{{tool="{tool}",status="{status}"}} {value:.6f}'
            )
        lines.extend([
            "# HELP power_ops_mcp_rows_returned_total Rows read from MySQL.",
            "# TYPE power_ops_mcp_rows_returned_total counter",
        ])
        for tool, value in sorted(returned.items()):
            lines.append(f'power_ops_mcp_rows_returned_total{{tool="{tool}"}} {value}')
        return "\n".join(lines) + "\n"


METRICS = Metrics()
