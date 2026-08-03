## 变更说明

<!-- 写明解决的问题、影响的工具或模块。 -->

## 架构影响

- [ ] 未改变 MCP 的只读、固定参数化查询边界
- [ ] 未引入自由 SQL 或原始表直连写入
- [ ] 若修改 `semantic/`，已重新生成并提交 `generated/`
- [ ] 若修改工具契约，已说明 Dify/调用方兼容性
- [ ] 若修改数据库，已新增迁移且未改写历史迁移

## 验证

- [ ] `uv run python scripts/compile_semantics.py --check`
- [ ] `uv run pytest -q tests`
- [ ] 如涉及数据库：已附上 `EXPLAIN`、迁移或基准证据

## 安全检查

- [ ] 未提交 `.env`、凭据、Token、生产结果或生产日志
