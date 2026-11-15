.PHONY: dev-up dev-down check test test-live lint
dev-up:    ## database, pooler and redis for local development and tests
	docker compose up -d --build db pgbouncer redis
dev-down:
	docker compose down
lint:
	cd backend && uv run ruff format --check -q . && uv run ruff check .
test:      ## everything except tests that call a real model
	cd backend && RUN_LIVE=0 uv run pytest -q
test-live: ## tests that call a real model through the gateway in ../.env.local
	cd backend && uv run pytest -q -m live
check: lint test
