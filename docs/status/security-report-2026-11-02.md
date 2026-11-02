# 依赖与镜像安全报告（2026-11-02）

## 结论

| 范围 | 工具 | 结果 |
|---|---|---|
| Python 依赖 | pip-audit | ✅ 未发现已知漏洞 |
| 前端生产依赖 | `npm audit --omit=dev` | ✅ 0 vulnerabilities |
| 前端全部依赖 | `npm audit` | 🟡 7 moderate（全部 dev） |
| 容器镜像 | Trivy（Docker 运行） | ✅ **0 HIGH/CRITICAL**（修复前 43） |
| 应用安全回归 | pytest | ✅ 安全用例通过 |

## 镜像 CVE 修复

### 修复前

`itinerary-reservation-agent:local` 基于 `python:3.13-slim-bookworm`：

```text
OS packages: 38 (HIGH: 36, CRITICAL: 2)
Python packages: 5 HIGH
合计: 43 HIGH/CRITICAL
```

OS 主要是 Debian 12 的 `util-linux`、`sqlite3`、`zlib`、`gzip`、
`libsystemd`、`ncurses`、`perl-base` 等，均无可用修复版本：

| 包 | 数量 | 说明 |
|---|---|---|
| `util-linux` 家族 | 27 | `mount`/`blkid`/`libmount`/`uuid` 等，3 个 CVE |
| `libsqlite3-0` | 4 | 含 1 CRITICAL |
| `ncurses` | 4 | — |
| `zlib1g` | 1 | CRITICAL |
| `libsystemd0` / `libudev1` | 2 | — |
| `gzip` / `libacl1` / `perl-base` | 3 | — |

Python 的 5 个 HIGH 全部来自基础镜像自带 **pip 的 vendored 包**，
不是应用 venv：

| 包 | pip vendored 版本 | 修复版本 |
|---|---|---|
| msgpack | 1.1.2 | 1.2.3 |
| setuptools | 70.3.0 | 78.1.1 |
| urllib3 | 2.7.0 | 2.8.0 |

应用 venv 实际已是 `urllib3==2.8.0`，且不包含 msgpack/setuptools。

### 修复措施

1. **运行镜像改用 Alpine**
   - builder：`ghcr.io/astral-sh/uv:python3.13-alpine`
   - runtime：`python:3.13-alpine`
   - Alpine 基础镜像扫描时 OS 层为 0 HIGH/CRITICAL。
2. **最终镜像移除系统 pip**
   - 应用依赖全部在 builder 的 `.venv` 中，运行期不需要 pip。
   - 同时消除了 5 个 pip vendored CVE。
3. **移除未使用的 SQLite 依赖**
   - `aiosqlite`、`langgraph-checkpoint-sqlite` 已无运行时引用；
   - 顺带移除 `sqlite-vec`（没有 musllinux wheel，会阻塞 Alpine 构建）；
   - 运行时仍使用 PostgreSQL checkpointer。
4. **补充原生 wheel 运行库**
   - `apk add libstdc++`，供 PyMuPDF/gRPC 等原生扩展使用。

### 修复后

```text
Trivy: 0 HIGH/CRITICAL
镜像大小: 554MB → 478MB
```

运行验证：

- API `/readyz`：database / redis / checkpointer 全部 `ok`
- worker `/readyz`：outbox / retention / business_metrics / quality_eval / judge 全部 `ok`
- 脚本化聊天 smoke：`COMPLETED`
- 镜像内 `fitz`、`psycopg`、`grpc`、`pymilvus`、`uvicorn`、`alembic` 导入正常

### 评估过但未采用

| 方案 | 结果 | 结论 |
|---|---|---|
| `python:3.13-slim-trixie` | 50（45 HIGH + 5 Python，0 CRITICAL） | HIGH 数量高于 bookworm，无明确收益 |
| Debian slim + 移除 pip | 38 OS HIGH/CRITICAL | 仍有 2 个 CRITICAL，且无修复版本 |
| Alpine | 0 OS CVE | 采用 |

## 构建说明

本机 Docker Desktop 访问 `files.pythonhosted.org` 的大文件时会出现明显降速，
本次验证使用临时镜像源构建；提交的 `Dockerfile` 与 `uv.lock` 不包含镜像源，
CI 或正常网络直接 `docker build` 即可。

如果本地构建 `uv sync` 长时间停在 `Downloading ...`，可临时把构建上下文中的
`uv.lock` 里的 `https://files.pythonhosted.org` 替换为可达的 PyPI 镜像后再构建。

## 容器镜像扫描命令

`make audit` 会优先使用本机 trivy；没有时使用本地
`aquasec/trivy:latest` 镜像：

```bash
docker pull aquasec/trivy:latest
make audit
```

脚本默认使用 `ghcr.io/aquasecurity/trivy-db:2`（匿名可拉），
并把 DB 缓存在 `trivy-cache` volume，避免每次重复下载。

单独扫描：

```bash
docker run --rm \
  -e TRIVY_DB_REPOSITORY=ghcr.io/aquasecurity/trivy-db:2 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v trivy-cache:/root/.cache/trivy \
  aquasec/trivy:latest image --severity HIGH,CRITICAL \
  --timeout 15m --no-progress itinerary-reservation-agent:local
```

## 应用安全回归

已通过：

- `tests/test_security.py`
- `tests/test_auth.py`
- `tests/test_pii.py`
- `tests/test_api_hardening.py`

覆盖 SQL 注入、path 注入、租户隔离、JWT 头伪造、PII 脱敏、CORS、SSE 归属。

## 后续

1. 将镜像构建 + Trivy HIGH/CRITICAL 门禁接入 CI。
2. 定期重建基础镜像（建议每周或每月），跟踪 Alpine 新 CVE。
3. 前端 7 个 dev moderate 保持现状；升级 `vue-tsc` 时统一处理。
4. 生产环境可增加镜像签名、SBOM 与供应链证明。
