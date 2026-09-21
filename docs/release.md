# 发布约定

本文档规定 `power-ops-mcp` 的版本、检查和 GitHub Release 流程。当前仓库没有自动
发布工作流，因此发布由仓库维护者按本约定手动完成。

## 版本与变更记录

- 版本号以 `pyproject.toml` 的 `[project].version` 为准。
- 使用 `MAJOR.MINOR.PATCH` 版本格式，并使用 `vMAJOR.MINOR.PATCH` 作为 Git tag。
- 用户可见的功能、修复、兼容性变化和数据库迁移必须先在 `CHANGELOG.md` 的对应
  版本条目中记录。
- 版本号和更新日志在同一个 Pull Request 中修改；PR 目标为 `main`，不得直接推送
  或强推 `main`。
- 尚未形成正式版本的变化写入 `[未发布]`，不要在没有实际发布内容时伪造历史版本
  条目。

## 发布前检查

合并版本 PR 前，至少执行与 `main` 分支 CI 一致的检查：

```powershell
uv sync --extra test --frozen
uv lock --check
uv run python scripts/compile_semantics.py --check
uv run python -m py_compile app.py runtime/*.py
uv run pytest -q tests
```

如果本次发布涉及数据库迁移、视图、索引或性能，还要补充目标数据库上的迁移结果、
`EXPLAIN`、`scripts/check_database.py` 或基准脚本证据；离线测试不能替代生产数据库
验证。发布包或 Release 说明中不得包含凭据、Token、生产查询结果或生产日志。

## 发布步骤

1. 从 `main` 创建版本 PR，更新 `pyproject.toml` 版本号和 `CHANGELOG.md`。
2. 等待 PR 检查通过，并完成代码、架构边界和敏感信息审查后合并。
3. 在已合并的 `main` 提交上创建对应的 `vMAJOR.MINOR.PATCH` tag，并推送该 tag；
   不修改或覆盖已有 tag。
4. 基于该 tag 创建 GitHub Release，标题使用版本号，正文引用
   `CHANGELOG.md` 中对应版本条目，并明确数据库迁移、配置变化和已知限制。
5. 发布后确认 Release、tag 和 `pyproject.toml` 版本一致；如发现问题，按补丁版本
   发布修复，不回写已发布版本。

## 回滚边界

发布回滚不得通过删除或覆盖 tag 伪造历史。应用代码回滚、数据库迁移回滚和配置回滚
必须分别评估；如果迁移不可逆，应先停止发布并保留证据，由维护者制定前向修复方案。
