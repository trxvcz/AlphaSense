# STATUS — gdzie jesteśmy

> **Claude Code: czytaj ten plik na starcie każdej sesji i aktualizuj na końcu każdego zadania.**
> Jedno źródło prawdy o postępie. Numery kroków = `docs/plan-dzialania-portfel-v2.md`.

**Aktualny etap:** 5 — Pozycje i wycena
**Ostatnia aktualizacja:** 2026-07-24
**Faza:** 1 (etapy 0–7, cel: wpisujesz pozycje → widzisz wartość, skład % i ranking rynków)

## Postęp etapów

| Etap | Zakres | Status |
|---|---|---|
| 0 | Decyzje i przygotowanie | 🟢 zrobiony |
| 1 | Fundament projektu | 🟢 zrobiony |
| 2 | Auth i izolacja danych | 🟢 zrobiony |
| 3 | Model danych | 🟢 zrobiony |
| 4 | Warstwa danych rynkowych | 🟢 zrobiony |
| 5 | Pozycje i wycena | ⚪ |
| 6 | Analityka i dashboard | ⚪ |
| 7 | Wdrożenie produkcyjne | ⚪ |
| 8 | Metryki i ryzyko (Faza 2) | ⚪ |
| 9 | Otoczka (Faza 3) | ⚪ |

Legenda: ⚪ nie zaczęty · 🟡 w toku · 🟢 zrobiony · 🔴 zablokowany

## Kroki 1–50

```
[x] 1  ADR-101 zatwierdzony (semantyka historii)
[x] 2  ADR-102 zatwierdzony (słownik rynków)
[x] 3  Klucze API: Finnhub, Alpha Vantage, CoinGecko
[x] 4  VPS + domena + DNS
[x] 5  Monorepo
[x] 6  Docker Compose dev
[x] 7  Szkielet FastAPI (moduły)
[x] 8  Alembic + konfiguracja env
[x] 9  Szkielet Next.js + layout
[x] 10 CI: lint, testy, build
[x] 11 users, refresh_tokens, rejestracja/logowanie
[x] 12 JWT access+refresh
[x] 13 OAuth Google PKCE
[x] 14 get_owned_portfolio / get_owned_holding (wzorzec gotowy; konkret dopisany w etapie 3/5, patrz notatka poniżej)
[x] 15 Parametryzowany test izolacji w CI
[x] 16 Rate limiting
[x] 17 Migracje modelu danych
[x] 18 NUMERIC, indeksy, CASCADE
[x] 19 Seed rynków + aktywa demo
[x] 20 DataProvider + RateLimiter + CircuitBreaker + FallbackChain
[x] 21 NBP (kursy + złoto)
[x] 22 Stooq + yfinance + Finnhub fallback (+ Binance zamiast CoinGecko, patrz notatka)
[x] 23 Worker APScheduler, joby EOD per rynek
[x] 24 /assets/search + /meta/freshness
[ ] 25 CRUD pozycji
[ ] 26 Wycena PLN + /holdings + /summary
[ ] 27 Snapshoty + composition_change
[ ] 28 Heurystyka splitu
[ ] 29 Alokacja + koncentracja (HHI)
[ ] 30 Ranking rynków + indeksy referencyjne
[ ] 31 Cache Redis wersjonowany
[ ] 32 Dashboard + wykres wartości
[ ] 33 Widoki struktury (donut, treemap, sektor, geo)
[ ] 34 Panel „Twoje rynki"
[ ] 35 Formularz mobile, stany puste, dark mode
[ ] 36 Caddy + compose produkcyjny
[ ] 37 Sentry + /health + alerty
[ ] 38 Backup pg_dump
[ ] 39 Smoke test 375px + desktop  ← KONIEC FAZY 1
[ ] 40 Zwroty dzienne (bez dni composition_change)
[ ] 41 Ryzyko: zmienność, Sharpe, drawdown, beta
[ ] 42 Benchmark (WIG20, S&P 500)
[ ] 43 Watchlisty i tagi
[ ] 44 RLS w Postgres (domknięcie ADR-002)
[ ] 45 Wykresy świecowe
[ ] 46 Newsy (RSS + Finnhub)
[ ] 47 Kalendarz dywidend
[ ] 48 Import CSV listy pozycji (opcjonalnie)
[ ] 49 PWA: Serwist, manifest, IndexedDB
[ ] 50 Web Push + i18n
```

## Decyzje oczekujące na użytkownika

- [ ] Commit + ewentualny push zmian z etapu 4 (DataProvider/RateLimiter/CircuitBreaker/FallbackChain, providerzy NBP/Stooq/yfinance/Finnhub/Binance, worker APScheduler, `/assets/search`+`/meta/freshness`) — repo ma już podłączony remote `github.com/trxvcz/AlphaSense`.
- [x] GOOGLE_CLIENT_ID/SECRET uzupełnione przez użytkownika. `/api/auth/google/start` zweryfikowany z prawdziwymi danymi (poprawny redirect do accounts.google.com, PKCE S256, state) — pozostaje do Twojej weryfikacji: pełny klik-przez-flow w przeglądarce (Google Cloud Console → Authorized redirect URIs musi mieć `http://localhost:8000/api/auth/google/callback`).

## Backlog bezpieczeństwa (nieblokujące, do adresu w kolejnych etapach)

- `get_remote_address` w rate limiterze czyta `request.client.host` — za Caddy (etap 7) to będzie adres proxy, nie klienta. Do naprawy przy wdrożeniu produkcyjnym (krok 36), inaczej rate limiting na `/auth/*` przestanie działać per-IP.
- Pełna weryfikacja e-maila przy rejestracji hasłem (`email_verified_at`) nie jest zrobiona — wymaga wyboru dostawcy e-mail (nowa zależność zewnętrzna, decyzja użytkownika). Dzisiejsza łatka (czyszczenie `password_hash` + unieważnienie tokenów przy pierwszym logowaniu Google na ten sam e-mail) usuwa najostrzejsze ryzyko (trwały hijack), ale nie jest pełnym rozwiązaniem.
- Rozważyć indeks funkcyjny `lower(email)` w Postgresie (dziś normalizacja tylko w kodzie aplikacji, `ix_users_email` jest zwykłym btree case-sensitive).

## Backlog danych rynkowych (etap 4, nieblokujące)

- `WIG20` w `asset_source_map` ma dziś tylko mapowanie Stooq, bez fallbacku yfinance — realna ingestia GPW kończy się `status=partial`, gdy Stooq odmawia (środowiskowo obserwowane: 404/anty-bot). Dodanie drugiego wpisu `asset_source_map` (yfinance, jeśli Yahoo w ogóle notuje WIG20) naprawiłoby to; do zrobienia przy pierwszej okazji, nie blokuje.
- `/meta/freshness` liczy świeżość jako „ostatni `ingestion_run` z dziś lub wczoraj (UTC)" — prosta reguła, świadomie nieświadoma kalendarza sesji per rynek (może dać fałszywy `stale=True` dla GPW/US w weekend/poniedziałek rano mimo aktualnych piątkowych danych). Do doprecyzowania, jeśli w praktyce da fałszywe alarmy.
- Snapshot portfeli (`backend/worker/jobs/snapshot_portfolios.py`) to świadomie pusty stub — silnik wyceny (etap 5, kroki 26-27) musi powstać, zanim ten job będzie miał sens.

## Notatki operacyjne

- **Demo login**: `demo@alphasense.example`, hasło wypisywane na konsoli tylko przy tworzeniu konta (`make seed`). Fixture `_clean_auth_tables` w `backend/tests/conftest.py` robi `TRUNCATE users CASCADE` przed każdym testem — `pytest`/`make check` usuwa demo użytkownika (kaskadowo portfel+holdings); `markets`/`assets` przetrwają. Po `make check` odpal `make seed` ponownie, jeśli potrzebujesz demo konta.
- **Pułapka e-mail w seedach/testach**: `email-validator` (Pydantic `EmailStr`) odrzuca domeny `.local` i `.test` jako „special-use". Do danych demo/testowych używaj `.example` (RFC 2606, gwarantowana nierozwiązywalna) — nie `.local`/`.test`.
- Po każdej zmianie `requirements.txt`/`requirements-dev.txt` w kontenerze `api` trzeba `docker compose up -d --build api` (nie samo `up -d`) — inaczej nowe zależności zainstalowane wcześniej „na żywo" w kontenerze (`pip install` przez `exec`) nie są zapisane w obrazie i znikają przy każdym recreate.

## Dziennik sesji

| Data | Co zrobione | Notatki / blokery |
|---|---|---|
| 2026-07-24 | Struktura agentowa repo (CLAUDE.md, agenci, skille, komendy, docs) | — |
| 2026-07-24 | Etap 0 zamknięty: ADR-101 i ADR-102 zatwierdzone, klucze API i VPS/domena/DNS potwierdzone przez użytkownika. Code-reviewer wykrył blokujące niespójności 403 vs 404 (CLAUDE.md, backend-fastapi.md, code-reviewer.md, endpoint.md) i luki w `.claude/settings.json` (`Read(//home/**)` zbyt szerokie, `deny .env.*` blokował `.env.example`, ścieżka `alembic/versions/**` nie odpowiadała realnej strukturze) — wszystkie naprawione. Otwarte „do poprawy" bez blokady: błędne relatywne odnośniki `../STATUS.md` w `.claude/agents\|commands`, rozgraniczenie kroku 48 (import CSV pozycji) od wykluczonego importu transakcji, `make test` bez filtra `-m "not network"`. | Start etapu 1 (Fundament) odblokowany. |
| 2026-07-24 | Krok 9: szkielet Next.js (App Router, TS strict, Tailwind v4, ESLint flat config z `@typescript-eslint/no-explicit-any` na "error") w `frontend/`. Dodano `app/providers.tsx` (QueryClientProvider), `app/layout.tsx` z boczną nawigacją (desktop, `md:`) i dolną (mobile, do `md:`) wg CLAUDE.md sekcja 6, `app/page.tsx` jako placeholder, `lib/queryKeys.ts` i `lib/money.ts` (szkielety do rozbudowy), `components/nav/*`. Next.js 16.2.11 — Turbopack domyślny, `next lint` usunięty (lint idzie przez `eslint` bezpośrednio, zgodnie z tym co już generuje `create-next-app`). Zweryfikowano: `npm run lint`, `npx tsc --noEmit`, `npm run build` — zielone. | Kroki 5–8 i 10 (monorepo/compose/FastAPI/Alembic/CI) nadal otwarte — etap 1 pozostaje w toku. |
| 2026-07-24 | **Etap 1 zamknięty** (kroki 5–10). Krok 5: repo okazało się już mieć `git init` + remote `origin` (github.com/trxvcz/AlphaSense) — poprawiono błędne założenie planu, utworzono `backend/`, `frontend/`, `worker/.gitkeep`. Krok 7: szkielet FastAPI (`app/main.py`, `core/{config,errors,security,deps,cache}.py`, moduły `auth/portfolio/marketdata/analytics/news` z pustymi routerami, `pyproject.toml` ruff+mypy strict, `requirements*.txt`) — wykrył, że `mypy backend/app` z korzenia repo nie podnosi `backend/pyproject.toml`; naprawione w `.github/workflows/ci.yml` (`cd backend && mypy app`). Krok 8: `app/db/{base,session}.py`, Alembic async (`alembic.ini`, `env.py`), pusta migracja `0001_initial_empty` — cykl up→down→up zweryfikowany. Krok 6: `docker-compose.yml` (postgres/redis/api/frontend), `backend/Dockerfile`, `frontend/Dockerfile` — stack wstaje, zweryfikowany `docker compose ps` (4/4 up, postgres healthy), `GET /openapi.json` → 200 (`paths: {}`), `GET /` frontend → 200. Krok 10: dodano `backend/tests/test_app.py` (smoke test — bez niego `pytest` zwracał exit 5 "no tests collected" i psuł `make check`), pełne `make check` zielone (ruff, mypy strict, pytest, next build). | Kryterium ukończenia etapu 1 spełnione. Uwaga środowiskowa: sandbox blokuje `docker compose down`/`stop` (permission denied) — stack pozostał `up`, dane niezagrożone. Nic z etapu 1 nie jest jeszcze zacommitowane — czeka na decyzję (patrz „Decyzje oczekujące"). |
| 2026-07-24 | Zmiana nazwy produktu z „Portfel v2" na „AlphaSense" (18 miejsc: CLAUDE.md, README, agenci/skille, `backend/app/main.py` tytuł FastAPI, frontend layout/nawigacja). Zacommitowane lokalnie. Nazwy plików `docs/*-portfel-v2.md` i pakiet `portfel-backend` świadomie bez zmian (nie branding). | — |
| 2026-07-24 | **Etap 2 zamknięty** (kroki 11–16). Krok 11: tabele `users`/`refresh_tokens` (migracja, `ON DELETE CASCADE`/`SET NULL`), rejestracja+logowanie (argon2id). Krok 12: JWT (PyJWT, access 15 min), `get_current_user` realny, refresh z rotacją i wykrywaniem ponownego użycia (unieważnia cały łańcuch), logout. Krok 13: OAuth Google (Authlib, PKCE, `state` w podpisanym cookie — bez `SessionMiddleware`), upsert po e-mailu; `password_hash` w `User` stał się nullable (migracja addytywna) dla kont OAuth-only. Krok 14: **zawężony zgodnie z decyzją** — tylko wzorzec + `get_current_user`; `get_owned_portfolio`/`get_owned_holding` konkretnie dopiszę w etapie 3 (`portfolios`) i 5 (`holdings`), bo tabele jeszcze nie istnieją. Krok 15: `backend/tests/test_isolation.py` — mechanizm ze skilla `izolacja-danych`, dziś 0 dopasowanych tras (pytest: skip, nie error — zweryfikowane), automatycznie zacznie działać od etapu 3/5; warunek `hashFiles` z etapu 1 usunięty z CI. Krok 16: rate limiting (slowapi, Redis-backed, fail-closed), 5/min na `/auth/register`+`/auth/login`, 100/min globalnie. **Security-auditor** znalazł i naprawiono: pre-account-hijack przez upsert po e-mailu (czyszczenie `password_hash`+unieważnienie tokenów przy pierwszym Google-loginie na e-mail konta hasłowego), brak walidacji `SECRET_KEY` w prod (teraz odmawia startu z placeholderem/za krótkim kluczem), normalizacja e-maila (`.strip().lower()`), race condition w rotacji refresh (`with_for_update()`). 30 testów, wszystkie zielone. Zweryfikowany żywy flow register→login→refresh→logout przez curl. | Kryterium ukończenia etapu 2 spełnione. Backlog bezpieczeństwa nieblokujący — patrz sekcja wyżej. Nic z etapu 2 nie jest jeszcze zacommitowane. |
| 2026-07-24 | Użytkownik uzupełnił GOOGLE_CLIENT_ID/SECRET w `.env`. Obraz `api` przebudowany (`--build`, wcześniejszy kontener miał zależności etapu 2 doinstalowane tylko „na żywo", nie w obrazie) — `/api/auth/google/start` zweryfikowany z realnymi danymi: poprawny redirect do Google, PKCE S256, state, nonce. Pozostaje do zweryfikowania przez użytkownika: pełny klik-przez-flow w przeglądarce. | Uwaga bezpieczeństwa: `printenv` w trakcie diagnozy przypadkowo wypisał `GOOGLE_CLIENT_SECRET` w plaintext do transkryptu sesji — nigdy niezacommitowany, ale do rozważenia rotacja w Google Cloud Console. |
| 2026-07-24 | **Etap 3 zamknięty** (kroki 17–19). Krok 17-18: migracje w kolejności rozwiązującej cykl FK `markets ⇄ assets` (markets bez index_asset_id → assets → ALTER markets ADD index_asset_id), plus `portfolios`/`holdings` (CASCADE, UNIQUE, CHECK quantity/avg_cost), `prices`/`asset_source_map`/`fx_rates`/`ingestion_runs`/`portfolio_valuations` (NUMERIC(20,8), TIMESTAMPTZ, indeksy DESC). Autogenerate po zastosowaniu migracji dał **pusty diff** (modele = migracje, potwierdzone). Krok 19: `backend/app/cli.py` (`make seed`, argparse — bez nowej zależności), `backend/app/db/seed.py` — 12 rynków + 11 indeksów referencyjnych jako `assets`, 4 demo aktywa (CDR/PKN/AAPL/MSFT), demo użytkownik+portfel+5 holdings (**na wyraźną prośbę użytkownika**, mimo że CRUD portfeli/pozycji to etap 5); idempotentne (zweryfikowane dwoma przebiegami, bez duplikatów). **Bug znaleziony i naprawiony przeze mnie po zakończeniu subagentów**: seed użył `demo@alphasense.local` — `.local` jest odrzucane przez `email-validator`/Pydantic `EmailStr` jako domena special-use, więc demo konto było **nielogowalne przez realny `/api/auth/login`** (żaden subagent tego nie złapał, bo testowali tylko stan DB/pytest, nie żywe logowanie z tym dosłownym adresem) — zmienione na `demo@alphasense.example` (RFC 2606), zweryfikowane żywym `curl` login → 200. `get_owned_portfolio`/`get_owned_holding` wciąż odłożone do etapu 5 (dopiszę razem z pierwszym endpointem, który ich potrzebuje — pisanie zależności bez konsumenta byłoby spekulacją). | Kryterium ukończenia etapu 3 spełnione. `make check` zielone. Demo login: `demo@alphasense.example` — hasło wypisane raz przy `make seed`, patrz „Notatki operacyjne". Nic z etapów 2-3 nie jest jeszcze zacommitowane. |
| 2026-07-24 | **Code-reviewer na całym niescommitowanym diffie etapów 2+3** — nic blokującego (niezależnie zweryfikował: mypy/ruff/pytest zielone, `alembic check` pusty diff, brak FIFO/XIRR/transaction w kodzie). Naprawione „do poprawy": `docs/api-kontrakt.md` używał generycznego `{id}` dla portfeli/pozycji — zmienione na `{portfolio_id}`/`{holding_id}`, bo harness izolacji (`RESOURCE_PARAMS`) łapie trasy dosłownie po tych nazwach — inaczej endpointy z etapu 5 zbudowane wg litery kontraktu umknęłyby automatycznemu gate'owi bezpieczeństwa. Reorganizacja `backend/tests/` na `unit/`/`integration/` zgodnie z `docs/konwencje.md` (`test_config.py`→`unit/`, `test_app.py`/`test_auth.py`/`test_auth_oauth.py`/`test_rate_limit.py`→`integration/`; `test_isolation.py`/`conftest.py` zostają płasko w `tests/`, tak jak nakazuje konwencja). Poprawiony nieaktualny docstring w `test_isolation.py` (pytest raportuje puste sparametryzowanie jako „1 skipped", nie „0 selected") i w `main.py` (już nie „czysty szkielet etapu 1"). Nienaprawione (świadomie, „drobne"): `oauth_state` cookie nie czyści się na ścieżkach błędu `google_callback` — wymagałoby złamania konwencji jednego centralnego exception handlera; niskie ryzyko (cookie podpisane, TTL 10 min), odłożone. | — |
| 2026-07-24 | **Etap 4 zamknięty** (kroki 20–24) — najbardziej ryzykowny etap wg CLAUDE.md §5. Krok 20: `providers/{base,rate_limiter,circuit_breaker,guarded,fallback_chain}.py`, stan RateLimiter/CircuitBreaker w Redisie (przetrwa restart, zweryfikowane testem). Krok 21: NBP (kursy + złoto→`prices` jako `Asset XAU`), `fx_rates.get_rate_pln` z `max(date)<=D`, fixture'y nagrane **z realnego `api.nbp.pl`**. Krok 22: Stooq/yfinance/Finnhub + **Binance zamiast CoinGecko** (ustalone z użytkownikiem — CoinGecko spłaciło darmowy plan; Binance klines, bez klucza, + yfinance `BTC-USD` jako fallback). Krok 23: worker w **`backend/worker/`** (nie top-level `worker/` — decyzja architektoniczna, jeden obraz Dockera z API, CLAUDE.md §6 zaktualizowany), `advisory_lock` (`pg_try_advisory_lock`, klucz SHA-256→63 bity), job `ingest_market` (nie przerywa się na błędzie pojedynczego aktywa), `python -m app.cli ingest --market <code>`, serwis `worker` w `docker-compose.yml`. Krok 24: `/assets/search` (422 dla `q`<2 znaków, uzupełnianie metadanych w tle przez `BackgroundTasks`), `/meta/freshness` (per rynek: ostatni `ingestion_run`, `stale`) — oba świadomie publiczne (assets/markets nie są zasobami użytkownika). Żywa weryfikacja: `ingest --market FX/CRYPTO/COMMODITY` → `status=ok` z realnymi danymi NBP/Binance; `--market GPW` → `status=partial` (Stooq odmówił, yfinance fallback zadziałał dla 2/3 aktywów, WIG20 bez fallbacku — patrz backlog). **Bug znaleziony i naprawiony przeze mnie**: `Makefile` (`make test`/`make check`) nie filtrował `@pytest.mark.network`, więc żywy test NBP potrafił niedeterministycznie wywalić `make check` — dodane `-m "not network"` (teraz spójne z `ci.yml`). **Po code-review (bez blokujących) naprawiłem**: `ingest_market` nie zapisywał `IngestionRun` przy wyjątku POZA pętlą per-aktywo (np. `build_fallback_chain`/błąd bazy) — złamanie SKILL `job-eod` reguły 5, `/meta/freshness` pokazywałby stare dane zamiast `status=failed`; owinięte w `try/except`, zapisuje i re-raise'uje. Niespójność słownictwa `status`: `docs/api-kontrakt.md`/testy używały `"success"`, kod zawsze zapisuje `"ok"` — ujednolicone. Dodane testy potwierdzające, że stan `CircuitBreaker`/`RateLimiter` przetrwałby restart (dwie niezależne instancje, ten sam klucz Redis). TTL na stanie `CircuitBreaker` (30 dni — nie rósł w nieskończoność dla porzuconych dostawców). `python -m app.cli ingest` zwraca teraz niezerowy exit code przy `status=failed`. Usunięty zduplikowany pin `httpx` w `requirements-dev.txt`. | Kryterium ukończenia etapu 4 spełnione. `make check` zielone (119 testów). Backlog danych rynkowych — patrz sekcja wyżej. Nic z etapu 4 nie jest jeszcze zacommitowane. |
