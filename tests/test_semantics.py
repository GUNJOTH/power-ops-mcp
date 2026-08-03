from pathlib import Path
import subprocess
import sys

from app import MCP, TOOL_CATALOG
from generated import semantic_registry


ROOT = Path(__file__).resolve().parents[1]


def test_generated_semantics_are_current():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "compile_semantics.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_ossie_tool_catalog_matches_registered_mcp_tools():
    registered = {tool.name for tool in MCP._tool_manager.list_tools()}
    assert registered == set(TOOL_CATALOG)


def test_database_migration_matches_generated_contract():
    migration_1 = (ROOT / "database" / "migrations" / "2026.07.31.1__runtime_contract_upgrade.sql").read_text(
        encoding="utf-8"
    )
    assert "2026.07.31.1" in migration_1
    # New FAST_SOURCES view is in the new migration
    new_migration = (ROOT / "database" / "migrations" / "2026.08.03.1__unify_english_field_names.sql").read_text(
        encoding="utf-8"
    )
    assert f"VIEW `{semantic_registry.FAST_SOURCES['workorder']}`" in new_migration
    assert f"VIEW `{semantic_registry.DATASETS['workorder']['source']}`" in new_migration
    assert "CREATE TABLE IF NOT EXISTS `mcp_schema_version`" in migration_1
    equipment_migration = (
        ROOT / "database" / "migrations" / "2026.07.31.2__equipment_lookup_views.sql"
    ).read_text(encoding="utf-8")
    assert "2026.07.31.2" in equipment_migration
    for view in semantic_registry.EQUIPMENT_SOURCES.values():
        if view.startswith("vw_qa_"):
            # New MCP equipment views are in the new migration
            if view.endswith("_mcp"):
                assert f"VIEW `{view}`" in new_migration
            else:
                assert f"VIEW `{view}`" in equipment_migration
    snapshot_migration = (
        ROOT / "database" / "migrations" / "2026.07.31.3__defect_snapshot_contract.sql"
    ).read_text(encoding="utf-8")
    assert "2026.07.31.3" in snapshot_migration
    # DATABASE_SCHEMA_VERSION "2026.08.03.1" is in the new migration
    assert semantic_registry.DATABASE_SCHEMA_VERSION in new_migration
