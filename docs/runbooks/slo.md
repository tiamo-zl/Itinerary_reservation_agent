# Runbook: SLO 与燃烧率告警

## SLO

当前目标：

```text
可用性 99.5% / 28 天
错误预算 = 0.5%
```

只统计业务请求，排除：

```text
/healthz
/readyz
/metrics
```

## 记录规则

`deploy/prometheus/alerts.yml` 中的 `itinerary-slo-recording`：

| 记录指标 | 含义 |
|---|---|
| `itinerary:slo_availability:ratio5m` | 5 分钟可用性 |
| `itinerary:slo_availability:ratio1h` | 1 小时可用性 |
| `itinerary:slo_availability:ratio6h` | 6 小时可用性 |
| `itinerary:slo_availability:ratio30m` | 30 分钟可用性 |
| `itinerary:slo_burn_rate:5m` | 5 分钟燃烧率 |
| `itinerary:slo_burn_rate:1h` | 1 小时燃烧率 |
| `itinerary:slo_burn_rate:6h` | 6 小时燃烧率 |
| `itinerary:slo_burn_rate:30m` | 30 分钟燃烧率 |
| `itinerary:slo_http_p95:5m` | HTTP P95 |
| `itinerary:slo_approval_recovery_p95:10m` | 审批恢复 P95 |

燃烧率公式：

```text
(1 - availability) / (1 - 0.995)
```

## 告警

| 告警 | 条件 | 级别 |
|---|---|---|
| `ItinerarySLOBurnFast` | 1h > 14.4 且 5m > 14.4 | critical |
| `ItinerarySLOBurnSlow` | 6h > 6 且 30m > 6 | warning |
| `ItineraryApprovalRecoverySlow` | 恢复 P95 > 10s | warning |
| `ItineraryTaskCompletionLow` | 完成率 < 95% | warning |
| `ItineraryBadcaseRateHigh` | 每千任务 badcase > 50 | warning |

快速燃烧需要同时满足 1h 和 5m，避免单点抖动误报。
所有可用性燃烧告警都要求最近 5 分钟有业务流量，空闲时不会误报。

## 验证

```bash
curl -s -G http://127.0.0.1:19090/api/v1/query \
  --data-urlencode 'query=itinerary:slo_availability:ratio5m'

curl -s -G http://127.0.0.1:19090/api/v1/query \
  --data-urlencode 'query=itinerary:slo_burn_rate:5m'
```

查看规则和状态：

```bash
curl -s http://127.0.0.1:19090/api/v1/rules
curl -s http://127.0.0.1:19090/api/v1/alerts
```

Grafana：

- `Itinerary Service Health` 看板
  - SLO availability
  - 1h/6h 燃烧率
  - 错误预算燃烧曲线
  - 审批恢复 P95

## 通知渠道

已采用 **Prometheus Alertmanager**：

```text
Prometheus SLO 告警 → Alertmanager 19093 → 邮件
```

- `critical`：快速燃烧 → `oncall@itinerary.local`，1 小时重复
- `warning`：慢速燃烧 → `team@itinerary.local`，4 小时重复
- 本地邮件由 Mailpit（http://127.0.0.1:8025）捕获
- 已配置抑制：快速燃烧抑制同一 SLO 的慢速燃烧
- 未来接企业微信/钉钉只需替换 receiver 的发送方式，
  SLO 规则和路由标签不变

详见 `docs/runbooks/alerting.md`。

## 排查

### SLO 指标为空

- 最近 5 分钟没有业务请求时，`ratio5m` 可能为空；
- 访问几次 `/traces` 或 `/chat` 后再查询；
- 检查 Prometheus 是否能抓到 `itinerary-api` / `itinerary-worker`。

### 燃烧率很高但系统正常

- 检查是否只有少量请求且其中一条 5xx；
- 低流量下比率波动大，告警已加最小流量门槛；
- 关注 1h/6h 窗口，而不是只看 5m。

### 审批恢复 P95 为空

- 还没有审批恢复样本；
- 触发一次“审批通过 → worker 恢复”后再查询；
- 检查 `itinerary_approval_recovery_seconds_bucket`。
