# 火电运维问数 MCP

该服务把生产工作流里的自由 SQL 查询替换为 8 个核心工具、2 个业务扩展工具和固定支持工具。Apache Ossie 模型是字段、维度、指标、状态和工具目录的唯一语义源；MCP 只消费经过验证的生成注册表。所有查询均为固定模板和参数化 SQL，不暴露 `sql`、`where_sql`、`order_by_sql` 等自由输入。

## 工具

核心工具：

1. `search_equipment`
2. `search_defects`
3. `get_defect_detail`
4. `summarize_defects`
5. `search_workorders`
6. `get_workorder_detail`
7. `summarize_workorders`
8. `analyze_workorder_failures`

扩展工具：`analyze_workorder_materials`、`get_equipment_operation_summary`。

此外提供 `get_maintenance_dashboard` 和 `get_service_status` 支持工具。前者负责能力导航、数据概况、数据时间边界和澄清消息；后者返回版本、语义指纹和可选数据库就绪状态。业务查询工具仍保持 8+2 的设计。

## 本地虚拟环境

```powershell
uv sync --extra test
uv run pytest
uv run python app.py
```

修改 `semantic/power_operations.ossie.yaml` 后必须重新编译：

```powershell
uv run python scripts/compile_semantics.py
uv run python scripts/compile_semantics.py --check
```

不要直接编辑 `generated/` 下的文件。

本项目统一使用 `uv` 管理 `.venv` 和 `uv.lock`，不要直接运行 `pip install` 或 `python -m venv`。

## 容器启动

先按 [database/README.md](database/README.md) 部署版本化视图，再复制 `.env.example` 为 `.env`，填写只读 MySQL 账号和随机 MCP Token。该账号应只拥有 `mcp_schema_version` 及以下视图的 `SELECT` 权限：

- `vw_qa_defect`
- `vw_qa_defect_fact`
- `vw_qa_work_order`
- `vw_qa_work_order_fact`

然后运行：

```powershell
docker compose -f compose.example.yml up --build
```

默认使用带 Bearer Token、Host/Origin 防护的 Streamable HTTP。Dify 中应配置 `<domain>_mcp_auth_token`，让意图识别节点输出 `tool_name + arguments`，不再输出 SQL。

运行端点：

- `/health/live`：进程存活。
- `/health/ready`：数据库、Schema 版本及视图字段契约。
- `/metrics`：Prometheus 文本指标。

查询层使用有界连接池、并发信号量和 MySQL `MAX_EXECUTION_TIME`；容量耗尽时快速失败，不创建无限排队。

## 数据边界

- 缺陷按 `defect_code` 去重，且没有可靠时间字段。
- 工单按 `workorder_code` 去重；只有计划开始、计划完成时间，没有实际完成时间。
- “超期”仅指计划完成时间早于查询基准时间，且状态不是已关闭、已取消、已作废。
- 单次明细或汇总返回上限为 50。
- 日志只记录工具名、参数数量、耗时和返回条数，不记录密码或结果数据。
