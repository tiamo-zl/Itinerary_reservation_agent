# API/worker 共用镜像；worker 在 compose 里覆盖启动命令。
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# 先只复制依赖清单，最大化 Docker 层缓存。
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN useradd --create-home --uid 10001 app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src
COPY --chown=app:app config ./config
COPY --chown=app:app alembic.ini ./

USER app

EXPOSE 8000 8001

CMD ["uvicorn", "--app-dir", "src", "itinerary_agent.main:app", \
     "--host", "0.0.0.0", "--port", "8000"]
