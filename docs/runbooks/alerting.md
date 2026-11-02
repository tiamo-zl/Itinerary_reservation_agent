# Runbook: 告警通知（Alertmanager + 邮件）

## 架构

```text
Prometheus 规则
    │ firing / resolved
    ▼
Alertmanager（分组、抑制、静默、路由）
    │ email
    ▼
SMTP（本地 Mailpit；生产为真实邮件服务器）
```

告警规则与发送方式解耦：

- Prometheus 只负责检测。
- Alertmanager 按 `severity` 路由到不同 receiver。
- 邮件模板只负责格式化，不包含业务规则。
- 以后接企业微信/钉钉，只需要把 receiver 的 `email_configs`
  换成 `webhook_configs`，或增加一个 relay；规则和路由标签不变。

## 组件与端口

| 组件 | 地址 | 说明 |
|---|---|---|
| Prometheus | http://127.0.0.1:19090 | 规则与告警源 |
| Alertmanager | http://127.0.0.1:19093 | 路由、分组、抑制、静默 |
| Mailpit SMTP | 127.0.0.1:1025 | 本地测试邮件接收 |
| Mailpit UI | http://127.0.0.1:8025 | 查看捕获的邮件 |

共享栈文件：

```text
/Users/lll/yuxiu/work_address_for_soft/docker/conf/monitoring-stack/
  docker-compose.yml
  prometheus/prometheus.yml
  prometheus/alerts.yml
  alertmanager/alertmanager.yml
  alertmanager/email.tmpl
```

仓库源文件：

```text
deploy/alertmanager/alertmanager.yml
deploy/alertmanager/email.tmpl
deploy/prometheus/alerts.yml
```

修改后需要同步到共享栈并重启对应容器。

## 严重级别与路由

| severity | 邮件收件人 | 重复提醒 | 典型告警 |
|---|---|---|---|
| critical | `oncall@itinerary.local` | 1h | ServiceDown、SLOBurnFast、AlertmanagerDown |
| warning | `team@itinerary.local` | 4h | 5xx、P95、fallback、熔断、outbox、工具错误、慢燃烧、审批恢复、完成率、badcase |
| info | `digest@itinerary.local` | 24h | 限流 |
| none | `platform@itinerary.local` | 24h | Watchdog 心跳 |

邮件主题包含状态和级别：

```text
[FIRING][CRITICAL] ItineraryServiceDown
[RESOLVED][WARNING] ItineraryHighLatency
[FIRING][NONE] Watchdog
```

正文包含：

- 告警名、状态、开始时间
- service / severity
- summary / description
- `runbook_url`
- Prometheus `GeneratorURL`

## 共享栈改动

`monitoring-stack/docker-compose.yml` 新增：

```yaml
  alertmanager:
    image: prom/alertmanager:v0.34.2
    container_name: alertmanager
    restart: unless-stopped
    command:
      - --config.file=/etc/alertmanager/alertmanager.yml
      - --storage.path=/alertmanager
      - --web.external-url=http://127.0.0.1:19093
    ports:
      - "127.0.0.1:19093:9093"
    volumes:
      - ./alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
      - ./alertmanager/email.tmpl:/etc/alertmanager/templates/email.tmpl:ro
      - alertmanager-data:/alertmanager
    depends_on:
      - mailpit
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:9093/-/healthy"]
      interval: 15s
      timeout: 5s
      retries: 5
    networks: [monitoring]

  mailpit:
    image: axllent/mailpit:latest
    container_name: mailpit
    restart: unless-stopped
    environment:
      - MP_MAX_MESSAGES=500
    ports:
      - "127.0.0.1:1025:1025"
      - "127.0.0.1:8025:8025"
    networks: [monitoring]
```

并新增 volume：

```yaml
volumes:
  alertmanager-data:
```

`monitoring-stack/prometheus/prometheus.yml` 新增：

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]

scrape_configs:
  # ...
  - job_name: alertmanager
    static_configs:
      - targets: ["alertmanager:9093"]
```

Prometheus 的 `--web.external-url` 需要指向收件人可访问的地址，
否则邮件里的 Prometheus 链接会显示容器主机名。

## 本地验证

以下步骤使用 `alertmanager.mailpit.yml`（收件人为 `oncall/team/digest/platform@itinerary.local`）。
如果共享栈当前已切换到 163，先按“回退到 Mailpit”替换配置。

### 1. 启动

```bash
cd /Users/lll/yuxiu/work_address_for_soft/docker/conf/monitoring-stack
docker compose up -d mailpit alertmanager
docker compose up -d prometheus   # 重载 alerting 配置
```

检查：

```bash
curl -s http://127.0.0.1:19093/-/healthy
curl -s http://127.0.0.1:8025/
curl -s http://127.0.0.1:19090/api/v1/targets
```

Prometheus 中应有 `alertmanager` target 为 `up`。

### 2. 配置检查

```bash
docker exec alertmanager amtool check-config \
  /etc/alertmanager/alertmanager.yml
```

预期：

```text
SUCCESS
 - 4 receivers
 - 2 inhibit rules
 - 1 templates
```

### 3. 注入测试告警

```bash
for spec in "RouteCritical critical" "RouteWarning warning" "RouteInfo info"; do
  set -A parts ${=spec}
  docker exec alertmanager amtool alert add "${parts[1]}" \
    severity="${parts[2]}" service=itinerary-agent \
    --annotation=summary="route-${parts[2]}" \
    --annotation=description="severity-routing-test" \
    --annotation=runbook_url="https://github.com/tiamo-zl/Itinerary_reservation_agent/blob/main/docs/runbooks/alerting.md" \
    --alertmanager.url=http://localhost:9093 --no-version-check
done
```

等待 `group_wait`（30s）后打开 Mailpit：

- critical → `oncall@itinerary.local`
- warning → `team@itinerary.local`
- info → `digest@itinerary.local`

测试完成后重启 Alertmanager 清除 API 注入的告警：

```bash
docker restart alertmanager
```

### 4. Watchdog

`Watchdog` 永远 firing，用来验证整条链路：

```text
Prometheus 规则 → Alertmanager → SMTP → 邮箱
```

如果长期收不到 Watchdog 邮件，说明告警链路本身坏了。
首次部署或清空 Alertmanager 数据后，它会在 `group_wait` 后发送一封；
之后按 `repeat_interval`（24h）重复。

## 邮箱配置

仓库里保留两套 Alertmanager 配置：

| 文件 | 用途 |
|---|---|
| `deploy/alertmanager/alertmanager.yml` | 163 真实邮箱 |
| `deploy/alertmanager/alertmanager.mailpit.yml` | 本地 Mailpit 演示 |

### 163 邮箱

当前 163 配置：

```yaml
smtp_smarthost: 'smtp.163.com:25'
smtp_from: 'your-account@163.com'
smtp_auth_username: 'your-account@163.com'
smtp_auth_password_file: '/etc/alertmanager/secrets/smtp_password'
smtp_require_tls: true
```

所有级别默认都发到 `your-account@163.com`，主题保留
`[CRITICAL]` / `[WARNING]` / `[INFO]` 区分。

> 仓库中的邮箱地址是占位符；真实发件地址、收件人和授权码只放在
> 共享栈的 `alertmanager.yml` 与 `secrets/smtp_password` 中，不提交到仓库。

注意：

- 163 需要在“设置 -> POP3/SMTP/IMAP”中开启 SMTP 服务并生成**授权码**；
  授权码不是邮箱登录密码。
- `smtp.163.com:25` 支持 STARTTLS，Alertmanager 的 `smtp_require_tls: true`
  可用。
- `smtp.163.com:465` 是隐式 TLS，Alertmanager 不支持；如必须用 465，
  需要本地 SMTP relay。
- 部分网络会封锁出站 25 端口；如果容器内无法连接，改用 relay 或 587
  （163 当前未在 587 提供 STARTTLS）。

### 写入授权码

共享栈的 secret 目录：

```text
/Users/lll/yuxiu/work_address_for_soft/docker/conf/monitoring-stack/alertmanager/secrets/
```

在终端中执行（不要通过聊天发送授权码）：

```bash
read -rsp "163 SMTP 授权码: " CODE; echo
printf '%s' "$CODE" > /Users/lll/yuxiu/work_address_for_soft/docker/conf/monitoring-stack/alertmanager/secrets/smtp_password
chmod 600 /Users/lll/yuxiu/work_address_for_soft/docker/conf/monitoring-stack/alertmanager/secrets/smtp_password
unset CODE
```

目录权限为 `700`，文件权限为 `600`，授权码不要提交到仓库。

### 切换到 163

仓库里的 `alertmanager.yml` 是模板，地址是占位符。首次部署时复制到共享栈，
然后把 `your-account@163.com` 换成真实地址（`smtp_from`、`smtp_auth_username`
和 4 个 `to`），再重启：

```bash
cp deploy/alertmanager/alertmanager.yml \
  /Users/lll/yuxiu/work_address_for_soft/docker/conf/monitoring-stack/alertmanager/alertmanager.yml

# 编辑共享栈配置，替换占位地址
$EDITOR /Users/lll/yuxiu/work_address_for_soft/docker/conf/monitoring-stack/alertmanager/alertmanager.yml

cd /Users/lll/yuxiu/work_address_for_soft/docker/conf/monitoring-stack
docker compose up -d alertmanager
```

之后只维护共享栈里的那一份配置，不要再用模板覆盖它。

### 验证投递

```bash
docker logs --tail 50 alertmanager | grep -iE 'notify|error|smtp'
curl -s http://127.0.0.1:19093/metrics \
  | grep -E 'alertmanager_notifications_(total|failed_total)'
```

预期：

- `alertmanager_notifications_total{integration="email"}` 增长
- `alertmanager_notifications_failed_total{integration="email"}` 不增长
- 163 收件箱收到测试告警

如果出现 `535 Authentication failed`：

1. 确认授权码不是登录密码；
2. 确认 `smtp_auth_username` 与 `smtp_from` 都是 `your-account@163.com`；
3. 确认 163 已开启 SMTP 服务；
4. 重新生成授权码后再试。

### 回退到 Mailpit

先备份共享栈里已经填好真实地址的 163 配置，再替换：

```bash
cp /Users/lll/yuxiu/work_address_for_soft/docker/conf/monitoring-stack/alertmanager/alertmanager.yml \
  /Users/lll/yuxiu/work_address_for_soft/docker/conf/monitoring-stack/alertmanager/alertmanager.163.local.yml

cp deploy/alertmanager/alertmanager.mailpit.yml \
  /Users/lll/yuxiu/work_address_for_soft/docker/conf/monitoring-stack/alertmanager/alertmanager.yml

cd /Users/lll/yuxiu/work_address_for_soft/docker/conf/monitoring-stack
docker compose up -d alertmanager
```

> Alertmanager 配置不支持环境变量插值。生产环境的 SMTP 凭据和收件人
> 应放在共享栈配置或 secret 文件中，不要写进仓库。

## 以后接企业微信/钉钉

保持以下内容不变：

- Prometheus 规则
- `severity`、`service`、`slo` 标签
- Alertmanager 的 route 结构
- 抑制规则和静默

只改 receiver：

```yaml
receivers:
  - name: 'im-critical'
    webhook_configs:
      - url: 'http://alert-relay:8080/notify/critical'
        send_resolved: true
```

迁移期可以同时保留邮件和 IM：

```yaml
- matchers: ['severity="critical"']
  receiver: 'email-critical'
  continue: true
- matchers: ['severity="critical"']
  receiver: 'im-critical'
```

relay 负责：

- 企业微信/钉钉/飞书消息格式
- 签名与 token
- 渠道限流与重试
- 把 `runbook_url`、Grafana/Tempo 链接放进消息

因此未来改造只需要增加 relay 和 receiver，不需要改检测规则。

## 抑制与静默

- `ItineraryServiceDown` 会抑制同一 service 的其它告警，避免故障刷屏。
- `ItinerarySLOBurnFast` 会抑制同一 SLO 的 `ItinerarySLOBurnSlow`。
- Watchdog 永远不被抑制。
- 发布/维护窗口使用 Alertmanager silence，不要直接删规则。

## 已知限制

1. 当前是单 Alertmanager，没有集群 HA；生产建议 3 副本 + gossip。
2. 邮件是唯一渠道；SMTP 故障时告警可能静默丢失。
   生产应增加 IM/电话或外部 dead-man's switch。
3. Mailpit 只用于本地验证，生产必须切换到真实 SMTP。
4. Alertmanager 配置不支持环境变量，凭据通过 secret 文件挂载。
5. Prometheus 的 `GeneratorURL` 依赖 `--web.external-url`；
   生产要改成可被收件人访问的地址。

## 排障

### 没有收到邮件

```bash
curl -s http://127.0.0.1:19090/api/v1/targets | jq
curl -s http://127.0.0.1:19093/api/v2/alerts | jq
docker logs --tail 50 alertmanager
docker logs --tail 50 mailpit
```

检查：

- `up{job="alertmanager"}` 是否为 1
- Alertmanager 中告警是否为 active
- `alertmanager_notifications_failed_total` 是否增长
- SMTP 主机/端口/认证/收件人
- 邮件是否进入垃圾箱

### 配置或模板错误

```bash
docker exec alertmanager amtool check-config \
  /etc/alertmanager/alertmanager.yml
```

### 告警重复或缺失

- 检查 `group_wait`、`group_interval`、`repeat_interval`
- 检查 inhibition 规则是否误抑制
- 检查 notification log（Alertmanager 持久化 volume）

### 告警风暴

- 缩小 `group_by` 维度，避免按 instance 分组
- 增加 inhibition
- 降级非可执行告警
- 定期评审告警数量和误报率
