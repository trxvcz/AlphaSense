# CLAUDE.md — instrukcja pracy nad projektem „Portfel v2"

Ten plik czytasz automatycznie przy każdej sesji. Traktuj go jako nadrzędny wobec własnych domyślnych nawyków.

## 1. Czym jest ten projekt

Aplikacja webowa (PWA) do **monitoringu i analizy składu portfela inwestycyjnego**. Użytkownik wpisuje posiadane aktywa (pozycje), system je wycenia w PLN, rozkłada portfel na klasy/sektory/geografię/waluty/rynki i pozwala obserwować indeksy rynków, na których użytkownik jest zainwestowany.

**Serce produktu to analityka struktury i ranking rynków — nie księgowość.**

Świadomie POZA zakresem (nie implementuj, nawet jeśli wydaje się „naturalne"):
rejestr transakcji, FIFO, zrealizowany P/L, XIRR/TWR z przepływami, import CSV od brokerów, rozliczenia podatkowe.
Jeśli uznasz, że zadanie wymaga któregoś z tych elementów — **zatrzymaj się i zapytaj**, zamiast rozszerzać zakres.

Dokumenty źródłowe (czytaj zanim zaczniesz kodzić w nowym obszarze):
- `docs/projekt-systemu-portfel-v2.md` — projekt systemu (architektura, model danych, obliczenia)
- `docs/plan-dzialania-portfel-v2.md` — plan 50 kroków w 10 etapach
- `docs/adr` — decyzje architektoniczne (ADR-101, ADR-102 i przeniesione z v1)
- `docs/model-danych.md`, `docs/api-kontrakt.md`, `docs/konwencje.md`, `docs/slownik-rynkow.md`
- `../STATUS.md` — **gdzie aktualnie jesteśmy** i co jest następne

## 2. Stack

| Warstwa | Technologia |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.x (async), Pydantic v2, Alembic |
| Baza | PostgreSQL 16 |
| Cache | Redis 7 (czysty cache, nigdy źródło prawdy) |
| Worker | osobny kontener, APScheduler + blokady doradcze Postgresa |
| Frontend | Next.js (App Router) + TypeScript + TanStack Query + Tailwind |
| Wykresy | ECharts (portfel, struktura), Lightweight Charts (świece) |
| Proxy | Caddy (TLS automatyczny) |
| Infra | docker-compose na jednym VPS |
| Testy | pytest + pytest-asyncio + httpx (backend), Vitest + Playwright (frontend) |

## 3. Zasady, które łamiesz tylko po jawnej zgodzie użytkownika

1. **Kwoty i ilości: `NUMERIC(20,8)` w bazie, `Decimal` w Pythonie, `string` w JSON. Nigdy `float`.**
2. **Żaden endpoint nie przyjmuje „gołego" ID z path.** Zawsze przez zależność `get_owned_portfolio` / `get_owned_holding`, która weryfikuje własność względem `current_user`. Zobacz skill `izolacja-danych`.
3. **Snapshoty są append-only** (ADR-101, opcja A). Edycja pozycji wpływa tylko na przyszłość. Nie buduj mechanizmu przeliczania historii.
4. **Wycena i wykresy zawsze na `close_adj`**, nigdy na surowym `close`.
5. **Kursy walut wyłącznie z NBP**, lookup `max(date) <= D` (cofanie do ostatniego dnia roboczego).
6. **Godziny jobów EOD czytasz ze słownika `markets`**, nie z hardkodu w kodzie workera (ADR-102).
7. **Redis można w każdej chwili wyczyścić** i aplikacja musi działać. Klucze wersjonowane: `{zasób}:{portfolio_id}:{ostatnia_edycja_holdings}:{data_eod}`.
8. **Migracja Alembic do każdej zmiany modelu**, w tym samym commicie. Nigdy `create_all()` w produkcji.
9. **Nie commituj sekretów.** Konfiguracja przez zmienne środowiskowe (pydantic-settings), wzorzec w `.env.example`.
10. **Każdy nowy endpoint dostaje test izolacji dwóch użytkowników** — parametryzowany test w CI ma go złapać automatycznie.

## 4. Jak pracujesz (pętla)

Przy każdym zadaniu:

1. **Zorientuj się** — przeczytaj `../STATUS.md`, znajdź numer kroku z planu, którego dotyczy zadanie.
2. **Zaplanuj** — rozpisz plan w TODO. Jeśli krok z planu jest większy niż ~1 dzień pracy, podziel go.
3. **Wykonaj** — najmniejsza zmiana, która domyka krok. Nie robisz „przy okazji" refaktorów w innych modułach.
4. **Zweryfikuj** — uruchom `make check` (lint + typy + testy backendu + build frontendu). Zielone albo nie kończysz.
5. **Zapisz** — zaktualizuj `../STATUS.md` (krok → zrobiony, notatki, co blokuje) i, jeśli podjęto decyzję architektoniczną, dopisz ADR w `docs/adr`.
6. **Podsumuj** — krótko: co zrobione, co dalej, co wymaga decyzji użytkownika.

**Każdy etap kończy się czymś działającym.** Jeśli po twojej zmianie `docker compose up` nie wstaje — nie skończyłeś.

## 5. Kolejność etapów (nie przeskakuj)

```
0. Decyzje i przygotowanie      → ADR-101, ADR-102, klucze API, VPS
1. Fundament                    → monorepo, compose, szkielet FastAPI/Next, CI
2. Auth i izolacja danych       → JWT, OAuth, get_owned_*, test izolacji w CI
3. Model danych                 → migracje, seed rynków i aktywów demo
4. Warstwa danych rynkowych     → DataProvider, NBP/Stooq/yfinance, worker EOD
5. Pozycje i wycena             → CRUD holdings, wycena PLN, snapshoty
6. Analityka i dashboard        ← SERCE PRODUKTU, największy bufor
7. Wdrożenie produkcyjne        → Caddy, Sentry, backup, smoke test = koniec Fazy 1
8. Metryki i ryzyko             → Faza 2
9. Otoczka (newsy, PWA, push)   → Faza 3
```

Największe ryzyko: **etap 4** (jakość darmowych źródeł) i **etap 6** (tu powstaje wartość). Tam zostawiaj bufor i tam nie ciąć jakości.

## 6. Struktura repo

**Stan aktualny:** repo jest na etapie 0 (patrz `STATUS.md`) — istnieją tylko `docs/`, `.claude/` (agenci, komendy, skille), `Makefile`, `.github/workflows/ci.yml`, `.env.example`, `README.md`, `STATUS.md`. Katalogów `backend/`, `frontend/`, `worker/` **jeszcze nie ma**. Struktura poniżej to cel etapu 1 (Fundament) — twórz ją zgodnie z tym układem, nie zakładaj, że już istnieje.

```
backend/
  app/
    main.py
    core/          config, security, deps, cache, errors
    modules/
      auth/        routes.py schemas.py service.py models.py
      portfolio/   portfele + holdings + wycena
      marketdata/  providers/, ingestion, assets, markets
      analytics/   allocation, concentration, risk, performance
      news/
    db/            base.py, session.py
  alembic/versions/
  tests/           unit/, integration/, test_isolation.py
frontend/
  app/             App Router: (auth)/, dashboard/, portfel/, rynki/, struktura/
  components/      ui/, charts/, forms/
  lib/             api client, query keys, formatery Decimal
worker/            scheduler.py, jobs/
docs/              projekt, plan, adr/, konwencje, model danych, kontrakt API
.claude/           agents/, commands/, skills/
```

## 7. Komendy

```bash
make up            # docker compose up dev
make down
make migrate       # alembic upgrade head
make revision m="opis"   # autogenerate migracji
make seed          # słownik rynków + aktywa demo
make test          # pytest
make check         # ruff + mypy + pytest + next build  ← przed każdym „gotowe"
make logs s=worker
```

## 8. Styl kodu

**Python:** ruff (format + lint), mypy w trybie strict dla `modules/`, type hints wszędzie. Warstwy: `routes` (walidacja + autoryzacja) → `service` (logika) → `repository/models` (SQL). Routes nie wołają SQL bezpośrednio. Wyjątki domenowe w `core/errors.py`, mapowane na HTTP w handlerze.

**TypeScript:** brak `any`. Kwoty jako `string` z API, konwersja przez `lib/decimal.ts` — nigdy `parseFloat` na kwocie do wyświetlenia obliczeń. Server Components domyślnie; `"use client"` tylko gdzie potrzebna interakcja. Dane przez TanStack Query z kluczami z `lib/queryKeys.ts`.

**Testy:** każdy endpoint — test szczęśliwej ścieżki + test 404 dla obcego zasobu (nie zdradzamy istnienia zasobu innego użytkownika, patrz skill `izolacja-danych`). Logika obliczeniowa (wycena, HHI, zwroty, drawdown) — testy jednostkowe na znanych liczbach, bez mocków bazy.

**Commity:** konwencjonalne, po polsku lub angielsku, konsekwentnie. `feat(analytics): ranking rynków wg wagi`.

## 9. Język

Rozmowa z użytkownikiem, dokumentacja, ADR-y, komunikaty UI: **polski**.
Kod, nazwy zmiennych, tabel, endpointów, commity: **angielski**.

## 10. Kiedy pytać, a kiedy działać

**Działaj bez pytania:** implementacja kroku z planu, testy, migracje wynikające z modelu, poprawki lintera, uzupełnianie dokumentacji.

**Zapytaj:** zmiana zakresu (patrz sekcja 1), zmiana ADR, dodanie zależności zewnętrznej, dodanie płatnego źródła danych, zmiana schematu, która wymaga migracji łamiącej, cokolwiek co dotyka pieniędzy użytkownika lub bezpieczeństwa auth.
