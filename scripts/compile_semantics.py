"""Validate the pinned Ossie model and compile deterministic runtime artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import pprint
import re
from pathlib import Path

import jsonschema
import sqlglot
import yaml


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "semantic" / "power_operations.ossie.yaml"
SCHEMA_PATH = ROOT / "semantic" / "vendor" / "ossie-0.2.0.dev0-schema.json"
EXTENSION_SCHEMA_PATH = ROOT / "semantic" / "vendor" / "tonghai-extensions.schema.json"
REGISTRY_PATH = ROOT / "generated" / "semantic_registry.py"
CATALOG_PATH = ROOT / "generated" / "tool_catalog.json"
CONTEXT_PATH = ROOT / "generated" / "dify_semantic_context.md"
DATABASE_CONTRACT_PATH = ROOT / "generated" / "database_contract.json"
EXPECTED_VERSION = "0.2.0.dev0"
BANNED_SQL = re.compile(r"(;|--|/\*|\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|REVOKE)\b)", re.I)


def ansi_expression(item: dict) -> str:
    dialects = item["expression"]["dialects"]
    matches = [entry["expression"] for entry in dialects if entry["dialect"] == "ANSI_SQL"]
    if len(matches) != 1:
        raise ValueError(f"{item['name']} 必须且只能有一个 ANSI_SQL 表达式")
    expression = matches[0].strip()
    if BANNED_SQL.search(expression):
        raise ValueError(f"{item['name']} 含禁止的 SQL 语句或分隔符")
    sqlglot.parse_one(expression)
    return expression


def extension(model: dict, vendor: str) -> dict:
    matches = [item for item in model.get("custom_extensions", []) if item["vendor_name"] == vendor]
    if len(matches) != 1:
        raise ValueError(f"模型必须且只能包含一个 {vendor} 扩展")
    value = json.loads(matches[0]["data"])
    if not isinstance(value, dict):
        raise ValueError(f"{vendor} 扩展必须是 JSON object")
    return value


def compile_model() -> tuple[str, str, str, str]:
    # Git may materialize text files with CRLF on Windows and LF on Linux.
    # Normalize line endings before parsing and hashing so generated artifacts
    # remain deterministic across developer workstations and CI runners.
    raw = MODEL_PATH.read_bytes().replace(b"\r\n", b"\n")
    data = yaml.safe_load(raw)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(data)
    if data["version"] != EXPECTED_VERSION:
        raise ValueError(f"Ossie 版本必须固定为 {EXPECTED_VERSION}")
    if len(data["semantic_model"]) != 1:
        raise ValueError("当前服务必须使用一个统一 semantic_model")

    model = data["semantic_model"][0]
    datasets: dict[str, dict] = {}
    field_labels: dict[str, str] = {}
    for dataset in model["datasets"]:
        fields = {field["name"]: ansi_expression(field) for field in dataset.get("fields", [])}
        if len(fields) != len(dataset.get("fields", [])):
            raise ValueError(f"数据集 {dataset['name']} 存在重复字段")
        missing_keys = set(dataset.get("primary_key", [])) - set(fields)
        if missing_keys:
            raise ValueError(f"数据集 {dataset['name']} 主键字段不存在: {sorted(missing_keys)}")
        datasets[dataset["name"]] = {
            "source": dataset["source"].split(".")[-1],
            "qualified_source": dataset["source"],
            "primary_key": dataset.get("primary_key", []),
            "fields": fields,
            "description": dataset.get("description", ""),
            "ai_context": dataset.get("ai_context", {}),
        }
        for field in dataset.get("fields", []):
            if field.get("label"):
                field_labels[field["name"]] = field["label"]

    if set(datasets) != {"defect", "workorder"}:
        raise ValueError("当前模型必须包含 defect 和 workorder 两个数据集")

    metrics = {
        metric["name"]: {
            "expression": ansi_expression(metric),
            "description": metric.get("description", ""),
            "ai_context": metric.get("ai_context", {}),
        }
        for metric in model.get("metrics", [])
    }
    if len(metrics) != len(model.get("metrics", [])):
        raise ValueError("存在重复指标名称")
    required_metrics = {
        "defect_count", "open_defect_count", "closed_defect_count",
        "workorder_count", "closed_workorder_count", "open_workorder_count",
        "overdue_workorder_count", "workorder_closure_rate",
    }
    missing_metrics = required_metrics - set(metrics)
    if missing_metrics:
        raise ValueError(f"缺少 MCP 运行所需指标: {sorted(missing_metrics)}")

    policy = extension(model, "TONGHAI_POWER_OPS")
    tool_extension = extension(model, "TONGHAI_MCP")
    extension_schema = json.loads(EXTENSION_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(extension_schema).validate(
        {"power_ops": policy, "mcp": tool_extension}
    )
    tools = tool_extension.get("tools", {})
    if not tools:
        raise ValueError("MCP 工具目录不能为空")
    for tool_name, tool in tools.items():
        if not tool.get("label") or not tool.get("domains") or not tool.get("intents"):
            raise ValueError(f"工具 {tool_name} 必须声明 label、domains 和 intents")
    intent_owners: dict[str, str] = {}
    for tool_name, tool in tools.items():
        for intent in tool["intents"]:
            previous = intent_owners.setdefault(intent, tool_name)
            if previous != tool_name:
                raise ValueError(f"意图 {intent} 同时映射到 {previous} 和 {tool_name}")

    closed_statuses = policy.get("closed_statuses", [])
    if not closed_statuses:
        raise ValueError("closed_statuses 不能为空")
    for metric_name in ("open_defect_count", "open_workorder_count", "overdue_workorder_count"):
        expression = metrics[metric_name]["expression"]
        missing_statuses = [status for status in closed_statuses if f"'{status}'" not in expression]
        if missing_statuses:
            raise ValueError(f"指标 {metric_name} 未覆盖关闭状态: {missing_statuses}")

    # Every configured dimension must resolve to a declared field.
    for domain in ("defect", "workorder"):
        fields = set(datasets[domain]["fields"])
        invalid = set(policy["dimensions"][domain].values()) - fields
        if invalid:
            raise ValueError(f"{domain} 维度引用未声明字段: {sorted(invalid)}")
    invalid_failure = set(policy["dimensions"]["failure"].values()) - set(datasets["workorder"]["fields"])
    if invalid_failure:
        raise ValueError(f"故障维度引用未声明字段: {sorted(invalid_failure)}")

    fingerprint = hashlib.sha256(raw).hexdigest()
    registry = {
        "OSSIE_VERSION": data["version"],
        "SEMANTIC_FINGERPRINT": fingerprint,
        "MODEL_NAME": model["name"],
        "MODEL_AI_CONTEXT": model.get("ai_context", {}),
        "DATASETS": datasets,
        "METRICS": metrics,
        "CLOSED_STATUSES": tuple(policy["closed_statuses"]),
        "FAST_SOURCES": policy["fast_sources"],
        "EQUIPMENT_SOURCES": policy["equipment_sources"],
        "DIMENSIONS": policy["dimensions"],
        "DATA_BOUNDARIES": policy["data_boundaries"],
        "DATABASE_SCHEMA_VERSION": policy["schema_version"],
        "FIELD_LABELS": field_labels,
        "TOOL_CATALOG": tools,
    }
    lines = [
        '"""Generated from semantic/power_operations.ossie.yaml; do not edit."""',
        "",
    ]
    for key, value in registry.items():
        lines.append(f"{key} = {pprint.pformat(value, sort_dicts=True, width=110)}")
        lines.append("")
    registry_text = "\n".join(lines)
    catalog_text = json.dumps(
        {"ossie_version": data["version"], "semantic_fingerprint": fingerprint, "tools": tools},
        ensure_ascii=False, indent=2, sort_keys=True,
    ) + "\n"
    context = model.get("ai_context", {})
    context_text = "\n".join([
        "# 火电运维统一语义上下文",
        "",
        f"Ossie version: `{data['version']}`",
        f"Semantic fingerprint: `{fingerprint}`",
        "",
        "## 使用边界",
        "",
        str(context.get("instructions", "")),
        "",
        "## 规范问题示例",
        "",
        *[f"- {item}" for item in context.get("examples", [])],
        "",
    ])
    database_contract_text = json.dumps(
        {
            "schema_version": policy["schema_version"],
            "views": {
                datasets["defect"]["source"]: sorted(datasets["defect"]["fields"]),
                policy["fast_sources"]["defect"]: sorted(datasets["defect"]["fields"]),
                datasets["workorder"]["source"]: sorted(datasets["workorder"]["fields"]),
                policy["fast_sources"]["workorder"]: sorted(datasets["workorder"]["fields"]),
                policy["equipment_sources"]["defect"]: [
                    "asset_code", "equipment_name", "kks_code", "location_name", "specialty_name"
                ],
                policy["equipment_sources"]["workorder"]: [
                    "asset_code", "equipment_name", "kks_code", "kks_name", "specialty_name"
                ],
            },
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    return registry_text, catalog_text, context_text, database_contract_text


def write_or_check(check: bool) -> None:
    outputs = dict(zip(
        (REGISTRY_PATH, CATALOG_PATH, CONTEXT_PATH, DATABASE_CONTRACT_PATH),
        compile_model(),
    ))
    if check:
        stale = [str(path.relative_to(ROOT)) for path, content in outputs.items()
                 if not path.exists() or path.read_text(encoding="utf-8") != content]
        if stale:
            raise SystemExit("生成产物已漂移，请重新编译: " + ", ".join(stale))
        print("Ossie semantic artifacts are current")
        return
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"generated: {path.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    write_or_check(args.check)


if __name__ == "__main__":
    main()
