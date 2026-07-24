# STATUS — gdzie jesteśmy

> **Claude Code: czytaj ten plik na starcie każdej sesji i aktualizuj na końcu każdego zadania.**
> Jedno źródło prawdy o postępie. Numery kroków = `docs/plan-dzialania-portfel-v2.md`.

**Aktualny etap:** 1 — Fundament projektu
**Ostatnia aktualizacja:** 2026-07-24
**Faza:** 1 (etapy 0–7, cel: wpisujesz pozycje → widzisz wartość, skład % i ranking rynków)

## Postęp etapów

| Etap | Zakres | Status |
|---|---|---|
| 0 | Decyzje i przygotowanie | 🟢 zrobiony |
| 1 | Fundament projektu | ⚪ nie zaczęty |
| 2 | Auth i izolacja danych | ⚪ |
| 3 | Model danych | ⚪ |
| 4 | Warstwa danych rynkowych | ⚪ |
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
[ ] 5  Monorepo
[ ] 6  Docker Compose dev
[ ] 7  Szkielet FastAPI (moduły)
[ ] 8  Alembic + konfiguracja env
[ ] 9  Szkielet Next.js + layout
[ ] 10 CI: lint, testy, build
[ ] 11 users, refresh_tokens, rejestracja/logowanie
[ ] 12 JWT access+refresh
[ ] 13 OAuth Google PKCE
[ ] 14 get_owned_portfolio / get_owned_holding
[ ] 15 Parametryzowany test izolacji w CI
[ ] 16 Rate limiting
[ ] 17 Migracje modelu danych
[ ] 18 NUMERIC, indeksy, CASCADE
[ ] 19 Seed rynków + aktywa demo
[ ] 20 DataProvider + RateLimiter + CircuitBreaker + FallbackChain
[ ] 21 NBP (kursy + złoto)
[ ] 22 Stooq + yfinance + Finnhub fallback
[ ] 23 Worker APScheduler, joby EOD per rynek
[ ] 24 /assets/search + /meta/freshness
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

Brak — etap 0 zamknięty.

## Dziennik sesji

| Data | Co zrobione | Notatki / blokery |
|---|---|---|
| 2026-07-24 | Struktura agentowa repo (CLAUDE.md, agenci, skille, komendy, docs) | — |
| 2026-07-24 | Etap 0 zamknięty: ADR-101 i ADR-102 zatwierdzone, klucze API i VPS/domena/DNS potwierdzone przez użytkownika. Code-reviewer wykrył blokujące niespójności 403 vs 404 (CLAUDE.md, backend-fastapi.md, code-reviewer.md, endpoint.md) i luki w `.claude/settings.json` (`Read(//home/**)` zbyt szerokie, `deny .env.*` blokował `.env.example`, ścieżka `alembic/versions/**` nie odpowiadała realnej strukturze) — wszystkie naprawione. Otwarte „do poprawy" bez blokady: błędne relatywne odnośniki `../STATUS.md` w `.claude/agents\|commands`, rozgraniczenie kroku 48 (import CSV pozycji) od wykluczonego importu transakcji, `make test` bez filtra `-m "not network"`. | Start etapu 1 (Fundament) odblokowany. |
