# 火电缺陷智能分析 MCP

本服务根据“火电-缺陷智能分析”Dify Chatflow 的查询口径编排，向 Dify 提供固定、参数化、只读的设备与缺陷查询工具。它不接受自由 SQL，不提交缺陷单或工单。

## 新增的缺陷分析工具

1. `parse_kks_code`：灵活解析长短 KKS。
2. `resolve_defect_equipment`：按完整 KKS 查询设备主数据。
3. `get_current_equipment_defects`：当前设备/当前KKS范围全量统计、分页明细。
4. `get_same_system_defects`：按 `system_kks` 查询同系统缺陷，排除当前主设备。
5. `get_same_type_defects`：按 `system_class_code + equipment_class_code` 查询同类型缺陷，排除当前主设备。
6. `get_defect_analysis_statistics`：一次返回当前设备、同系统、同类型的全量统计。

原项目的设备、缺陷、工单和运维统计工具继续保留。

## 全量数据口径

- 所有数量均使用 `sqldemo3.dwd_defect_dedup_physical` 的全部匹配记录统计。
- 明细不做静默截断，采用 `page + page_size` 分页返回。
- `page_size` 最大为 500。响应中的 `has_more` 和 `next_page` 表示是否还有后续数据。
- 连续请求 `next_page` 可以取得全部明细，同时避免 Dify 变量超过 400000 字符或模型上下文溢出。
- 物理表无可靠缺陷发生时间，因此明细只按 `defect_code` 稳定分页，不解释为时间顺序。

## 数据库要求

运行账号至少需要以下对象的 `SELECT` 权限：

- `dwd_defect_dedup_physical`
- `mcp_defect_current`
- `vw_qa_workorder_equipment_mcp`
- 原项目 `generated/database_contract.json` 中列出的视图
- `mcp_schema_version`

推荐使用只读数据库账号。数据库密码和 MCP Token 只能放在 `.env`，不得写入代码或 Dify 提示词。

## 本地启动

```powershell
Copy-Item .env.example .env
# 编辑 .env，配置数据库和认证信息
uv sync --extra test
uv run pytest
uv run python app.py
```

默认 Streamable HTTP 端点是：

```text
http://<MCP_HOST>:<MCP_PORT>/mcp
```

健康检查：

- `/health/live`
- `/health/ready`
- `/metrics`

## Dify 推荐调用方式

```text
用户Query
  → 意图识别/动态分析策略
  → parse_kks_code
  → resolve_defect_equipment
  → 根据策略选择以下一个或多个工具
      get_current_equipment_defects
      get_same_system_defects
      get_same_type_defects
  → 汇总统计及必要分页明细
  → 大模型生成动态Markdown分析报告
```

如果用户只要求统计，优先调用 `get_defect_analysis_statistics`，不要读取全部明细。
