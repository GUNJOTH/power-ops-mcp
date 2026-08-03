# 贡献规范

先阅读 [架构与变更边界](docs/ARCHITECTURE.md)。所有修改通过分支和 Pull Request
进入 `main`；不要直接推送或强推 `main`。

## 开始开发

```powershell
uv sync --extra test
uv run pytest -q tests
```

不要使用 `pip install`、`python -m venv` 或提交 `.venv`、`.uv-cache`、`.env`。

## 提交规则

- 一个 PR 聚焦一个可审查目标；不要把 MCP、Dify 工作流和图表插件混在同一个 PR。
- 修改 `semantic/` 后，必须运行编译脚本并提交更新后的 `generated/` 产物。
- 不要手工编辑 `generated/`。
- 数据库改动只新增有序迁移；不要重写已经执行过的迁移，也不要在 MCP 中直接改原始表。
- 不提交凭据、Token、生产查询结果、生产日志或 `.env`。
- 变更工具契约时，在 PR 中写明工具名、参数、响应字段、兼容性和 Dify 影响。

## 验证要求

每个 PR 至少通过：

```powershell
uv run python scripts/compile_semantics.py --check
uv run pytest -q tests
```

以下情况需要补充证据：

| 变更类型 | 额外证据 |
| --- | --- |
| SQL、视图、索引、聚合表 | 目标库 `EXPLAIN`、迁移结果与耗时 |
| 鉴权、Host/Origin、配置 | 拒绝路径与启动校验 |
| 新工具或参数 | 成功、空结果、非法参数和上限测试 |
| 响应字段/语义变更 | Dify 消费方兼容性说明 |

## PR 合并标准

`main` 的规则要求 Pull Request。提交人应确保 CI 通过、架构边界未被破坏、
敏感信息未进入差异；仓库所有者负责最终合并。
