# Runbook: 压测、混沌与安全

## 1. k6 压测

### 安装

```bash
brew install k6
k6 version
```

若 Homebrew 不在 PATH：

```bash
export PATH="/usr/local/bin:$PATH"
```

### 场景

```bash
make load-smoke VUS=5 DURATION=30s
make load-chat VUS=10 DURATION=30s
make load VUS=20 RAMP=20s HOLD=1m
```

直接运行：

```bash
k6 run load/k6/smoke.js
k6 run -e VUS=20 -e DURATION=1m load/k6/chat.js
k6 run -e BASE_URL=http://127.0.0.1:8000 -e VUS=50 load/k6/mixed.js
```

默认入口是 Higress `http://127.0.0.1:8081`。

### 阶梯

```text
20 VUs × 2m
50 VUs × 2m
100 VUs × 2m
```

每档记录：

- RPS、P50/P95/P99、错误率
- API/worker CPU、内存
- PostgreSQL 连接数、慢查询
- Redis 错误
- model fallback / circuit 状态
- SSE 连接数
- outbox 积压

结果写入 `docs/status/load-report-<date>.md`。

## 2. Toxiproxy 混沌

Toxiproxy 位于 mock-deps 前面，用于注入延迟和断连。

```bash
make chaos-up
./scripts/chaos/toxiproxy.sh setup
```

让 API 走代理：

```bash
ADAPTER_MODE=http MOCK_DEPS_URL=http://toxiproxy:19003 \
  docker compose --profile core --profile chaos up -d \
  api worker mock-deps toxiproxy
```

注入延迟：

```bash
./scripts/chaos/toxiproxy.sh latency 2000
```

模拟依赖不可用：

```bash
./scripts/chaos/toxiproxy.sh down
# 恢复
./scripts/chaos/toxiproxy.sh up
```

清理：

```bash
./scripts/chaos/toxiproxy.sh reset
```

观察点：

- `itinerary_tool_calls_total{code="UPSTREAM_TIMEOUT"}`
- `itinerary_tool_calls_total{code="UPSTREAM_UNAVAILABLE"}`
- API 是否返回 5xx，还是按工具降级进入人工处理
- 请求延迟是否在 adapter timeout 后收敛

## 3. 基础混沌脚本

```bash
./scripts/chaos/run.sh pg
./scripts/chaos/run.sh redis
APPROVAL_ID=<id> TASK_ID=<id> ./scripts/chaos/run.sh worker
TASK_ID=<id> ./scripts/chaos/run.sh concurrent-resume
```

预期：

| 场景 | 预期 |
|---|---|
| `pg` | `/healthz=200`、`/readyz=503`，恢复后 `/readyz=200` |
| `redis` | `/healthz=200`、`/readyz=503`，恢复后 `/readyz=200` |
| `worker` | 停机时审批保持 `WAITING_APPROVAL`；启动后恢复 `WAITING_HUMAN` |
| `concurrent-resume` | 一个请求完成，另一个收到 `TASK_BUSY` |

脚本退出时会尝试 `start postgres redis worker`。

### 生成 worker 场景数据

```bash
make demo-seed ARGS="--adapter-mode http"
```

把输出的 `APPROVAL_ID`、`TASK_ID` 传给脚本。

## 4. 安全测试

```bash
uv run pytest -q tests/test_security.py
```

覆盖：

- SQL 注入字符串按普通文本存储，查询不中断
- 注入 payload 作为 path 参数返回 404，不出现 500
- 跨租户任务/会话读取 403
- JWT 模式下伪造 `X-Mock-User` 仍返回 401
- 反馈中的手机号被脱敏

已有覆盖：

- `tests/test_auth.py`：过期 token、错误 issuer、scope
- `tests/test_pii.py`：文本与嵌套对象脱敏
- `tests/test_api_hardening.py`：CORS、SSE 头、归属校验

建议后续补充：

- 依赖审计与镜像扫描：`make audit`（见 `docs/status/security-report-2026-11-02.md`）
- prompt injection 红队用例
- 限流绕过（JWT 身份稳定后）

## 5. 本轮结果

已执行：

- `pg`：通过
- `redis`：通过
- `worker`：通过
- `concurrent-resume`：通过
- Toxiproxy：proxy 创建、100ms 延迟注入、清除均通过
- `tests/test_security.py`：4 passed

待执行：

- k6 阶梯压测（本机 k6 尚未安装）
- Toxiproxy 与应用端到端降级（需要重启 API 指向 toxiproxy）
- 依赖/镜像扫描
