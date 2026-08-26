.PHONY: up down logs migrate revision db-roles seed backfill seed-history test check smoke fmt shell psql \
        prod-build prod-up prod-down prod-migrate prod-db-roles prod-seed prod-logs prod-ps prod-psql \
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

db-roles:  ## krok 44: nadaj roli `portfel_app` hasło z DATABASE_URL_APP (po `make migrate`)
	docker compose exec api python -m app.cli db-roles

seed:
	docker compose exec api python -m app.cli seed

# Etap 8, krok zerowy. `from`, `years`, `to` i `provider` nadpisywalne:
#   make backfill years=2
#   make backfill from=2021-01-01 to=2024-12-31
#   make backfill provider=yfinance          <- zalecane dla historii
#
# `provider=` przypina wszystkie okna do jednego dostawcy. Bez tego fallback
# rozstrzyga się per okno i potrafi zszyć w jedną serię dwie niekompatybilne
# konwencje `close_adj` (yfinance koryguje o dywidendy/splity, Stooq nie).
#
# `date -d` jest GNU-owe — na macOS/BSD trzeba podać `from=` wprost.
years    ?= 5
from     ?= $(shell date -d "$(years) years ago" +%Y-%m-%d)
to       ?=
provider ?=

backfill:  ## dev: zaciągnij historię cen i kursów (domyślnie 5 lat wstecz)
	docker compose exec api python -m app.cli backfill-prices --from $(from) \
		$(if $(to),--to $(to),) $(if $(provider),--provider $(provider),)

# Osobno od `backfill` celowo: najpierw oglądasz, co się zaciągnęło, dopiero
# potem liczysz na tym wyceny. Historia jest SYNTETYCZNA (dzisiejszy skład
# wyceniony cenami z przeszłości) i komenda odmawia działania poza ENV=dev.
seed-history:  ## TYLKO DEV: odtwórz portfolio_valuations wstecz dla metryk etapu 8
	docker compose exec api python -m app.cli seed-history --from $(from) $(if $(to),--to $(to),)

test:
	docker compose exec api pytest -q -m "not network"

check:     ## bramka jakości — musi być zielona przed „gotowe"
	docker compose exec api ruff format --check .
	docker compose exec api ruff check .
	docker compose exec api mypy app
	docker compose exec api pytest -q -m "not network"
	cd frontend && npm run lint && npx tsc --noEmit && npm run test && npm run build

# Świadomie POZA `make check` (krok 39): wymaga żywego stacku, a `check` musi
# dać się uruchomić także tam, gdzie stoi sam kod (CI, świeży klon). Domyślnie
# celuje w dev (`http://localhost:3000`); po wdrożeniu przepuszczasz ten sam
# plik przez produkcję:
#
#   E2E_BASE_URL=https://alphasense.cedron.net.pl make smoke
#
# UWAGA: przebieg zakłada w bazie KONTO (`smoke-…@alphasense.example`) wraz
# z portfelem i pozycją. Na produkcji posprzątaj po sobie — `docs/wdrozenie.md` §10.
smoke:     ## smoke test Fazy 1 na ŻYWYM stacku: 375 px + desktop
	cd frontend && npx playwright test e2e/smoke.spec.ts

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

prod-db-roles: ## prod: hasło dla roli aplikacji (krok 44) — PO `make prod-migrate`, przed restartem API
	$(PROD) run --rm --no-deps api python -m app.cli db-roles

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
