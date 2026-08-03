from unittest.mock import patch

import app


def test_parse_complete_equipment_kks():
    value = app._parse_analysis_kks("L0BLD01GE017")
    assert value["valid"] is True
    assert value["system_kks"] == "L0BLD01"
    assert value["equipment_kks"] == "L0BLD01GE017"
    assert value["system_class_code"] == "BLD"
    assert value["equipment_class_code"] == "GE"


def test_parse_short_kks_is_supported():
    value = app._parse_analysis_kks("10")
    assert value["valid"] is True
    assert value["level"] == "PLANT_SYSTEM_PREFIX"
    assert value["current_scope_kks"] == "10"
    assert value["system_kks"] == ""


def test_analysis_page_has_a_safe_maximum():
    assert app._analysis_page(0, 9999) == (1, 500, 0)
    assert app._analysis_page(3, 100) == (3, 100, 200)


@patch("app._execute")
def test_current_equipment_uses_indexed_equipment_kks(execute):
    execute.side_effect = [
        [{"total_defect_count": 1, "involved_kks_count": 1}],
        [{"defect_code": "D1", "kks_code": "L0BLD01GE017"}],
    ]
    result = app.get_current_equipment_defects("L0BLD01GE017", 1, 100)
    assert result["summary"]["total_defect_count"] == 1
    assert result["pagination"]["has_more"] is False
    assert "equipment_kks = %s" in execute.call_args_list[0].args[1]


@patch("app._execute")
def test_same_type_uses_both_classification_codes(execute):
    execute.side_effect = [
        [{"total_defect_count": 4, "involved_kks_count": 3}],
        [],
    ]
    result = app.get_same_type_defects("L0BLD01GE017", 1, 20)
    assert result["summary"]["total_defect_count"] == 4
    sql = execute.call_args_list[0].args[1]
    assert "system_class_code = %s" in sql
    assert "equipment_class_code = %s" in sql

