.PHONY: up down logs migrate revision seed test check fmt shell psql

up:        ## dev: postgres, redis, api, frontend, worker
	docker compose up -d --build

down:
	docker compose down

logs:      ## make logs s=worker
	docker compose logs -f $(s)

migrate:
	docker compose exec api alembic upgrade head

revision:  ## make revision m="opis zmiany"
	docker compose exec api alembic revision --autogenerate -m "$(m)"

seed:
	docker compose exec api python -m app.cli seed

test:
	docker compose exec api pytest -q -m "not network"

check:     ## bramka jakości — musi być zielona przed „gotowe"
	docker compose exec api ruff format --check .
	docker compose exec api ruff check .
	docker compose exec api mypy app
	docker compose exec api pytest -q -m "not network"
	cd frontend && npm run lint && npx tsc --noEmit && npm run test && npm run build

fmt:
	docker compose exec api ruff format .
	cd frontend && npm run format

shell:
	docker compose exec api bash

psql:
	docker compose exec postgres psql -U portfel -d portfel
