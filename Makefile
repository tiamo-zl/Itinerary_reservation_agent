DATABASE_URL ?= postgresql://itinerary:itinerary_dev@127.0.0.1:55432/itinerary
TEST_DATABASE_URL ?= postgresql://itinerary:itinerary_dev@127.0.0.1:55432/itinerary_test
VUS ?= 5
DURATION ?= 30s
RAMP ?= 20s
HOLD ?= 60s

.PHONY: db-up db-down db-logs migrate revision api worker idp obs-up obs-down higress-up higress-down demo-seed knowledge-ingest knowledge-reindex knowledge-check badcase-export chaos-up chaos-down load-smoke load-chat load-read load audit ci test eval eval-holdout lint typecheck web-build smoke

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

idp:
	uv run uvicorn --app-dir src itinerary_agent.mock_services.identity:app --reload --host 127.0.0.1 --port 9002

obs-up:
	./scripts/up-observability.sh

obs-down:
	docker compose --profile observability down

test:
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest -q

eval:
	PYTHONPATH=src uv run python -m itinerary_agent.eval.cli

eval-holdout:
	PYTHONPATH=src uv run python -m itinerary_agent.eval.cli --split holdout

judge-calibrate:
	PYTHONPATH=src uv run python -m itinerary_agent.eval.judge_calibration

lint:
	uv run ruff check src tests

demo-seed:
	PYTHONPATH=src uv run python scripts/seed_demo_task.py $(ARGS)

knowledge-ingest:
	PYTHONPATH=src uv run python -m itinerary_agent.knowledge.cli ingest \
		--fixture config/policies/docs/demo-travel-policy.json $(ARGS)

knowledge-reindex:
	PYTHONPATH=src uv run python -m itinerary_agent.knowledge.cli reindex $(ARGS)

knowledge-check:
	PYTHONPATH=src uv run python -m itinerary_agent.knowledge.cli check --json $(ARGS)

badcase-export:
	PYTHONPATH=src uv run python -m itinerary_agent.eval.badcase_export $(ARGS)

chaos-up:
	docker compose --profile chaos up -d toxiproxy

chaos-down:
	docker compose stop toxiproxy

load-smoke:
	@command -v k6 >/dev/null || (echo "k6 not found: brew install k6"; exit 1)
	k6 run -e VUS=$(VUS) -e DURATION=$(DURATION) load/k6/smoke.js

load-chat:
	@command -v k6 >/dev/null || (echo "k6 not found: brew install k6"; exit 1)
	k6 run -e VUS=$(VUS) -e DURATION=$(DURATION) load/k6/chat.js

load-read:
	@command -v k6 >/dev/null || (echo "k6 not found: brew install k6"; exit 1)
	k6 run -e VUS=$(VUS) -e RAMP=$(RAMP) -e HOLD=$(HOLD) load/k6/read.js

load:
	@command -v k6 >/dev/null || (echo "k6 not found: brew install k6"; exit 1)
	k6 run -e VUS=$(VUS) -e RAMP=$(RAMP) -e HOLD=$(HOLD) load/k6/mixed.js

audit:
	./scripts/security_audit.sh

ci: lint typecheck test eval

higress-up:
	./scripts/configure-higress.sh

higress-down:
	docker network disconnect \
		itinerary-reservation-agent_default higress-ai 2>/dev/null || true

typecheck:
	uv run mypy \
		src/itinerary_agent/application \
		src/itinerary_agent/eval \
		src/itinerary_agent/knowledge \
		src/itinerary_agent/security \
		src/itinerary_agent/tools \
		src/itinerary_agent/workers \
		src/itinerary_agent/infra/database.py \
		src/itinerary_agent/infra/repositories

web-build:
	npm --prefix web run build

smoke:
	curl -fsS http://127.0.0.1:8000/healthz
