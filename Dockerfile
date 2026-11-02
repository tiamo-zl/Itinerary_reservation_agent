# API/worker 共用镜像；worker 在 compose 里覆盖启动命令。
#
# 最终镜像使用 Alpine：2026-11-02 扫描时 OS 层无 HIGH/CRITICAL，
# Debian slim 基础镜像有 38 个（2 CRITICAL）且多数无修复版本。
# 基础镜像自带的 pip 会携带 vendored msgpack/urllib3/setuptools，
# 应用运行不需要 pip，因此最终阶段直接移除。
FROM ghcr.io/astral-sh/uv:python3.13-alpine AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# 先只复制依赖清单，最大化 Docker 层缓存。
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.13-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# libstdc++ 供原生 wheel 使用；移除 pip 减少镜像面与 vendored CVE。
RUN apk add --no-cache libstdc++ \
 && addgroup -g 10001 app \
 && adduser -D -u 10001 -G app -H -s /sbin/nologin app \
 && rm -rf /usr/local/lib/python3.13/site-packages/pip \
           /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 \
 && rm -rf /var/cache/apk/*

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src
COPY --chown=app:app config ./config
COPY --chown=app:app alembic.ini ./

USER app

EXPOSE 8000 8001

CMD ["uvicorn", "--app-dir", "src", "itinerary_agent.main:app", \
     "--host", "0.0.0.0", "--port", "8000"]
