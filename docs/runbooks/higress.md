# Runbook: Higress 网关

## 架构

本机已有 Higress all-in-one；项目用它作为统一入口，不再依赖 Web 容器的
Nginx 作为唯一入口。

```text
Browser
  │  :8081
  ▼
Higress (higress-ai)
  ├── /                 → web.local:80   （Vue 静态资源）
  ├── /chat,/tasks,...  → api.local:8000 （业务 API / SSE）
  └── /console          → Higress 控制台 landing
```

- 控制台仍可直接访问 `http://127.0.0.1:8002`
- 直连端口保留：Web `8080`、API `8000`、worker `8001`
- McpBridge 使用 DNS registry；`api.local` / `web.local` 是 Compose 网络别名

## 启动

先启动 core，再应用网关配置：

```bash
docker compose --profile core up -d
make higress-up
```

`make higress-up` 会：

1. 把 `higress-ai` 接入项目 Docker 网络（别名 `higress-edge`）；
2. 备份现有 `/Users/lll/higress/{mcpbridges,ingresses,configmaps}`；
3. 写入 `deploy/higress/` 下的 McpBridge 与 Ingress；
4. 首次把 `dnsRefreshRate` 从 200s 调到 10s 并重启 Higress；
5. 冒烟 `/healthz` 与 `/index.html`。

可用环境变量覆盖：

| 变量 | 默认值 |
|---|---|
| `HIGRESS_CONTAINER` | `higress-ai` |
| `HIGRESS_DATA_DIR` | `/Users/lll/higress` |
| `HIGRESS_NETWORK` | `itinerary-reservation-agent_default` |
| `HIGRESS_HTTP_PORT` | `8081` |

## 路由文件

仓库内模板：

```text
deploy/higress/
  mcpbridge-default.yaml   # api.local / web.local / higress-console
  ingress-api.yaml         # /chat、/tasks、/traces、...
  ingress-web.yaml         # / 与静态资源
  ingress-console.yaml     # /console
```

修改后重新执行 `make higress-up`。

## 验证

```bash
curl -fsS http://127.0.0.1:8081/healthz
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8081/index.html
curl -N -X POST http://127.0.0.1:8081/chat \
  -H 'Content-Type: application/json' \
  -H 'X-Mock-User: u001' \
  -d '{"message":"下周二去北京"}'
```

浏览器入口：<http://127.0.0.1:8081>

## 故障排查

### 网关 503

- 确认 `api`/`web` 容器在项目网络里：
  `docker inspect itinerary-reservation-agent-api-1 --format '{{json .NetworkSettings.Networks}}'`
- 从 Higress 容器解析：
  `docker exec higress-ai python3 -c "import socket; print(socket.gethostbyname('api.local'))"`
- API 容器重建后 IP 会变；等待 `dnsRefreshRate=10s` 刷新，或执行
  `make higress-up` 重新应用配置。

### SSE 被缓冲/断开

- `/chat` 与 `/tasks/*` 直接路由到 API，不经过 Web Nginx；
- API 已设置 `X-Accel-Buffering: no` 和 15s 心跳；
- 确认请求没有被外部代理（如公司代理）缓冲。

### 控制台入口

- 网关 `/console` 只保留 landing；
- 完整控制台使用 <http://127.0.0.1:8002>。
