# MCP 架构与变更边界

本仓库是火电运维问数的生产 MCP 服务。它只提供固定、参数化、只读的业务工具；
不接受自由 SQL，也不承担 Dify 工作流或图表插件的实现。

## 架构图

```text
Dify / MCP Client
        |
        v
app.py  (MCP transport, tool orchestration, response contract)
        |
        +--> generated/  (compiled semantic registry; never edit by hand)
        |        ^
        |        |
        |   semantic/power_operations.ossie.yaml  (single semantic source)
        |
        +--> runtime/  (configuration, security, database pool, metrics)
        |
        v
Governed vw_qa_* views in MySQL
        ^
        |
database/migrations/ and database/materialization/
        |
Raw business tables (read through views only; do not alter from MCP code)
```

## 模块职责

| 模块 | 可以修改什么 | 不应修改什么 |
| --- | --- | --- |
| `semantic/` | 业务字段、维度、指标、工具目录、查询边界 | 手工修改生成文件 |
| `generated/` | 只能由 `scripts/compile_semantics.py` 生成 | 任何手工业务逻辑 |
| `app.py` | 固定工具参数、工具编排、响应结构、参数化查询模板 | 自由 SQL 输入、数据库连接池实现 |
| `runtime/` | 配置校验、鉴权、限流、连接池、可观测性 | 业务工具语义和 Dify 工作流逻辑 |
| `database/migrations/` | 版本化视图、索引、聚合快照契约 | 直接修改原始业务表或删除历史迁移 |
| `scripts/` | 编译、迁移、校验、压测、刷新等受控运维动作 | 启动时隐式执行破坏性数据库操作 |
| `tests/` | 单元、契约、运行时边界测试 | 依赖生产数据或真实凭据 |

## 不可违反的架构规则

1. **Ossie 是唯一语义源。** 调整字段、指标、维度或工具目录时，先改
   `semantic/power_operations.ossie.yaml`，再运行编译脚本；不得直接编辑
   `generated/`。
2. **MCP 只读且无自由 SQL。** 工具不得接收 `sql`、`where_sql`、
   `order_by_sql` 或同等能力的用户输入。所有查询必须固定模板并参数化。
3. **原始表不属于 MCP 变更面。** 新口径先通过受治理的 `vw_qa_*` 视图、
   索引或聚合快照实现；迁移必须可审查、可重复执行。
4. **工具契约优先兼容。** 已发布工具的名称、必填参数、返回字段和业务边界
   不能悄然改变；不兼容调整要新增工具或明确版本迁移方案。
5. **运行时职责下沉。** 鉴权、配置、连接池、超时、并发和指标放在 `runtime/`，
   不在业务工具里复制实现。
6. **Dify 与图表插件是外部消费者。** 本仓库只维护 MCP 契约；工作流和
   `dify-echarts-chart-generator` 各自独立演进。

## 常见变更路径

| 需求 | 正确路径 | 必做验证 |
| --- | --- | --- |
| 新增查询指标或维度 | `semantic/` → 编译产物 → `app.py` 固定工具 | 编译检查、单测、数据库契约检查 |
| 新增 MCP 工具 | 先在 Ossie 工具目录声明，再实现 `app.py` 工具 | 工具目录、参数、响应和测试同步 |
| 查询变慢或超时 | `EXPLAIN` → 索引/聚合快照 → 迁移 | 基准脚本和真实数据库验证 |
| 视图字段变更 | 新增迁移 → 更新语义契约 → 更新工具 | `scripts/check_database.py` 与就绪检查 |
| 鉴权或容量调整 | `runtime/config.py`、`security.py`、`database.py` | 配置测试、拒绝路径和健康检查 |
| Dify 展示改动 | 在 Dify 工作流或图表插件仓库实现 | 不修改 MCP 业务契约，除非另开契约变更 |

## 提交前最小验证

```powershell
uv sync --extra test
uv run python scripts/compile_semantics.py --check
uv run pytest -q tests
```

涉及数据库迁移、视图或性能的变更，还必须在目标数据库执行对应的迁移、
`EXPLAIN`、`scripts/check_database.py` 或基准脚本；本地单测不能替代生产验证。
