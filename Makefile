.PHONY: up down logs test migrate lint seed

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

test:
	docker compose run --rm api pytest

migrate:
	docker compose run --rm api alembic upgrade head

lint:
	docker compose run --rm api ruff check .
	docker compose run --rm api mypy app
	docker compose run --rm frontend npm run lint

seed:
	@echo "Phase 0: no seed script yet (comes with the orgs/documents phases)."
