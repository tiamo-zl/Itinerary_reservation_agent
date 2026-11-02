# 压测报告（2026-11-01）

## 环境

- 入口：Higress `http://127.0.0.1:8081`
- API：`ADAPTER_MODE=http`、`MODEL_MODE=scripted`、`AUTH_MODE=mock`
- 运行镜像：早于最新模型网关改动（当前 API/worker 镜像）
- 负载工具：k6 v2.3.0
- 说明：chat 场景使用脚本化模型，不代表 live 模型延迟

## 只读路径阶梯

`load/k6/read.js`，10s ramp + 30s hold：

| VUs | 请求数 | RPS | 失败率 | P50 | P95 | Max |
|---:|---:|---:|---:|---:|---:|---:|
| 20 | 3,831 | 76.3 | 0% | 7.4ms | 27.5ms | 109ms |
| 50 | 8,602 | 171.9 | 0% | 24.2ms | 89.3ms | 238ms |
| 100 | 13,191 | 263.7 | 0% | 102.7ms | 206.8ms | 340ms |

结论：

- 只读路径线性扩展良好，100 VU 仍无错误
- P95 从 27ms 增长到 207ms，主要来自 trace/task 聚合查询
- 瓶颈优先级：PostgreSQL 连接池/聚合查询 > API 进程

## Chat / SSE 阶梯

`load/k6/chat.js`，30s：

| VUs | 请求数 | RPS | 失败率 | P50 | P95 | Max | 说明 |
|---:|---:|---:|---:|---:|---:|---:|---|
| 5 | 48 | 4.4 | 37.5% | 137ms | 203ms | 207ms | 限流开启，18 个 429 |
| 10 | 265 | 8.6 | 0% | 151ms | 321ms | 385ms | 限流关闭 |
| 50 | 636 | 20.4 | 0% | 1.42s | 1.87s | 1.97s | 限流关闭 |
| 100 | 836 | 26.8 | 0% | 2.72s | 3.15s | 3.34s | 限流关闭 |

结论：

- 限流按设计生效：5 VUs / 10s 即触发 37.5% 的 429
- 关闭限流后，chat 在 100 VU 无错误，但 P95 达到 3.1s
- chat 的单轮成本明显高于只读查询：任务索引、Checkpoint、span 投影、消息写入
- 100 VU 下吞吐未线性增长（26.8 RPS vs 50 VU 的 20.4 RPS），说明写路径开始成为瓶颈

## 混沌

已执行并通过：

| 场景 | 结果 |
|---|---|
| 停 PostgreSQL | `/healthz=200`、`/readyz=503`，恢复后 200 |
| 停 Redis | `/healthz=200`、`/readyz=503`，恢复后 200 |
| worker 停机 | 审批保持 `WAITING_APPROVAL`，启动后恢复 `WAITING_HUMAN` |
| 并发 resume | 一个完成，另一个 `TASK_BUSY` |
| Toxiproxy 100ms 延迟 | proxy 注入/清除正常 |

待执行：

- Toxiproxy 应用端到端（API 指向 `toxiproxy:19003` 后注入 2s/6s 延迟）
- 依赖/镜像扫描（pip-audit / Trivy）

## 安全

`tests/test_security.py` 4 条通过：

- SQL 注入字符串按普通文本存储
- path 注入返回 404
- 跨租户任务/会话 403
- JWT 模式忽略伪造 `X-Mock-User`
- 反馈手机号脱敏

## 原始数据

`load/results/*.json`

## 建议

1. P2 引入 PgBouncer，并评估 `database_pool_max`。
2. 关注 Checkpoint / span 投影写入对 chat 延迟的影响。
3. 压测环境关闭限流仅用于容量测试；生产必须保留。
4. 下一轮压测在最新镜像和 live 模型模式分别执行。
