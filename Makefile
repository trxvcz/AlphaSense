.PHONY: up down logs migrate revision seed test check fmt shell psql \
        prod-build prod-up prod-down prod-migrate prod-seed prod-logs prod-ps prod-psql \
        backup backup-check backup-restore-test

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

# --- produkcja (krok 36) ----------------------------------------------------
#
# Każdy cel przechodzi przez `$(PROD)`, bo `--env-file .env.prod` NIE jest
# opcjonalny: `${ZMIENNA}` w `docker-compose.prod.yml` podstawia compose po
# stronie hosta i domyślnie czyta do tego `.env`, nie `.env.prod`. Bez tego
# flagi na VPS-ie wyjdzie puste hasło Postgresa, a lokalnie po cichu wejdą
# ustawienia deweloperskie. Pełna procedura: `docs/wdrozenie.md`.

PROD = docker compose --env-file .env.prod -f docker-compose.prod.yml

prod-build:   ## prod: zbuduj obrazy (NEXT_PUBLIC_* są wypiekane właśnie tutaj)
	$(PROD) build

prod-up:      ## prod: podnieś stack (migracje lecą jako usługa `migrate` przed API)
	$(PROD) up -d

prod-down:
	$(PROD) down

prod-migrate: ## prod: migracje poza cyklem `up` (np. po samej zmianie schematu)
	$(PROD) run --rm migrate

prod-seed:    ## prod: słownik rynków i indeksy — BEZ danych demo; potem restart workera
	$(PROD) run --rm --no-deps api python -m app.cli seed --reference-only
	$(PROD) restart worker

prod-logs:    ## make prod-logs s=worker
	$(PROD) logs -f $(s)

prod-ps:
	$(PROD) ps

prod-psql:
	$(PROD) exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

# --- backup (krok 38) -------------------------------------------------------
#
# Bez `$(PROD)`: skrypty same składają wywołanie compose'a z `--env-file
# .env.prod` (`infra/backup/common.sh`), bo muszą działać także spod crona,
# gdzie `make` nie uczestniczy. Te cele są wygodą przy ręcznym przebiegu —
# harmonogram jedzie z `infra/backup/alphasense-backup.cron`.

backup-check:         ## prod: sprawdź bucket i klucz przed pierwszym backupem
	./infra/backup/check-bucket.sh

backup:               ## prod: jednorazowy dump + wysyłka do bucketu (to samo, co cron)
	./infra/backup/backup.sh

backup-restore-test:  ## prod: odtwórz ostatnią kopię do jednorazowej bazy i sprawdź ją
	./infra/backup/restore-test.sh
