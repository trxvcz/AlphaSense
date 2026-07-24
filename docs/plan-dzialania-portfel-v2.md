# Plan działania krok po kroku v2 — monitoring i analiza składu portfela

**Powiązany dokument:** projekt-systemu-portfel-v2.md
**Data:** 2026-07-20
**Zakres:** wersja bez rejestru transakcji — użytkownik wpisuje posiadane aktywa, aplikacja je wycenia, analizuje strukturę (klasy, sektory, geografia, waluty, rynki) i pozwala obserwować rynki obecne w portfelu.

Kolejność ma znaczenie: najpierw fundament i izolacja danych, wdrożenie na serwer wcześnie (nie na końcu), metryki dopiero gdy są snapshoty. Każdy etap kończy się czymś działającym.

---

## Etap 0 — Decyzje i przygotowanie (1 dzień)

1. Zatwierdź ADR-101: semantyka historii — snapshoty „od teraz" (append-only), edycja pozycji wpływa tylko na przyszłość; pole `valid_from` w schemacie od razu.
2. Zatwierdź ADR-102: słownik rynków z indeksami referencyjnymi (GPW→WIG20, USA→S&P 500, krypto→BTC itd.) — spisz startową listę kilkunastu rynków.
3. Załóż konta i klucze API: Finnhub, Alpha Vantage, CoinGecko (NBP i Stooq bez kluczy).
4. Wykup VPS + domenę, skonfiguruj DNS.

## Etap 1 — Fundament projektu (2–3 dni)

5. Monorepo: katalogi `backend/`, `frontend/`, `docker-compose.yml`.
6. Docker Compose dev: `postgres`, `redis`, `api` (FastAPI + uvicorn), `frontend` (Next.js), później `worker` i `caddy`.
7. Szkielet FastAPI z podziałem na moduły: `auth`, `portfolio`, `marketdata`, `analytics`, `news`.
8. Alembic + pierwsza pusta migracja; konfiguracja przez zmienne środowiskowe (pydantic-settings).
9. Szkielet Next.js (App Router, TypeScript) + TanStack Query + podstawowy layout z dolną nawigacją mobile / boczną desktop.
10. CI (GitHub Actions): lint, testy backendu, build frontendu — od pierwszego commita.

## Etap 2 — Auth i izolacja danych (3–5 dni)

11. Tabele `users`, `refresh_tokens`; rejestracja + logowanie (argon2id).
12. JWT: access 15 min + refresh rotowany w httpOnly cookie; endpointy `login/refresh/logout`.
13. OAuth Google (Authorization Code + PKCE, wyłącznie po stronie backendu).
14. Wzorzec autoryzacji zasobowej: zależność `get_owned_portfolio` / `get_owned_holding` — żaden endpoint nie bierze „gołego" ID z path.
15. Parametryzowany test izolacji dwóch użytkowników w CI (przechodzi po wszystkich trasach automatycznie) — wdrażany od razu.
16. Rate limiting (`slowapi`), ostrzejszy na `/auth/*`.

## Etap 3 — Model danych (2 dni)

17. Migracje dla: `portfolios`, `holdings` (ilość, opcjonalny `avg_cost` + waluta, `valid_from`, UNIQUE(portfolio_id, asset_id)), `assets` (klasa, sektor, kraj, region, `market_code`), `markets` (słownik z indeksem referencyjnym i godziną EOD), `asset_source_map`, `prices` (z `close_adj`), `fx_rates`, `portfolio_valuations` (sama wartość, bez przepływów), `ingestion_runs`.
18. Kwoty jako `NUMERIC(20,8)`, indeksy wg dokumentu projektowego, `ON DELETE CASCADE` od użytkownika w dół.
19. Seed: słownik rynków + indeksy referencyjne jako aktywa + kilka aktywów demo GPW/US/krypto z przykładowymi pozycjami.

## Etap 4 — Warstwa danych rynkowych (4–6 dni)

20. Interfejs `DataProvider` + warstwy `RateLimiter` (backoff przy 429), `CircuitBreaker`, `FallbackChain`.
21. Implementacja NBP (kursy + złoto, cofanie do ostatniego dnia roboczego).
22. Implementacja Stooq (CSV, GPW) i yfinance z fallbackiem na Finnhub; mapowanie symboli w `asset_source_map`; pobieranie metadanych aktywa (sektor/kraj) przy pierwszym dodaniu.
23. Kontener `worker` z APScheduler: joby EOD per rynek z godzinami czytanymi ze słownika `markets` (NBP 12:35, GPW 18:30, US 23:15, krypto 00:30), blokada doradcza Postgresa, zapis do `ingestion_runs`. Indeksy referencyjne pobierane tymi samymi jobami.
24. Endpoint `GET /assets/search` (autouzupełnianie tickera) + `GET /meta/freshness`.

## Etap 5 — Pozycje i wycena (2–3 dni)

25. CRUD pozycji: aktywo z autouzupełniania + ilość + opcjonalnie średnia cena nabycia; walidacja Pydantic; edycja ilości = zwykły PATCH (bez przeliczania historii — ADR-101).
26. Bieżąca wycena portfela w PLN (`ilość × close_adj × kurs NBP`); endpointy `/holdings` i `/summary`; opcjonalny niezrealizowany P/L dla pozycji z podanym kosztem.
27. Job snapshotów `portfolio_valuations` po każdym EOD; znacznik `composition_change` w dniu edycji składu.
28. Heurystyka wykrywania splitu (skok ceny >40% d/d) → przypomnienie w UI „sprawdź ilość".

## Etap 6 — Analityka struktury i dashboard (5–7 dni) — serce aplikacji

29. Endpointy alokacji: `?by=class|sector|geo|currency|market` (GROUP BY po atrybutach wycenionych pozycji) + `concentration` (top 5, liczba pozycji, HHI z opisową interpretacją).
30. **Ranking rynków**: udział % każdej giełdy w wartości portfela + dane indeksu referencyjnego (wartość, zmiana dzienna, mini-seria).
31. Cache Redis wg kluczy wersjonowanych (znacznik = ostatnia edycja pozycji + data EOD).
32. Dashboard: łączna wartość, zmiana dzienna, YTD, mini-wykres, top ruchy dnia; wykres wartości (ECharts) 1M/3M/1R/YTD/max ze znacznikami zmian składu.
33. Widoki struktury: donut (klasy), treemap (pozycje / waluty), wykresy sektor i geografia z etykietą „przybliżone" dla ETF + ręczny override metadanych.
34. Panel „Twoje rynki" sortowany wg wagi rynku w portfelu.
35. Formularz dodawania pozycji zoptymalizowany pod telefon; stany puste („dodaj pierwszą pozycję"); tryb ciemny/jasny.

## Etap 7 — Pierwsze wdrożenie produkcyjne (2–3 dni)

36. Caddy (TLS automatyczny), compose produkcyjny, migracje jako krok przed startem API.
37. Sentry (backend + frontend), `/health`, alert z workera przy failu ingestii.
38. Nocny `pg_dump` poza VPS.
39. Smoke test na telefonie (375 px) i desktopie — **koniec Fazy 1**: wpisujesz pozycje, widzisz wartość, skład % i ranking rynków.

## Etap 8 — Metryki i ryzyko (Faza 2, ~1,5–2 tyg.)

40. Zwroty dzienne ze snapshotów z wyłączeniem dni `composition_change` (żeby dokupienie nie udawało zysku).
41. Ryzyko: zmienność, Sharpe (stopa referencyjna NBP jako konfigurowalny parametr), max drawdown + wykres underwater, beta; heatmapa zwrotów miesięcznych.
42. Porównanie z benchmarkiem (WIG20, S&P 500 — wybór użytkownika, wykres znormalizowany do 100).
43. Watchlisty i tagi (CRUD + filtrowanie widoków struktury po tagach).
44. Domknięcie ADR-002: polityki RLS w Postgres, worker z rolą `BYPASSRLS`.
45. Wykresy świecowe pojedynczych aktywów i indeksów (Lightweight Charts).

## Etap 9 — Otoczka (Faza 3, ~2 tyg.)

46. Newsy: joby RSS (Bankier, Money, StockWatch) + Finnhub/Alpha Vantage, deduplikacja, tagowanie po tickerach z portfela i watchlist, feed z filtrem sentymentu.
47. Kalendarz dywidend (Finnhub dla zagranicy; GPW oznaczone jako ograniczenie).
48. (Opcjonalnie) prosty import listy pozycji z CSV — jeden kanoniczny format: `symbol;ilość;cena_nabycia`.
49. PWA na pełnej mocy: Serwist, manifest, persystencja cache do IndexedDB, baner „dane z {data}, offline".
50. Web Push (z instrukcją instalacji na ekranie głównym dla iOS); struktura i18n (next-intl) z polskim jako jedynym językiem.

---

## Harmonogram orientacyjny

| Zakres | Czas (1 osoba) |
|---|---|
| Faza 1 (etapy 0–7) | ok. 3–4,5 tygodnia |
| Faza 2 (etap 8) | ok. 1,5–2 tygodnie |
| Faza 3 (etap 9) | ok. 2 tygodnie |
| **Całość** | **ok. 6–9 tygodni** |

Względem wersji z transakcjami wypadły: silnik FIFO, XIRR/TWR z przepływami, model przepływów pieniężnych, przeliczanie historii po edycjach i import CSV od brokerów — stąd skrócenie o ~połowę. Największy bufor zostawić na etap 4 (jakość darmowych źródeł danych) i etap 6 (to tu powstaje wartość produktu — analityka struktury).
