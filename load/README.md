# k6 压测

前置：

```bash
brew install k6
k6 version
```

默认入口是 Higress：`http://127.0.0.1:8081`。也可以直接打 API：
`BASE_URL=http://127.0.0.1:8000`。

## 场景

| 脚本 | 内容 |
|---|---|
| `k6/smoke.js` | `/healthz` 基线 |
| `k6/chat.js` | 对话 SSE，带 mock 用户 |
| `k6/mixed.js` | health / trace / approval / chat 混合流量 |

## 运行

```bash
# 通过 Makefile
make load-smoke
make load VUS=20 DURATION=1m
make load-chat VUS=10 DURATION=30s

# 直接
k6 run load/k6/smoke.js
k6 run -e VUS=20 -e DURATION=1m load/k6/chat.js
k6 run -e BASE_URL=http://127.0.0.1:8000 -e VUS=50 load/k6/mixed.js
```

`mixed.js` 使用 ramping VUs：

```bash
k6 run -e VUS=100 -e RAMP=30s -e HOLD=2m load/k6/mixed.js
```

## 阈值

- `http_req_failed < 5%`
- `http_req_duration p(95) < 3s`
- `smoke` 更严格：失败率 <1%，P95 <1s

脚本化模型模式下 `/chat` 很快；live 模式会受模型延迟影响，建议单独看
`chat` 的阈值。

## 建议阶梯

```text
20 VUs × 2m
50 VUs × 2m
100 VUs × 2m
```

每档记录：

- RPS
- P50 / P95 / P99
- 错误率
- CPU / 内存
- PostgreSQL 连接数
- Redis 错误
- model fallback / circuit 状态
- SSE 连接数

压测结果写入 `docs/status/load-report-<date>.md`。
