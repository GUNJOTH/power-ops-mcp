"""火电运维问数 MCP 服务。

只暴露固定、参数化的只读查询，不接受 SQL、WHERE 或 ORDER BY 片段。
数据口径与 ``火电运维问数驾驶舱_生产版_sqldemo3.yml`` 使用的
``vw_qa_*`` 语义视图保持一致。
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

try:
    from .runtime.config import get_settings
    from .runtime.database import ConnectionPool
    from .runtime.security import StaticTokenVerifier
    from .runtime.metrics import METRICS as RUNTIME_METRICS
except ImportError:  # Direct execution: uv run python app.py
    from runtime.config import get_settings
    from runtime.database import ConnectionPool
    from runtime.security import StaticTokenVerifier
    from runtime.metrics import METRICS as RUNTIME_METRICS

try:
    from .generated.semantic_registry import (
        CLOSED_STATUSES,
        DATABASE_SCHEMA_VERSION,
        DATA_BOUNDARIES,
        DATASETS,
        DIMENSIONS,
        EQUIPMENT_SOURCES,
        FAST_SOURCES,
        METRICS,
        MODEL_AI_CONTEXT,
        SEMANTIC_FINGERPRINT,
        TOOL_CATALOG,
    )
except ImportError:  # Direct execution: uv run python app.py
    from generated.semantic_registry import (  # type: ignore[no-redef]
        CLOSED_STATUSES,
        DATABASE_SCHEMA_VERSION,
        DATA_BOUNDARIES,
        DATASETS,
        DIMENSIONS,
        EQUIPMENT_SOURCES,
        FAST_SOURCES,
        METRICS,
        MODEL_AI_CONTEXT,
        SEMANTIC_FINGERPRINT,
        TOOL_CATALOG,
    )


SETTINGS = get_settings()
logging.basicConfig(
    level=SETTINGS.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOGGER = logging.getLogger("power-defect-analysis-mcp")
MCP = FastMCP(
    "火电缺陷智能分析",
    json_response=True,
    host=SETTINGS.mcp_host,
    port=SETTINGS.mcp_port,
    max_request_body_size=SETTINGS.max_request_body_size,
    token_verifier=StaticTokenVerifier(SETTINGS.auth_token) if SETTINGS.auth_required else None,
    auth=(
        AuthSettings(
            issuer_url=SETTINGS.auth_issuer_url,
            resource_server_url=SETTINGS.public_url,
            required_scopes=["mcp:tools"],
        )
        if SETTINGS.auth_required else None
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(SETTINGS.allowed_hosts),
        allowed_origins=list(SETTINGS.allowed_origins),
    ),
)
POOL = ConnectionPool(SETTINGS)

MAX_LIMIT = 50
DEFECT_ANALYSIS_TABLE = "dwd_defect_dedup_physical"
ANALYSIS_PAGE_MAX = 500
ANALYSIS_FIELDS = (
    "defect_code, defect_description, defect_type_name, defect_classification, "
    "specialty_code, specialty_name, defect_type_desc, defect_status, kks_code, "
    "location_name, kks_name, asset_code, equipment_name, unit_name, "
    "maintenance_team_code, maintenance_team_name, acceptance_location, "
    "treatment_result, acceptance_summary, work_summary, equipment_kks, "
    "system_kks, system_class_code, equipment_class_code"
)
TOOL_CATALOG.update({
    "parse_kks_code": {
        "label": "KKS长短编码解析", "domains": ["defect"],
        "intents": ["kks_parse"],
    },
    "resolve_defect_equipment": {
        "label": "缺陷设备主数据匹配", "domains": ["defect"],
        "intents": ["equipment_search"],
    },
    "get_current_equipment_defects": {
        "label": "当前设备历史缺陷", "domains": ["defect"],
        "intents": ["current_equipment_defect_analysis"],
    },
    "get_same_system_defects": {
        "label": "同系统设备缺陷", "domains": ["defect"],
        "intents": ["same_system_defect_analysis"],
    },
    "get_same_type_defects": {
        "label": "同类型设备缺陷", "domains": ["defect"],
        "intents": ["same_type_defect_analysis"],
    },
    "get_defect_analysis_statistics": {
        "label": "缺陷分析三范围统计", "domains": ["defect"],
        "intents": ["defect_analysis_statistics"],
    },
})
DEFECT_VIEW = DATASETS["defect"]["source"]
DEFECT_FAST_VIEW = FAST_SOURCES["defect"]
WORKORDER_VIEW = DATASETS["workorder"]["source"]
WORKORDER_FAST_VIEW = FAST_SOURCES["workorder"]
DEFECT_EQUIPMENT_VIEW = EQUIPMENT_SOURCES["defect"]
WORKORDER_EQUIPMENT_VIEW = EQUIPMENT_SOURCES["workorder"]
DEFECT_COLUMNS = ", ".join(DATASETS["defect"]["fields"])
WORKORDER_COLUMNS = ", ".join(DATASETS["workorder"]["fields"])
RESPONSE_CONTRACT_VERSION = "1.0"
VIEW_CONTRACTS = {
    DEFECT_VIEW: set(DATASETS["defect"]["fields"]),
    DEFECT_FAST_VIEW: set(DATASETS["defect"]["fields"]),
    WORKORDER_VIEW: set(DATASETS["workorder"]["fields"]),
    WORKORDER_FAST_VIEW: set(DATASETS["workorder"]["fields"]),
    DEFECT_EQUIPMENT_VIEW: {
        "LOCATION", "location_name", "assetnum", "equipment_name", "specialty_name",
    },
    WORKORDER_EQUIPMENT_VIEW: {
        "LOCATION", "kks_name", "ASSETNUM", "equipment_name", "specialty_name",
    },
    DEFECT_ANALYSIS_TABLE: {
        "defect_code", "defect_description", "defect_type_name",
        "defect_classification", "specialty_code", "specialty_name",
        "defect_type_desc", "defect_status", "kks_code", "location_name",
        "kks_name", "asset_code", "equipment_name", "unit_name",
        "maintenance_team_code", "maintenance_team_name", "acceptance_location",
        "treatment_result", "acceptance_summary", "work_summary",
        "equipment_kks", "system_kks", "system_class_code", "equipment_class_code",
    },
}


def _metric(name: str) -> str:
    """Return a build-time validated ANSI SQL metric expression."""
    return str(METRICS[name]["expression"])


def _limit(value: int, default: int = 20) -> int:
    try:
        return max(1, min(int(value), MAX_LIMIT))
    except (TypeError, ValueError):
        return default


def _months(value: int) -> int:
    try:
        return max(1, min(int(value), 120))
    except (TypeError, ValueError):
        return 12


def _iso_date(value: str, field: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} 必须是 YYYY-MM-DD") from exc
    return value


def _stat_month(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    try:
        datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ValueError("stat_month 必须是 YYYY-MM") from exc
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ")
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _execute(tool: str, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    if not sql.lstrip().upper().startswith(("SELECT", "WITH")):
        raise RuntimeError("拒绝执行非只读语句")
    started = time.perf_counter()
    try:
        with POOL.query_slot(), POOL.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
    except Exception:
        elapsed = time.perf_counter() - started
        RUNTIME_METRICS.record(tool, "error", elapsed)
        LOGGER.exception(
            "tool=%s params_count=%d elapsed_ms=%.1f status=error",
            tool,
            len(params),
            (time.perf_counter() - started) * 1000,
        )
        raise
    result = [{key: _json_value(value) for key, value in row.items()} for row in rows]
    RUNTIME_METRICS.record(tool, "success", time.perf_counter() - started, len(result))
    LOGGER.info(
        "tool=%s params_count=%d elapsed_ms=%.1f returned_count=%d",
        tool,
        len(params),
        (time.perf_counter() - started) * 1000,
        len(result),
    )
    return result


def _scope(**values: Any) -> dict[str, Any]:
    scope = {key: value for key, value in values.items() if value not in (None, "", False)}
    if values.get("kks_code"):
        scope["match_method"] = "exact_kks"
    elif values.get("asset_code"):
        scope["match_method"] = "exact_asset"
    elif values.get("equipment_name") and values.get("location_name"):
        scope["match_method"] = "name_and_location"
    elif values.get("equipment_name"):
        scope["match_method"] = "equipment_name"
    elif values.get("location_name"):
        scope["match_method"] = "location_name"
    return scope


def _response(
    data: Any,
    *,
    scope: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    limit: int | None = None,
    deduplicate_key: str = "",
    data_boundary: str = "",
) -> dict[str, Any]:
    truncated = bool(limit and isinstance(data, list) and len(data) > limit)
    if truncated:
        data = data[:limit]
    count = len(data) if isinstance(data, list) else (1 if data else 0)
    return {
        "contract_version": RESPONSE_CONTRACT_VERSION,
        "service_version": SETTINGS.service_version,
        "semantic_fingerprint": SEMANTIC_FINGERPRINT,
        "request_id": str(uuid.uuid4()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "code": 0,
        "message": "success",
        "need_clarification": False,
        "clarification_message": "",
        "query_scope": scope or {},
        "summary": summary or {},
        "data": data,
        "meta": {
            "deduplicate_key": deduplicate_key,
            "limit": limit,
            "returned_count": count,
            "truncated": truncated,
            "data_boundary": data_boundary,
        },
    }


def _clarification(message: str, scope: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "contract_version": RESPONSE_CONTRACT_VERSION,
        "service_version": SETTINGS.service_version,
        "semantic_fingerprint": SEMANTIC_FINGERPRINT,
        "request_id": str(uuid.uuid4()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "code": 400,
        "message": message,
        "need_clarification": True,
        "clarification_message": message,
        "query_scope": scope or {},
        "summary": {},
        "data": [],
        "meta": {"returned_count": 0, "truncated": False},
    }


def _locator(
    *,
    kks_code: str = "",
    asset_code: str = "",
    equipment_name: str = "",
    location_name: str = "",
    kks_field: str = "LOCATION",
    location_field: str = "location_name",
    asset_field: str = "assetnum",
) -> tuple[list[str], list[Any]]:
    kks_code = _input_text(kks_code, "kks_code", 128)
    asset_code = _input_text(asset_code, "asset_code", 128)
    equipment_name = _input_text(equipment_name, "equipment_name", 100)
    location_name = _input_text(location_name, "location_name", 200)
    if kks_code:
        return [f"{kks_field} = %s"], [kks_code]
    if asset_code:
        return [f"{asset_field} = %s"], [asset_code]
    conditions: list[str] = []
    params: list[Any] = []
    if equipment_name:
        _validate_fuzzy(equipment_name, "equipment_name")
        conditions.append(f"(equipment_name LIKE %s ESCAPE '=' OR {location_field} LIKE %s ESCAPE '=')")
        pattern = _like_pattern(equipment_name)
        params.extend([pattern, pattern])
    if location_name:
        _validate_fuzzy(location_name, "location_name")
        conditions.append(f"{location_field} LIKE %s ESCAPE '='")
        params.append(_like_pattern(location_name))
    return conditions, params


def _input_text(value: Any, field: str, maximum: int = 200) -> str:
    text = str(value or "").strip()
    if len(text) > maximum:
        raise ValueError(f"{field} 长度不能超过 {maximum}")
    if any(ord(char) < 32 for char in text):
        raise ValueError(f"{field} 不能包含控制字符")
    return text


def _validate_fuzzy(value: str, field: str) -> None:
    visible = value.replace("%", "").replace("_", "").strip()
    if len(visible) < SETTINGS.fuzzy_min_length:
        raise ValueError(f"{field} 模糊查询至少需要 {SETTINGS.fuzzy_min_length} 个字符")


def _like_pattern(value: str) -> str:
    return "%" + value.replace("=", "==").replace("%", "=%").replace("_", "=_") + "%"


def _add_like(conditions: list[str], params: list[Any], field: str, value: str) -> None:
    value = _input_text(value, field)
    if value:
        _validate_fuzzy(value, field)
        conditions.append(f"{field} LIKE %s ESCAPE '='")
        params.append(_like_pattern(value))


@MCP.tool()
def search_equipment(
    kks_code: str = "",
    asset_code: str = "",
    equipment_name: str = "",
    location_name: str = "",
    specialty_name: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """根据 KKS、资产编码、设备名称或地点查询设备候选；精确编码优先。"""
    limit = _limit(limit, 10)
    scope = _scope(kks_code=kks_code, asset_code=asset_code, equipment_name=equipment_name,
                   location_name=location_name, specialty_name=specialty_name)
    defect_conditions, defect_params = _locator(
        kks_code=kks_code, asset_code=asset_code,
        equipment_name=equipment_name, location_name=location_name,
    )
    workorder_conditions, workorder_params = _locator(
        kks_code=kks_code, asset_code=asset_code,
        equipment_name=equipment_name, location_name=location_name,
        location_field="kks_name", asset_field="ASSETNUM",
    )
    _add_like(defect_conditions, defect_params, "specialty_name", specialty_name)
    _add_like(workorder_conditions, workorder_params, "specialty_name", specialty_name)
    if not defect_conditions:
        return _clarification("请提供设备名称、地点、KKS编码或资产编码。", scope)
    defect_where = " AND ".join(defect_conditions)
    workorder_where = " AND ".join(workorder_conditions)
    source_sql = """
        SELECT
          COALESCE(NULLIF(LOCATION, ''), NULLIF(assetnum, '')) AS equipment_id,
          LOCATION, {location_field} AS location_name,
          assetnum, equipment_name, specialty_name
        FROM {source} WHERE {where}
        LIMIT %s
    """
    exact_search = bool(kks_code.strip() or asset_code.strip())
    candidate_limit = limit + 1 if exact_search else min(max((limit + 1) * 20, 100), 1000)
    defect_rows = _execute(
        "search_equipment.defect",
        source_sql.format(
            location_field="location_name", source=DEFECT_EQUIPMENT_VIEW, where=defect_where
        ),
        defect_params + [candidate_limit],
    )
    workorder_rows = _execute(
        "search_equipment.workorder",
        source_sql.format(
            location_field="kks_name", source=WORKORDER_EQUIPMENT_VIEW, where=workorder_where
        ),
        workorder_params + [candidate_limit],
    )
    merged: dict[str, dict[str, Any]] = {}
    for source_name, source_rows in (("defect", defect_rows), ("workorder", workorder_rows)):
        for row in source_rows:
            key = str(row.get("equipment_id") or "")
            if not key:
                continue
            target = merged.setdefault(key, {**row, "data_sources": []})
            for field, value in row.items():
                if value not in (None, "") and target.get(field) in (None, ""):
                    target[field] = value
            if source_name not in target["data_sources"]:
                target["data_sources"].append(source_name)
    rows = list(merged.values())
    for row in rows:
        if kks_code.strip() and row.get("LOCATION") == kks_code.strip():
            row["match_method"] = "精确KKS命中"
        elif asset_code.strip() and row.get("assetnum") == asset_code.strip():
            row["match_method"] = "精确资产编码命中"
        else:
            row["match_method"] = "名称或地点模糊命中"
    rows.sort(
        key=lambda row: (
            row["match_method"] != "精确KKS命中",
            row["match_method"] != "精确资产编码命中",
            str(row.get("equipment_name") or ""),
        )
    )
    for row in rows:
        row["name_match"] = int(
            not equipment_name.strip()
            or equipment_name.strip().lower() in str(row.get("equipment_name") or "").lower()
            or equipment_name.strip().lower() in str(row.get("location_name") or "").lower()
        )
        row["location_exact_match"] = int(
            not location_name.strip()
            or location_name.strip().lower() in str(row.get("location_name") or "").lower()
        )
        row["location_relaxed_match"] = row["location_exact_match"]
    return _response(rows, scope=scope, limit=limit)


def _defect_filters(**values: Any) -> tuple[list[str], list[Any]]:
    conditions, params = _locator(
        kks_code=values.get("kks_code", ""), asset_code=values.get("asset_code", ""),
        equipment_name=values.get("equipment_name", ""), location_name=values.get("location_name", ""),
    )
    exact_fields = ("TICKETID", "S_QXLB", "status")
    for field in exact_fields:
        value = str(values.get(field, "") or "").strip()
        if value:
            conditions.append(f"{field} = %s")
            params.append(value)
    for field in ("S_CLASSIFICATION", "specialty_name", "TEAMNAME", "C_JZH"):
        _add_like(conditions, params, field, str(values.get(field, "") or ""))
    if values.get("open_only"):
        conditions.append("COALESCE(status, '') NOT IN (%s, %s, %s)")
        params.extend(CLOSED_STATUSES)
    return conditions, params


@MCP.tool()
def search_defects(
    defect_code: str = "", kks_code: str = "", asset_code: str = "",
    equipment_name: str = "", location_name: str = "", defect_type_name: str = "",
    defect_classification: str = "", defect_status: str = "", specialty_name: str = "",
    maintenance_team_name: str = "", unit_name: str = "", open_only: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    """查询缺陷列表或未关闭缺陷；缺陷数据不支持日期趋势、超期或处理时长。"""
    limit = _limit(limit)
    values = locals().copy()
    conditions, params = _defect_filters(**values)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"""SELECT TICKETID, S_QXLB, S_CLASSIFICATION, status,
       DESCRIPTION, specialty_name, C_JZH, LOCATION, location_name,
       assetnum, equipment_name, TEAMNAME, S_FINISHREPORT,
       S_YXYS, S_GZZJ
    FROM {DEFECT_VIEW}{where} ORDER BY TICKETID DESC LIMIT %s"""
    rows = _execute("search_defects", sql, params + [limit + 1])
    return _response(rows, scope=_scope(**values), limit=limit, deduplicate_key="TICKETID",
                     data_boundary=DATA_BOUNDARIES["defect"])


@MCP.tool()
def get_defect_detail(defect_code: str) -> dict[str, Any]:
    """根据唯一缺陷编号获取一条完整、去重的缺陷记录。"""
    defect_code = defect_code.strip()
    if not defect_code:
        return _clarification("请提供缺陷编号。")
    rows = _execute(
        "get_defect_detail",
        f"SELECT {DEFECT_COLUMNS} FROM {DEFECT_VIEW} WHERE TICKETID = %s LIMIT 1",
        [defect_code],
    )
    return _response(rows[0] if rows else {}, scope={"defect_code": defect_code},
                     deduplicate_key="TICKETID",
                     data_boundary=DATA_BOUNDARIES["defect"])


@MCP.tool()
def summarize_defects(
    group_by: str = "specialty", kks_code: str = "", asset_code: str = "",
    equipment_name: str = "", location_name: str = "", specialty_name: str = "",
    defect_type_name: str = "", open_only: bool = False, limit: int = 10,
) -> dict[str, Any]:
    """按类别、状态、专业、班组、机组、缺陷分类或 KKS 统计缺陷。"""
    dimensions = DIMENSIONS["defect"]
    if group_by not in dimensions:
        return _clarification("group_by 只允许 type、status、specialty、team、unit、classification、kks。")
    limit = _limit(limit, 10)
    values = locals().copy()
    conditions, params = _defect_filters(
        kks_code=kks_code, asset_code=asset_code, equipment_name=equipment_name,
        location_name=location_name, specialty_name=specialty_name,
        defect_type_name=defect_type_name, open_only=open_only,
    )
    field = dimensions[group_by]
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    location_select = ", MAX(location_name) AS location_name" if group_by == "kks" else ""
    sql = f"""SELECT COALESCE({field}, '未标注') AS dimension_value{location_select},
       {_metric('defect_count')} AS defect_count,
       {_metric('closed_defect_count')} AS closed_count,
       {_metric('open_defect_count')} AS open_count
    FROM {DEFECT_VIEW}{where}
    GROUP BY COALESCE({field}, '未标注')
    ORDER BY {'open_count' if open_only else 'defect_count'} DESC LIMIT %s"""
    rows = _execute("summarize_defects", sql, params + [limit + 1])
    if group_by == "kks":
        for row in rows:
            row["LOCATION"] = row.pop("dimension_value")
    return _response(rows, scope=_scope(**values), limit=limit, deduplicate_key="TICKETID",
                     data_boundary=DATA_BOUNDARIES["defect"])


def _workorder_filters(**values: Any) -> tuple[list[str], list[Any]]:
    conditions, params = _locator(
        kks_code=values.get("kks_code", ""), asset_code=values.get("asset_code", ""),
        equipment_name=values.get("equipment_name", ""), location_name=values.get("location_name", ""),
        location_field="kks_name", asset_field="ASSETNUM",
    )
    for field in ("wonum", "status"):
        value = str(values.get(field, "") or "").strip()
        if value:
            conditions.append(f"{field} = %s")
            params.append(value)
    for field in ("specialty_name", "maintenance_team_name"):
        _add_like(conditions, params, field, str(values.get(field, "") or ""))
    start_from = _iso_date(str(values.get("planned_start_from", "") or ""), "planned_start_from")
    start_to = _iso_date(str(values.get("planned_start_to", "") or ""), "planned_start_to")
    if start_from:
        conditions.append("SCHEDSTART >= %s")
        params.append(start_from + " 00:00:00")
    if start_to:
        conditions.append("SCHEDSTART < DATE_ADD(%s, INTERVAL 1 DAY)")
        params.append(start_to)
    if values.get("overdue_only"):
        anchor = _iso_date(str(values.get("as_of_date", "") or ""), "as_of_date")
        conditions.append("COALESCE(status, '') NOT IN (%s, %s, %s)")
        params.extend(CLOSED_STATUSES)
        if anchor:
            conditions.append("SCHEDFINISH < DATE_ADD(%s, INTERVAL 1 DAY)")
            params.append(anchor)
        else:
            conditions.append("SCHEDFINISH < CURRENT_TIMESTAMP")
    elif values.get("open_only"):
        conditions.append("COALESCE(status, '') NOT IN (%s, %s, %s)")
        params.extend(CLOSED_STATUSES)
    return conditions, params


@MCP.tool()
def search_workorders(
    workorder_code: str = "", kks_code: str = "", asset_code: str = "",
    equipment_name: str = "", location_name: str = "", workorder_status: str = "",
    specialty_name: str = "", maintenance_team_name: str = "",
    planned_start_from: str = "", planned_start_to: str = "", open_only: bool = False,
    overdue_only: bool = False,
    as_of_date: str = "", limit: int = 20,
) -> dict[str, Any]:
    """查询工单列表；超期仅表示计划完成时间已过且工单尚未关闭。"""
    limit = _limit(limit)
    values = locals().copy()
    conditions, params = _workorder_filters(**values)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT {WORKORDER_COLUMNS} FROM {WORKORDER_VIEW}{where} ORDER BY SCHEDFINISH, SCHEDSTART DESC LIMIT %s"
    rows = _execute("search_workorders", sql, params + [limit + 1])
    return _response(rows, scope=_scope(**values), limit=limit, deduplicate_key="wonum",
                     data_boundary=DATA_BOUNDARIES["workorder"])


@MCP.tool()
def get_workorder_detail(workorder_code: str) -> dict[str, Any]:
    """根据工单编号查询完整工单，并将关联物料和工作票聚合为数组。"""
    workorder_code = workorder_code.strip()
    if not workorder_code:
        return _clarification("请提供工单编号。")
    rows = _execute("get_workorder_detail", f"SELECT {WORKORDER_COLUMNS} FROM {WORKORDER_FAST_VIEW} WHERE wonum = %s LIMIT 50", [workorder_code])
    if not rows:
        return _response({}, scope={"workorder_code": workorder_code}, deduplicate_key="wonum")
    detail = dict(rows[0])
    detail["materials"] = list({
        (row.get("itemnum"), row.get("material_name")): {
            "itemnum": row.get("itemnum"), "material_name": row.get("material_name")
        }
        for row in rows if row.get("itemnum") or row.get("material_name")
    }.values())
    detail["work_tickets"] = list({
        row.get("work_ticket_code"): {
            "work_ticket_code": row.get("work_ticket_code"), "work_ticket_status": row.get("work_ticket_status")
        }
        for row in rows if row.get("work_ticket_code")
    }.values())
    for field in ("itemnum", "material_name", "work_ticket_code", "work_ticket_status"):
        detail.pop(field, None)
    return _response(detail, scope={"workorder_code": workorder_code}, deduplicate_key="wonum",
                     data_boundary=DATA_BOUNDARIES["workorder"])


@MCP.tool()
def summarize_workorders(
    group_by: str = "team", kks_code: str = "", asset_code: str = "",
    equipment_name: str = "", location_name: str = "", specialty_name: str = "",
    maintenance_team_name: str = "", months: int = 12, stat_month: str = "",
    as_of_date: str = "", limit: int = 10,
) -> dict[str, Any]:
    """按状态、专业、班组、月份、工作票关联或月度关闭率统计工单。"""
    allowed = set(DIMENSIONS["workorder"])
    if group_by not in allowed:
        return _clarification("group_by 只允许 status、specialty、team、month、ticket_linkage、monthly_closure。")
    limit, months = _limit(limit, 10), _months(months)
    stat_month = _stat_month(stat_month)
    as_of_date = _iso_date(as_of_date, "as_of_date")
    values = locals().copy()
    conditions, params = _workorder_filters(
        kks_code=kks_code, asset_code=asset_code, equipment_name=equipment_name,
        location_name=location_name, specialty_name=specialty_name,
        maintenance_team_name=maintenance_team_name,
    )
    if group_by in {"month", "monthly_closure"}:
        if stat_month:
            conditions.append("DATE_FORMAT(SCHEDSTART, '%%Y-%%m') = %s")
            params.append(stat_month)
        else:
            conditions.append(f"SCHEDSTART >= DATE_SUB((SELECT MAX(SCHEDSTART) FROM {WORKORDER_VIEW}), INTERVAL %s MONTH)")
            params.append(months - 1)
        field, unknown = "DATE_FORMAT(SCHEDSTART, '%%Y-%%m')", ""
    elif group_by == "ticket_linkage":
        field, unknown = "CASE WHEN NULLIF(TRIM(work_ticket_code), '') IS NULL THEN '未关联工作票' ELSE '已关联工作票' END", ""
    else:
        field, unknown = {
            "status": ("status", "未标注状态"),
            "specialty": ("specialty_name", "未标注专业"),
            "team": ("maintenance_team_name", "未标注班组"),
        }[group_by]
    dimension = field if not unknown else f"COALESCE({field}, '{unknown}')"
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    anchor_params = [as_of_date] if as_of_date else []
    overdue_expression = _metric("overdue_workorder_count") if not as_of_date else (
        "COUNT(DISTINCT CASE WHEN COALESCE(status, '') NOT IN (%s, %s, %s) "
        "AND SCHEDFINISH < DATE_ADD(%s, INTERVAL 1 DAY) THEN wonum END)"
    )
    sql = f"""SELECT {dimension} AS dimension_value, {_metric('workorder_count')} AS workorder_count,
       {_metric('closed_workorder_count')} AS closed_count,
       {_metric('open_workorder_count')} AS pending_count,
       {overdue_expression} AS overdue_count
    FROM {WORKORDER_VIEW}{where} GROUP BY {dimension} ORDER BY dimension_value DESC LIMIT %s"""
    query_params = (list(CLOSED_STATUSES) + anchor_params if as_of_date else []) + params + [limit + 1]
    rows = _execute("summarize_workorders", sql, query_params)
    if group_by in {"month", "monthly_closure"}:
        for row in rows:
            row["stat_month"] = row.pop("dimension_value")
            if group_by == "monthly_closure":
                total = row.get("workorder_count") or 0
                row["closure_rate"] = round((row.get("closed_count") or 0) * 100 / total, 2) if total else 0
                row["calculation_note"] = "关闭率代理口径：已关闭工单数/当月工单总数"
    elif group_by == "ticket_linkage":
        for row in rows:
            row["linkage_status"] = row.pop("dimension_value")
    return _response(rows, scope=_scope(**values), limit=limit, deduplicate_key="wonum",
                     data_boundary=DATA_BOUNDARIES["workorder"])


@MCP.tool()
def analyze_workorder_failures(
    dimension: str = "cause", kks_code: str = "", asset_code: str = "",
    equipment_name: str = "", location_name: str = "", specialty_name: str = "",
    maintenance_team_name: str = "", limit: int = 10,
) -> dict[str, Any]:
    """统计工单故障类别、问题、原因或补救措施集中度。"""
    fields = DIMENSIONS["failure"]
    if dimension not in fields:
        return _clarification("dimension 只允许 category、problem、cause、remedy。")
    limit = _limit(limit, 10)
    values = locals().copy()
    conditions, params = _workorder_filters(
        kks_code=kks_code, asset_code=asset_code, equipment_name=equipment_name,
        location_name=location_name, specialty_name=specialty_name,
        maintenance_team_name=maintenance_team_name,
    )
    field = fields[dimension]
    conditions.append(f"NULLIF(TRIM({field}), '') IS NOT NULL")
    where = " AND ".join(conditions)
    sql = f"""SELECT %s AS dimension, {field} AS dimension_value,
       {_metric('workorder_count')} AS workorder_count,
       {_metric('overdue_workorder_count')} AS overdue_count
    FROM {WORKORDER_VIEW} WHERE {where} GROUP BY {field} ORDER BY workorder_count DESC LIMIT %s"""
    rows = _execute("analyze_workorder_failures", sql, [dimension] + params + [limit + 1])
    return _response(rows, scope=_scope(**values), limit=limit, deduplicate_key="wonum",
                     data_boundary=DATA_BOUNDARIES["workorder"])


@MCP.tool()
def analyze_workorder_materials(
    kks_code: str = "", asset_code: str = "", equipment_name: str = "",
    location_name: str = "", specialty_name: str = "", maintenance_team_name: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """统计工单物料/备件使用频次及覆盖设备数。"""
    limit = _limit(limit, 10)
    values = locals().copy()
    conditions, params = _workorder_filters(**values)
    conditions.append("(NULLIF(TRIM(itemnum), '') IS NOT NULL OR NULLIF(TRIM(material_name), '') IS NOT NULL)")
    sql = f"""SELECT itemnum, MAX(material_name) AS material_name,
       COUNT(DISTINCT wonum) AS workorder_count,
       COUNT(DISTINCT COALESCE(NULLIF(LOCATION, ''), NULLIF(ASSETNUM, ''))) AS equipment_count
    FROM {WORKORDER_FAST_VIEW} WHERE {' AND '.join(conditions)}
    GROUP BY itemnum ORDER BY workorder_count DESC LIMIT %s"""
    rows = _execute("analyze_workorder_materials", sql, params + [limit + 1])
    return _response(rows, scope=_scope(**values), limit=limit, deduplicate_key="wonum")


@MCP.tool()
def get_equipment_operation_summary(
    kks_code: str = "", asset_code: str = "", equipment_name: str = "", location_name: str = "",
) -> dict[str, Any]:
    """查询指定设备的缺陷和工单总体情况。"""
    scope = _scope(kks_code=kks_code, asset_code=asset_code, equipment_name=equipment_name,
                   location_name=location_name)
    defect_conditions, defect_params = _locator(
        kks_code=kks_code, asset_code=asset_code, equipment_name=equipment_name,
        location_name=location_name,
    )
    order_conditions, order_params = _locator(
        kks_code=kks_code, asset_code=asset_code, equipment_name=equipment_name,
        location_name=location_name,
        location_field="kks_name", asset_field="ASSETNUM",
    )
    if not defect_conditions and not order_conditions:
        return _clarification("请提供设备名称、地点、KKS编码或资产编码。", scope)
    sql = f"""SELECT
      (SELECT MAX(LOCATION) FROM {DEFECT_VIEW} WHERE {' AND '.join(defect_conditions)}) AS LOCATION,
      (SELECT MAX(equipment_name) FROM {DEFECT_VIEW} WHERE {' AND '.join(defect_conditions)}) AS equipment_name,
      (SELECT COUNT(*) FROM {DEFECT_VIEW} WHERE {' AND '.join(defect_conditions)}) AS defect_total_count,
      (SELECT COUNT(*) FROM {DEFECT_VIEW} WHERE {' AND '.join(defect_conditions)}
         AND COALESCE(status, '') NOT IN (%s, %s, %s)) AS defect_open_count,
      (SELECT COUNT(*) FROM {WORKORDER_VIEW} WHERE {' AND '.join(order_conditions)}) AS workorder_total_count,
      (SELECT COUNT(*) FROM {WORKORDER_VIEW} WHERE {' AND '.join(order_conditions)}
         AND COALESCE(status, '') NOT IN (%s, %s, %s)) AS workorder_open_count,
      (SELECT COUNT(*) FROM {WORKORDER_VIEW} WHERE {' AND '.join(order_conditions)}
         AND COALESCE(status, '') NOT IN (%s, %s, %s)
         AND SCHEDFINISH < CURRENT_TIMESTAMP) AS workorder_overdue_count"""
    params = (
        defect_params + defect_params + defect_params + defect_params + list(CLOSED_STATUSES)
        + order_params + order_params + list(CLOSED_STATUSES)
        + order_params + list(CLOSED_STATUSES)
    )
    row = _execute("get_equipment_operation_summary", sql, params)[0]
    data = {
        "equipment": {"LOCATION": row.get("LOCATION") or kks_code, "equipment_name": row.get("equipment_name") or equipment_name},
        "defect": {"total_count": row["defect_total_count"], "open_count": row["defect_open_count"],
                   "closed_count": row["defect_total_count"] - row["defect_open_count"]},
        "workorder": {"total_count": row["workorder_total_count"], "open_count": row["workorder_open_count"],
                      "closed_count": row["workorder_total_count"] - row["workorder_open_count"],
                      "overdue_count": row["workorder_overdue_count"]},
    }
    return _response(data, scope=scope, data_boundary=f"{DATA_BOUNDARIES['defect']}；{DATA_BOUNDARIES['workorder']}")


@MCP.tool()
def get_maintenance_dashboard(
    domain: str,
    view: str = "capabilities",
    message: str = "",
    limit: int = 10,
    kks_code: str = "",
    asset_code: str = "",
    equipment_name: str = "",
    location_name: str = "",
    specialty_name: str = "",
    maintenance_team_name: str = "",
) -> dict[str, Any]:
    """返回缺陷或工单智能体的能力导航、数据概况、时间边界或澄清消息。

    这是工作流支持工具，不接受自由 SQL，也不替代 10 个业务查询工具。
    """
    if domain not in {"defect", "workorder"}:
        return _clarification("domain 只允许 defect 或 workorder。")
    if view not in {"capabilities", "overview", "freshness", "clarification"}:
        return _clarification("view 只允许 capabilities、overview、freshness、clarification。")
    limit = _limit(limit, 10)
    scope = _scope(
        domain=domain, view=view, kks_code=kks_code, asset_code=asset_code,
        equipment_name=equipment_name, location_name=location_name,
        specialty_name=specialty_name, maintenance_team_name=maintenance_team_name,
    )
    if view == "clarification":
        return _clarification(message.strip() or "请补充查询对象或筛选条件。", scope)

    if view == "capabilities":
        rows = [
            {
                "query_category": tool["label"],
                "tool_name": tool_name,
                "supported_question": "、".join(tool["intents"]),
                "semantic_fingerprint": SEMANTIC_FINGERPRINT,
            }
            for tool_name, tool in TOOL_CATALOG.items()
            if domain in tool["domains"]
        ]
        return _response(rows[:limit], scope=scope, limit=limit)

    if domain == "defect":
        conditions, params = _defect_filters(
            kks_code=kks_code, asset_code=asset_code, equipment_name=equipment_name,
            location_name=location_name, specialty_name=specialty_name,
            maintenance_team_name=maintenance_team_name,
        )
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        if view == "freshness":
            return _response(
                [{"defect_time_note": DATA_BOUNDARIES["defect"]}],
                scope=scope,
                data_boundary=DATA_BOUNDARIES["defect"],
            )
        sql = f"""SELECT {_metric('defect_count')} AS defect_count,
          {_metric('open_defect_count')} AS open_defect_count,
          COUNT(DISTINCT NULLIF(LOCATION, '')) AS equipment_count
        FROM {DEFECT_VIEW}{where}"""
        rows = _execute("get_maintenance_dashboard", sql, params)
        return _response(rows, scope=scope, summary=rows[0] if rows else {},
                         data_boundary=DATA_BOUNDARIES["defect"])

    conditions, params = _workorder_filters(
        kks_code=kks_code, asset_code=asset_code, equipment_name=equipment_name,
        location_name=location_name, specialty_name=specialty_name,
        maintenance_team_name=maintenance_team_name,
    )
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    if view == "freshness":
        sql = f"""SELECT MIN(SCHEDSTART) AS first_workorder_date,
          MAX(SCHEDSTART) AS latest_workorder_date,
          MAX(SCHEDFINISH) AS latest_planned_finish_date,
          %s AS workorder_time_note
        FROM {WORKORDER_VIEW}{where}"""
        rows = _execute("get_maintenance_dashboard", sql, [DATA_BOUNDARIES["workorder"]] + params)
        return _response(rows, scope=scope, data_boundary=DATA_BOUNDARIES["workorder"])
    sql = f"""SELECT {_metric('workorder_count')} AS workorder_count,
      {_metric('closed_workorder_count')} AS closed_count,
      {_metric('open_workorder_count')} AS open_workorder_count,
      {_metric('overdue_workorder_count')} AS overdue_count,
      COUNT(DISTINCT NULLIF(LOCATION, '')) AS equipment_count
    FROM {WORKORDER_VIEW}{where}"""
    rows = _execute("get_maintenance_dashboard", sql, params)
    return _response(rows, scope=scope, summary=rows[0] if rows else {},
                     data_boundary=DATA_BOUNDARIES["workorder"])


def _readiness() -> tuple[bool, dict[str, Any]]:
    try:
        SETTINGS.validate_startup()
        POOL.ping()
        missing = POOL.validate_views(VIEW_CONTRACTS)
        if missing:
            return False, {"status": "not_ready", "reason": "view_contract_mismatch", "missing": missing}
        actual_schema_version = POOL.schema_version()
        if actual_schema_version != DATABASE_SCHEMA_VERSION:
            return False, {
                "status": "not_ready",
                "reason": "database_schema_version_mismatch",
                "expected": DATABASE_SCHEMA_VERSION,
                "actual": actual_schema_version,
            }
        snapshot = POOL.snapshot_status()
        if DEFECT_VIEW == "mcp_defect_current" and not snapshot:
            return False, {"status": "not_ready", "reason": "defect_snapshot_not_published"}
        return True, {
            "status": "ready",
            "service_version": SETTINGS.service_version,
            "semantic_fingerprint": SEMANTIC_FINGERPRINT,
            "database_schema_version": actual_schema_version,
            "defect_snapshot": snapshot,
        }
    except Exception as exc:
        LOGGER.warning("readiness_failed error_type=%s", type(exc).__name__)
        return False, {"status": "not_ready", "reason": type(exc).__name__}


def _parse_analysis_kks(kks_code: str) -> dict[str, Any]:
    """Parse the flexible KKS levels used by the Dify defect-analysis workflow."""
    code = re.sub(r"[\s._/]+", "", str(kks_code or "").strip().upper())
    result: dict[str, Any] = {
        "normalized_kks": code,
        "valid": False,
        "level": "UNKNOWN",
        "system_kks": "",
        "equipment_kks": "",
        "system_class_code": "",
        "equipment_class_code": "",
        "current_scope_kks": "",
    }
    if not code or len(code) > 17 or not re.fullmatch(r"[A-Z0-9-]+", code):
        return result
    checks = (
        (0, 1, r"[A-Z0-9]+"),
        (1, 2, r"[0-9]+"),
        (2, min(len(code), 5), r"[A-Z]+"),
        (5, min(len(code), 7), r"[0-9]+"),
        (7, min(len(code), 9), r"[A-Z]+"),
        (9, min(len(code), 12), r"[0-9]+"),
    )
    for start, end, pattern in checks:
        if len(code) > start and not re.fullmatch(pattern, code[start:end]):
            return result
    result["valid"] = True
    result["system_class_code"] = code[2:min(5, len(code))] if len(code) > 2 else ""
    result["system_kks"] = code[:7] if len(code) >= 7 else ""
    result["equipment_class_code"] = code[7:min(9, len(code))] if len(code) > 7 else ""
    result["equipment_kks"] = code[:12] if len(code) >= 12 else ""
    result["current_scope_kks"] = result["equipment_kks"] or code
    levels = {
        1: "PLANT", 2: "PLANT_SYSTEM_PREFIX", 5: "SYSTEM_CLASS",
        7: "SYSTEM", 9: "EQUIPMENT_CLASS", 12: "EQUIPMENT",
        16: "COMPONENT", 17: "COMPONENT_WITH_ADDITIONAL",
    }
    result["level"] = levels.get(len(code), "PARTIAL")
    return result


def _analysis_page(page: int, page_size: int) -> tuple[int, int, int]:
    try:
        safe_page = max(1, int(page))
        safe_size = max(1, min(int(page_size), ANALYSIS_PAGE_MAX))
    except (TypeError, ValueError):
        safe_page, safe_size = 1, 100
    return safe_page, safe_size, (safe_page - 1) * safe_size


def _analysis_query(
    tool: str,
    *,
    scope_name: str,
    where_sql: str,
    params: list[Any],
    page: int,
    page_size: int,
) -> dict[str, Any]:
    safe_page, safe_size, offset = _analysis_page(page, page_size)
    summary_sql = (
        f"SELECT COUNT(*) AS total_defect_count, "
        f"COUNT(DISTINCT kks_code) AS involved_kks_count "
        f"FROM {DEFECT_ANALYSIS_TABLE} WHERE {where_sql}"
    )
    detail_sql = (
        f"SELECT {ANALYSIS_FIELDS} FROM {DEFECT_ANALYSIS_TABLE} "
        f"WHERE {where_sql} ORDER BY defect_code LIMIT %s OFFSET %s"
    )
    summary_rows = _execute(tool, summary_sql, params)
    details = _execute(tool, detail_sql, [*params, safe_size, offset])
    summary = summary_rows[0] if summary_rows else {
        "total_defect_count": 0, "involved_kks_count": 0,
    }
    total = int(summary.get("total_defect_count") or 0)
    return {
        "contract_version": RESPONSE_CONTRACT_VERSION,
        "service_version": SETTINGS.service_version,
        "request_id": str(uuid.uuid4()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "code": 0,
        "message": "success",
        "query_scope": {"scope": scope_name},
        "summary": summary,
        "data": details,
        "pagination": {
            "page": safe_page,
            "page_size": safe_size,
            "returned_count": len(details),
            "total_count": total,
            "has_more": offset + len(details) < total,
            "next_page": safe_page + 1 if offset + len(details) < total else None,
        },
        "data_boundary": (
            "统计覆盖全部匹配缺陷；明细采用分页返回。按next_page连续调用可取完全部数据。"
        ),
    }


@MCP.tool()
def parse_kks_code(kks_code: str) -> dict[str, Any]:
    """解析长短KKS，返回当前范围、系统码以及同类型匹配所需分类码。"""
    parsed = _parse_analysis_kks(kks_code)
    if not parsed["valid"]:
        return _clarification("KKS格式无法识别，请提供由字母、数字或连字符组成的有效位置编码。")
    return _response(parsed, scope={"kks_code": parsed["normalized_kks"]})


@MCP.tool()
def resolve_defect_equipment(kks_code: str) -> dict[str, Any]:
    """按KKS从资产、工单和工作票设备视图中解析设备主数据，不补造缺失字段。"""
    parsed = _parse_analysis_kks(kks_code)
    if not parsed["valid"]:
        return _clarification("KKS格式无法识别。")
    code = parsed["normalized_kks"]
    sql = f"""
    SELECT
      MAX(source_rows.equipment_id) AS equipment_id,
      MAX(source_rows.equipment_code) AS equipment_code,
      source_rows.kks_code,
      MAX(source_rows.equipment_name) AS equipment_name,
      MAX(source_rows.location_name) AS location_name,
      MAX(source_rows.specialty_name) AS specialty_name
    FROM (
      SELECT COALESCE(NULLIF(assetnum,''),NULLIF(LOCATION,'')) AS equipment_id,
             COALESCE(assetnum,'') AS equipment_code, LOCATION AS kks_code,
             COALESCE(equipment_name,location_name,'') AS equipment_name,
             COALESCE(location_name,'') AS location_name,
             COALESCE(specialty_name,'') AS specialty_name
      FROM {DEFECT_EQUIPMENT_VIEW} WHERE UPPER(TRIM(LOCATION)) = %s
      UNION ALL
      SELECT LOCATION, COALESCE(ASSETNUM,''), LOCATION,
             COALESCE(equipment_name,kks_name,''), COALESCE(kks_name,''),
             COALESCE(specialty_name,'')
      FROM {WORKORDER_EQUIPMENT_VIEW} WHERE UPPER(TRIM(LOCATION)) = %s
    ) source_rows
    GROUP BY source_rows.kks_code
    LIMIT 5
    """
    rows = _execute("resolve_defect_equipment", sql, [code, code])
    return _response(
        rows,
        scope={"kks_code": code, "match_method": "exact_kks"},
        summary={"matched": bool(rows), "match_count": len(rows)},
        deduplicate_key="kks_code",
    )


@MCP.tool()
def get_current_equipment_defects(
    kks_code: str, page: int = 1, page_size: int = 100,
) -> dict[str, Any]:
    """统计当前设备全部历史缺陷，并分页返回全部明细；支持短KKS前缀。"""
    parsed = _parse_analysis_kks(kks_code)
    if not parsed["valid"]:
        return _clarification("KKS格式无法识别。")
    if parsed["equipment_kks"]:
        where_sql, params = "equipment_kks = %s", [parsed["equipment_kks"]]
    else:
        where_sql, params = "kks_code LIKE %s", [parsed["current_scope_kks"] + "%"]
    result = _analysis_query(
        "get_current_equipment_defects", scope_name="CURRENT_EQUIPMENT",
        where_sql=where_sql, params=params, page=page, page_size=page_size,
    )
    result["query_scope"].update(parsed)
    return result


@MCP.tool()
def get_same_system_defects(
    kks_code: str, page: int = 1, page_size: int = 100,
) -> dict[str, Any]:
    """按system_kks查询同一具体系统的全部缺陷，排除当前主设备，明细分页返回。"""
    parsed = _parse_analysis_kks(kks_code)
    if not parsed["valid"] or not parsed["system_kks"]:
        return _clarification("至少需要7位KKS，才能识别同一具体系统。")
    where_sql = "system_kks = %s"
    params: list[Any] = [parsed["system_kks"]]
    if parsed["equipment_kks"]:
        where_sql += " AND equipment_kks <> %s"
        params.append(parsed["equipment_kks"])
    result = _analysis_query(
        "get_same_system_defects", scope_name="SAME_SYSTEM",
        where_sql=where_sql, params=params, page=page, page_size=page_size,
    )
    result["query_scope"].update(parsed)
    return result


@MCP.tool()
def get_same_type_defects(
    kks_code: str, page: int = 1, page_size: int = 100,
) -> dict[str, Any]:
    """按系统分类码和设备分类码查询同类型设备全部缺陷，排除当前主设备，明细分页返回。"""
    parsed = _parse_analysis_kks(kks_code)
    if (
        not parsed["valid"]
        or len(parsed["system_class_code"]) != 3
        or len(parsed["equipment_class_code"]) != 2
    ):
        return _clarification("至少需要9位KKS，才能识别完整系统分类码和设备分类码。")
    where_sql = "system_class_code = %s AND equipment_class_code = %s"
    params: list[Any] = [parsed["system_class_code"], parsed["equipment_class_code"]]
    if parsed["equipment_kks"]:
        where_sql += " AND equipment_kks <> %s"
        params.append(parsed["equipment_kks"])
    result = _analysis_query(
        "get_same_type_defects", scope_name="SAME_TYPE",
        where_sql=where_sql, params=params, page=page, page_size=page_size,
    )
    result["query_scope"].update(parsed)
    return result


@MCP.tool()
def get_defect_analysis_statistics(kks_code: str) -> dict[str, Any]:
    """一次返回当前设备、同系统、同类型三个范围的全量统计，不返回大体量明细。"""
    parsed = _parse_analysis_kks(kks_code)
    if not parsed["valid"]:
        return _clarification("KKS格式无法识别。")
    scopes: list[tuple[str, str, list[Any]]] = []
    if parsed["equipment_kks"]:
        scopes.append(("current_equipment", "equipment_kks = %s", [parsed["equipment_kks"]]))
    else:
        scopes.append(("current_scope", "kks_code LIKE %s", [parsed["current_scope_kks"] + "%"]))
    if parsed["system_kks"]:
        sql, values = "system_kks = %s", [parsed["system_kks"]]
        if parsed["equipment_kks"]:
            sql += " AND equipment_kks <> %s"
            values.append(parsed["equipment_kks"])
        scopes.append(("same_system", sql, values))
    if len(parsed["system_class_code"]) == 3 and len(parsed["equipment_class_code"]) == 2:
        sql = "system_class_code = %s AND equipment_class_code = %s"
        values = [parsed["system_class_code"], parsed["equipment_class_code"]]
        if parsed["equipment_kks"]:
            sql += " AND equipment_kks <> %s"
            values.append(parsed["equipment_kks"])
        scopes.append(("same_type", sql, values))
    statistics: dict[str, Any] = {}
    for name, where_sql, params in scopes:
        rows = _execute(
            "get_defect_analysis_statistics",
            f"SELECT COUNT(*) AS total_defect_count, "
            f"COUNT(DISTINCT kks_code) AS involved_kks_count "
            f"FROM {DEFECT_ANALYSIS_TABLE} WHERE {where_sql}",
            params,
        )
        statistics[name] = rows[0] if rows else {
            "total_defect_count": 0, "involved_kks_count": 0,
        }
    return _response(statistics, scope=parsed, data_boundary="全部匹配记录的精确统计")


@MCP.custom_route("/health/live", methods=["GET"], include_in_schema=False)
async def health_live(_: Request) -> JSONResponse:
    return JSONResponse({"status": "alive", "service_version": SETTINGS.service_version})


@MCP.custom_route("/health/ready", methods=["GET"], include_in_schema=False)
async def health_ready(_: Request) -> JSONResponse:
    ready, payload = _readiness()
    return JSONResponse(payload, status_code=200 if ready else 503)


@MCP.custom_route("/metrics", methods=["GET"], include_in_schema=False)
async def metrics(_: Request) -> PlainTextResponse:
    return PlainTextResponse(RUNTIME_METRICS.render(), media_type="text/plain; version=0.0.4")


@MCP.tool()
def get_service_status(check_database: bool = False) -> dict[str, Any]:
    """返回服务版本和语义指纹；可选执行数据库及视图契约检查。"""
    status: dict[str, Any] = {
        "status": "running",
        "service_version": SETTINGS.service_version,
        "contract_version": RESPONSE_CONTRACT_VERSION,
        "semantic_fingerprint": SEMANTIC_FINGERPRINT,
        "database_schema_version": DATABASE_SCHEMA_VERSION,
        "authentication_required": SETTINGS.auth_required,
    }
    if check_database:
        ready, readiness = _readiness()
        status["database_ready"] = ready
        status["readiness"] = readiness
    return _response(status)


def main() -> None:
    SETTINGS.validate_startup()
    if SETTINGS.mcp_transport != "stdio":
        ready, payload = _readiness()
        if not ready:
            LOGGER.warning("startup_readiness status=not_ready reason=%s", payload.get("reason", "unknown"))
    MCP.run(transport=SETTINGS.mcp_transport)


if __name__ == "__main__":
    main()
