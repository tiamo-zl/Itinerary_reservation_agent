# 依赖与镜像安全报告（2026-11-02）

## 结论

| 范围 | 工具 | 结果 |
|---|---|---|
| Python 依赖 | pip-audit | ✅ 未发现已知漏洞 |
| 前端生产依赖 | `npm audit --omit=dev` | ✅ 0 vulnerabilities |
| 前端全部依赖 | `npm audit` | 🟡 7 moderate（全部 dev） |
| 容器镜像 | Trivy（Docker 运行） | 🔴 43 HIGH/CRITICAL |
| 应用安全回归 | pytest | ✅ 安全用例通过 |

## 前端依赖

生产依赖：

```text
found 0 vulnerabilities
```

全部依赖：

```text
7 moderate severity vulnerabilities
```

来源：

- `glob` / `minimatch`（通过 `vue-tsc`、`@vue/test-utils` 的 dev 依赖链）
- `npm audit fix --force` 会升级到破坏性版本，暂不自动修复
- 前端加固已移出当前范围；7 个问题不影响生产构建运行时

建议：

1. 不执行 `npm audit fix --force`。
2. 如移除前端测试依赖：
   ```bash
   cd web
   npm uninstall -D vitest @vue/test-utils jsdom @vitest/coverage-v8 @playwright/test
   ```
   仍会保留 `vue-tsc` 的 dev 告警。
3. 后续升级 `vue-tsc` 时统一处理。

## Python 依赖

`pip-audit` 结果：

```text
No known vulnerabilities found
```

## 容器镜像

使用 Trivy Docker 镜像扫描 `itinerary-reservation-agent:local`：

```text
OS packages: 38 (HIGH: 36, CRITICAL: 2)
Python packages: 5 HIGH
```

OS 主要是 Debian 12 基础镜像的 `util-linux`、`sqlite3`、`zlib`、
`gzip`、`libsystemd` 等，多数当前没有修复版本。

Python 包可修复：

| 包 | 当前 | 修复 |
|---|---|---|
| msgpack | 1.1.2 | 1.2.3 |
| setuptools | 70.3.0 | 78.1.1 |
| urllib3 | 2.7.0 | 2.8.0 |

建议由你执行：

```bash
uv lock --upgrade-package msgpack --upgrade-package urllib3 --upgrade-package setuptools
uv sync
```

然后重建镜像并重新扫描。OS 漏洞建议在 P2 升级基础镜像（例如 Debian trixie）
或建立定期重建策略。

## 容器镜像扫描命令

`make audit` 会优先使用本机 trivy；没有时使用本地
`aquasec/trivy:latest` 镜像：

```bash
docker pull aquasec/trivy:latest
make audit
```

Trivy DB 默认使用 `public.ecr.aws/aquasecurity/trivy-db:2`，
不需要 Docker Hub 登录。

## 应用安全回归

已通过：

- `tests/test_security.py`
- `tests/test_auth.py`
- `tests/test_pii.py`
- `tests/test_api_hardening.py`

覆盖 SQL 注入、path 注入、租户隔离、JWT 头伪造、PII 脱敏、CORS、SSE 归属。

## 待办

1. 升级 msgpack / urllib3 / setuptools 并重建镜像。
2. P2 升级基础镜像或建立定期重建策略，处理 Debian OS 漏洞。
3. 把 `make audit` 接入 CI，对 high/critical 设置门禁。
