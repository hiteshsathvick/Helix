.PHONY: up down logs test test-frontend test-e2e migrate lint seed

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

test:
	docker compose run --rm api pytest

test-frontend:
	docker compose run --rm frontend npm test

# Needs the full stack up first (`make up`, in another terminal) — unlike
# test/test-frontend, Playwright drives a real browser against the running
# app + api, not an isolated container.
test-e2e:
	cd frontend && npm run test:e2e

migrate:
	docker compose run --rm api alembic upgrade head

lint:
	docker compose run --rm api ruff check .
	docker compose run --rm api mypy app
	docker compose run --rm frontend npm run lint
	docker compose run --rm frontend npx tsc --noEmit

seed:
	@echo "Phase 0: no seed script yet (comes with the orgs/documents phases)."
