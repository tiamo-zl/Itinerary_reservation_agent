DATABASE_URL ?= postgresql://itinerary:itinerary_dev@127.0.0.1:55432/itinerary
TEST_DATABASE_URL ?= postgresql://itinerary:itinerary_dev@127.0.0.1:55432/itinerary_test

.PHONY: db-up db-down db-logs migrate revision api worker test lint typecheck web-build smoke

# 只启动 P0 需要的基础设施，不构建应用镜像。
db-up:
	docker compose --profile core up -d postgres redis

db-down:
	docker compose --profile core down

db-logs:
	docker compose logs -f postgres redis

migrate:
	DATABASE_URL=$(DATABASE_URL) uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "$(m)"

api:
	uv run uvicorn --app-dir src itinerary_agent.main:app --reload --host 127.0.0.1 --port 8000

worker:
	uv run uvicorn --app-dir src itinerary_agent.workers.main:app --reload --host 127.0.0.1 --port 8001

test:
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest -q

lint:
	uv run ruff check src tests

typecheck:
	uv run mypy src

web-build:
	npm --prefix web run build

smoke:
	curl -fsS http://127.0.0.1:8000/healthz
