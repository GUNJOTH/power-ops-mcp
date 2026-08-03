from unittest.mock import patch

import app
from generated import semantic_registry


def test_limit_is_capped():
    assert app._limit(999) == 50
    assert app._limit(0) == 1


def test_locator_prefers_exact_kks():
    conditions, params = app._locator(
        kks_code="Y0QEA01AN001", asset_code="A1", equipment_name="引风机", location_name="锅炉房"
    )
    assert conditions == ["LOCATION = %s"]
    assert params == ["Y0QEA01AN001"]


def test_invalid_dimension_does_not_query():
    with patch.object(app, "_execute") as execute:
        result = app.summarize_defects(group_by="sql")
    assert result["code"] == 400
    execute.assert_not_called()


def test_search_workorders_uses_bound_values_and_limit():
    with patch.object(app, "_execute", return_value=[]) as execute:
        result = app.search_workorders(equipment_name="引风机", overdue_only=True, limit=999)
    sql, params = execute.call_args.args[1:]
    assert "引风机" not in sql
    assert params[-1] == 51
    assert result["meta"]["limit"] == 50
    assert "SCHEDFINISH < CURRENT_TIMESTAMP" in sql


def test_search_workorders_supports_open_only_from_dify_agent():
    with patch.object(app, "_execute", return_value=[]) as execute:
        app.search_workorders(open_only=True)
    sql, params = execute.call_args.args[1:]
    assert "NOT IN (%s, %s, %s)" in sql
    assert params[-4:-1] == list(app.CLOSED_STATUSES)


def test_dashboard_capabilities_does_not_query_database():
    with patch.object(app, "_execute") as execute:
        result = app.get_maintenance_dashboard(domain="defect", view="capabilities")
    assert result["code"] == 0
    assert result["data"][0]["query_category"] == "缺陷明细"
    execute.assert_not_called()


def test_runtime_semantics_come_from_generated_registry():
    assert app.CLOSED_STATUSES == semantic_registry.CLOSED_STATUSES
    assert app.DEFECT_VIEW == semantic_registry.DATASETS["defect"]["source"]
    assert app.WORKORDER_VIEW == semantic_registry.DATASETS["workorder"]["source"]
    assert app.DIMENSIONS == semantic_registry.DIMENSIONS
    assert app.WORKORDER_FAST_VIEW == "vw_qa_work_order_mcp_fact"


def test_response_truncation_is_based_on_limit_plus_one():
    result = app._response([{"id": 1}, {"id": 2}, {"id": 3}], limit=2)
    assert result["data"] == [{"id": 1}, {"id": 2}]
    assert result["meta"]["truncated"] is True
    assert result["contract_version"] == "1.0"
    assert result["semantic_fingerprint"] == semantic_registry.SEMANTIC_FINGERPRINT


def test_like_pattern_escapes_wildcards():
    assert app._like_pattern("泵%_A") == "%泵=%=_A%"


def test_defect_detail_uses_explicit_contract_columns():
    with patch.object(app, "_execute", return_value=[]) as execute:
        app.get_defect_detail("D-1")
    sql = execute.call_args.args[1]
    assert "SELECT *" not in sql.upper()
    assert "TICKETID" in sql


def test_workorder_detail_aggregates_materials():
    rows = [
        {"wonum": "WO1", "itemnum": "M1", "material_name": "轴承", "work_ticket_code": "T1", "work_ticket_status": "已许可"},
        {"wonum": "WO1", "itemnum": "M2", "material_name": "润滑脂", "work_ticket_code": "T1", "work_ticket_status": "已许可"},
    ]
    with patch.object(app, "_execute", return_value=rows):
        result = app.get_workorder_detail("WO1")
    assert len(result["data"]["materials"]) == 2
    assert len(result["data"]["work_tickets"]) == 1
