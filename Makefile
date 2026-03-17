.PHONY: setup dev dev-infra dev-py dev-js build test lint clean

# ─── Setup ──────────────────────────────────────────
setup: setup-js setup-py setup-infra
	@echo "SoulForge development environment ready"

setup-js:
	pnpm install

setup-py:
	uv sync

setup-infra:
	docker compose up -d postgres redis milvus minio
	@echo "Waiting for services..."
	@sleep 5
	pnpm run db:migrate

# ─── Development ────────────────────────────────────
dev-infra:
	docker compose up -d postgres redis milvus minio

dev-ai:
	uv run --package ai-core -- uvicorn ai_core.main:app --reload --port 8100

dev-gw:
	uv run --package gateway -- uvicorn gateway.main:app --reload --port 8080

dev-admin:
	pnpm --filter @soulforge/admin-web dev

dev: dev-infra
	@echo "Starting all services..."
	$(MAKE) -j3 dev-ai dev-gw dev-admin

# ─── Build ──────────────────────────────────────────
build-js:
	pnpm run build

# ─── Test ───────────────────────────────────────────
test: test-js test-py

test-js:
	pnpm run test

test-py:
	uv run pytest packages/ai-core/tests packages/gateway/tests

# ─── Lint ───────────────────────────────────────────
lint: lint-js lint-py

lint-js:
	pnpm run lint

lint-py:
	uv run ruff check packages/ai-core packages/gateway
	uv run ruff format --check packages/ai-core packages/gateway

# ─── Database ───────────────────────────────────────
db-migrate:
	pnpm run db:migrate

db-generate:
	pnpm run db:generate

db-seed:
	pnpm run db:seed

db-studio:
	pnpm --filter @soulforge/database exec prisma studio

# ─── Clean ──────────────────────────────────────────
clean:
	docker compose down -v
	rm -rf node_modules apps/*/node_modules packages/*/node_modules
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
