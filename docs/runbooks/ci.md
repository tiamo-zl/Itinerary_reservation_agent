# Runbook: CI

## 本地等价 CI

```bash
make ci
```

展开为：

```bash
make lint
make typecheck
make test
make eval
```

`make test` 需要 `TEST_DATABASE_URL` 指向可用的 PostgreSQL 测试库。

## 当前仓库状态

- 主仓库在 Gitee
- GitHub 镜像：https://github.com/tiamo-zl/Itinerary_reservation_agent
- GitHub Actions 已实际运行通过：
  https://github.com/tiamo-zl/Itinerary_reservation_agent/actions/runs/41438354389
- 后端 job：lint / mypy / migrate / pytest / eval 全部通过
- 前端 job：构建通过

Gitee Go 为可选；如需要，可在 Gitee 配置同等流水线。

## Gitee Go 最小步骤

在 Gitee 仓库启用 Gitee Go 后，流水线至少执行：

```text
安装 uv
uv sync --dev --frozen
uv run ruff check src tests
uv run mypy（CI 范围）
uv run pytest（需要 PostgreSQL 测试库）
PYTHONPATH=src uv run python -m itinerary_agent.eval.cli
```

注意：

- 测试需要 PostgreSQL；Gitee Go 没有数据库服务时，只能跑 lint/typecheck/eval。
- 完整测试建议在 GitHub Actions 或独立 CI runner 上运行。
- 前端构建不是必选，当前前端加固已移出范围。

## 需要人工完成

- 在 Gitee 仓库设置中启用 Gitee Go；
- 配置 PostgreSQL 测试库（或只启用静态检查 + eval）；
- 如需镜像扫描，在 CI 中安装 trivy 或使用 Docker Scout 登录凭据。

## 安全扫描

```bash
make audit
```

需要：

```bash
uv tool install pip-audit
brew install trivy
# 或 docker login
```
