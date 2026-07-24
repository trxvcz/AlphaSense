# Projekt systemu v2 — monitoring i analiza składu portfela inwestycyjnego

**Status:** Propozycja do akceptacji (zastępuje wersję opartą o transakcje)
**Data:** 2026-07-20
**Zmiana zakresu:** aplikacja NIE prowadzi rejestru kupna/sprzedaży. Użytkownik wpisuje posiadane aktywa (pozycje), a system je wycenia, analizuje strukturę portfela i pozwala obserwować rynki, na których użytkownik jest zainwestowany.

---

## 1. Podsumowanie wykonawcze

Uproszczenie zakresu wycina najtrudniejszą połowę poprzedniego projektu: znika silnik FIFO, XIRR, model przepływów pieniężnych (dawny ADR-006), mechanizm przeliczania historii po edycji transakcji oraz import CSV od brokerów. **Bez zmian zostaje** cała warstwa danych rynkowych (DataProvider, joby EOD, NBP/Stooq/yfinance), snapshoty dzienne, auth z izolacją danych, PWA i stack (FastAPI + PostgreSQL + Redis + Next.js).

Rdzeń produktu przesuwa się z „księgowości" na **analitykę struktury**:

1. **Pozycje zamiast transakcji** — tabela `holdings` (portfel, aktywo, ilość, opcjonalnie cena nabycia) jako źródło prawdy. Edycja = zwykła korekta ilości.
2. **Analiza ekspozycji** — dekompozycja portfela wg: klasy aktywa, sektora, geografii, waluty i **rynku (giełdy)**; ranking rynków wg wagi w portfelu.
3. **Obserwacja rynków** — dla każdego rynku obecnego w portfelu system automatycznie śledzi indeks referencyjny (GPW→WIG20, USA→S&P 500, krypto→BTC itd.) i pokazuje go na dashboardzie proporcjonalnie do wagi rynku.
4. **Metryki z cen, nie z przepływów** — zwrot portfela = zmiana wartości wycenianego koszyka; zmienność, Sharpe, beta, max drawdown liczone ze zwrotów cenowych. Opcjonalny P/L względem wpisanej ceny nabycia.
5. Jedna decyzja do podjęcia przed startem: **semantyka historii przy edycji pozycji** (ADR-101, sekcja 4).

Szacowany czas realizacji: **6–9 tygodni** (1 osoba) zamiast 3–4 miesięcy.

---

## 2. Zakres funkcjonalny

**Pozycje:** CRUD pozycji (aktywo z autouzupełniania + ilość + opcjonalnie: średnia cena nabycia, waluta nabycia, notatka). Wiele portfeli per użytkownik (IKE / zwykłe / spekulacyjny), watchlisty, tagi.

**Wycena:** bieżąca wartość w PLN (ceny EOD × ilość × kurs NBP), zmiana dzienna, wykres wartości w czasie (1M/3M/1R/YTD/max) z dziennych snapshotów.

**Analiza struktury (serce aplikacji):**
- Skład % portfela per pozycja (donut + treemap + tabela).
- Alokacja wg klasy aktywa (akcje/ETF/obligacje/krypto/surowce/REIT).
- Alokacja wg sektora i geografii („na czym opierają się te aktywa").
- Ekspozycja walutowa (PLN vs USD/EUR/inne).
- **Ranking rynków**: udział % każdej giełdy/rynku w wartości portfela — „które rynki mają największe znaczenie".
- Koncentracja: top 5 pozycji jako % całości, liczba pozycji, wskaźnik HHI (prosty sygnał dywersyfikacji).

**Obserwacja rynków:** panel „Twoje rynki" — dla rynków wykrytych w portfelu: indeks referencyjny (wartość, zmiana dzienna, mini-wykres), sortowany wg wagi rynku w portfelu; newsy filtrowane po aktywach z portfela i watchlist.

**Ryzyko i wyniki:** zwrot portfela za okres (ze snapshotów), zmienność, Sharpe, max drawdown + wykres underwater, beta i porównanie z wybranym benchmarkiem (znormalizowane do 100), heatmapa zwrotów miesięcznych. Opcjonalnie (gdy podano ceny nabycia): niezrealizowany P/L per pozycja i łącznie.

**Poza zakresem (świadomie):** rejestr transakcji, FIFO, zrealizowany P/L, XIRR/TWR z przepływami, import CSV od brokerów, rozliczenia podatkowe. Architektura nie zamyka drogi powrotu (sekcja 10).

---

## 3. Architektura

Bez zmian względem v1: modularny monolit FastAPI + osobny kontener workera (APScheduler, blokady doradcze Postgresa), PostgreSQL, Redis jako czysty cache, Next.js PWA, Caddy, docker-compose na jednym VPS. Warstwa DataProvider (RateLimiter + CircuitBreaker + FallbackChain) i harmonogram EOD per rynek (NBP 12:35, GPW 18:30, USA 23:15, krypto 00:30) — jak w dokumencie v1, sekcje 3, 7.

Zmienia się tylko ścieżka obliczeń: `holdings` → wycena → snapshot. Zero rekonstrukcji stanu z historii zdarzeń.

---

## 4. Decyzje architektoniczne

### ADR-101: Semantyka historii przy edycji pozycji

**Status:** Proponowana — wymaga akceptacji przed Fazą 1

**Kontekst:** Użytkownik zmienia ilość (dokupił/sprzedał poza aplikacją) albo dodaje nową pozycję. Co z wykresem wartości za poprzednie miesiące?

| Opcja | Złożoność | Zachowanie |
|---|---|---|
| A: Historia „od teraz" — snapshoty są niemutowalne; edycja pozycji wpływa wyłącznie na przyszłe dni | Niska | wykres pokazuje faktyczną historię monitoringu; skok wartości w dniu edycji jest naturalny |
| B: Pozycje z datą obowiązywania (`valid_from`) — historia przeliczalna wstecz | Średnia | wierniejsza przeszłość, ale wraca problem przeliczania ogona i pytań „od kiedy to miałeś" |
| C: Retroaktywnie bieżący koszyk („gdybym zawsze trzymał to co dziś") | Niska | użyteczne jako symulacja, fałszywe jako historia |

**Decyzja:** Opcja A jako domyślna semantyka (snapshoty append-only) + pole `valid_from` w `holdings` już teraz (nullable, domyślnie data dodania), żeby opcja B była możliwa bez migracji łamiącej. Opcja C nigdy jako „historia portfela"; ewentualnie później jako jawnie nazwana symulacja.

**Konsekwencje:** (+) zero mechanizmu `dirty_from`, snapshoty trywialne; (−) dzień edycji pozycji = skok na wykresie — oznaczać znacznikiem „zmiana składu" na osi czasu; (do rewizji) opcja B, jeśli użytkownicy będą chcieli uzupełniać przeszłość.

### ADR-102: Mapowanie rynków i indeksów referencyjnych

**Status:** Proponowana

**Kontekst:** Funkcja „obserwuj rynki, na których inwestuję" wymaga (a) przypisania aktywa do rynku, (b) przypisania rynkowi indeksu.

**Decyzja:** Słownikowa tabela `markets` (kod, nazwa, indeks_asset_id, strefa czasowa, godzina EOD) utrzymywana przez system (kilkanaście wpisów: GPW, NYSE/NASDAQ, LSE, XETRA, krypto...). `assets.market_code` FK do słownika. Indeksy referencyjne to zwykłe `assets` (WIG20, ^SPX, ^NDX, DAX, BTC) pobierane tymi samymi jobami EOD. Ranking rynków = GROUP BY market_code po wycenionych pozycjach. Godziny jobów EOD czytane z tego samego słownika — jedno źródło prawdy o rynkach.

**Konsekwencje:** (+) „Twoje rynki" i harmonogram ingestii spinają się w jednym miejscu; (−) słownik trzeba ręcznie zasiać i utrzymywać (rzadka zmiana).

### Decyzje przeniesione z v1 (obowiązują dalej)

ADR-001 (modularny monolit), ADR-002 (izolacja: zależność aplikacyjna + RLS w Fazie 2 + parametryzowany test dwóch użytkowników w CI), ADR-003 (snapshoty — w wersji uproszczonej: sama wartość, bez kolumny przepływów), ADR-004 (APScheduler w osobnym kontenerze), ADR-005 (własny auth: argon2id, JWT 15 min + rotowany refresh, OAuth Google przez PKCE). ADR-006 (przepływy) — **wycofany, bezprzedmiotowy**.

---

## 5. Model danych

### 5.1 Tabele

- `users`, `refresh_tokens` — jak v1.
- `portfolios` (id, user_id, nazwa, typ) — bez `dirty_from`.
- **`holdings`** (id, portfolio_id, asset_id, ilość NUMERIC(20,8), avg_cost NUMERIC(20,8) null, cost_currency null, valid_from date null, notatka; UNIQUE(portfolio_id, asset_id)).
- `assets` (id, symbol, nazwa, klasa_aktywa, **market_code FK**, waluta, isin, sektor, kraj, region, aktywny) — sektor/kraj/region z yfinance dla akcji, dla ETF przybliżenie + ręczny override użytkownika z etykietą „przybliżone" (jak luka nr 4 z v1).
- **`markets`** (code PK, nazwa, indeks_asset_id FK→assets, timezone, eod_time) — ADR-102.
- `asset_source_map` (asset_id, provider, provider_symbol, priority) — bez zmian, warunek działania fallbacku.
- `prices` (asset_id, date, OHLCV, close_adj; PK(asset_id,date)) — `close_adj` zostaje: bez transakcji splitów w ogóle **wycena i wykresy używają wyłącznie cen skorygowanych** — split u dostawcy nie psuje niczego, o ile użytkownik sam skoryguje ilość (przypomnienie w UI przy wykrytym skoku ceny >40% dnia).
- `fx_rates` (waluta, date, kurs_pln; PK(waluta,date)) — lookup `max(date) <= D`.
- `portfolio_valuations` (portfolio_id, date, value_pln; PK(portfolio_id,date)) — bez kolumny przepływów.
- `watchlists` + `watchlist_items`, `tags` + `asset_tags`, `news` + `news_assets`, `dividend_events`, `ingestion_runs` — jak v1.

### 5.2 Zasady

`NUMERIC`, nigdy float; FK do users z `ON DELETE CASCADE`; kwoty w API jako stringi dziesiętne.

---

## 6. API (różnice względem v1)

Znikają trasy transakcji i importu. Dochodzą:

| Zasób | Endpointy |
|---|---|
| Pozycje | `GET/POST /portfolios/{id}/holdings`, `PATCH/DELETE /holdings/{id}` |
| Struktura | `GET /portfolios/{id}/allocation?by=class\|sector\|geo\|currency\|market`, `GET /portfolios/{id}/concentration` |
| Rynki | `GET /portfolios/{id}/markets` (ranking wg wagi + dane indeksów), `GET /markets/{code}/index?range=` |

Reszta (auth, portfele, `/summary`, `/valuations`, `/risk`, `/performance?benchmark=`, assets/search, watchlisty, tagi, newsy, dywidendy, meta/freshness) — jak v1. `/summary` dodatkowo zwraca skrót „Twoje rynki".

---

## 7. Obliczenia

- **Wycena:** `Σ ilość × close_adj (ostatni) × kurs_pln (ostatni)` per pozycja; agregacje struktury to GROUP BY po atrybutach aktywa. Trywialne, liczone przy zapisie snapshotu i na żądanie z cache.
- **Zwrot portfela:** ze snapshotów `r_t = V_t/V_{t-1} − 1`; przy zmianie składu (ADR-101) dzień edycji wyłączany z serii zwrotów (znacznik `composition_change` w snapshocie), żeby dokupienie nie udawało zysku. To jedyna subtelność silnika.
- **Ryzyko:** zmienność (odch. std × √252), Sharpe (stopa referencyjna NBP, konfigurowalna), max drawdown, beta względem benchmarku — wszystko z tej samej serii `r_t`. Benchmarki i indeksy rynków to zwykłe `assets`.
- **P/L niezrealizowany (opcjonalny):** `(cena_bieżąca_pln − avg_cost_pln) × ilość` tylko dla pozycji z podanym kosztem; UI wyraźnie oddziela pozycje bez kosztu.
- **HHI koncentracji:** `Σ w_i²` po wagach pozycji; prezentowany opisowo (niska/średnia/wysoka koncentracja).

---

## 8. Cache, bezpieczeństwo, PWA, eksploatacja

Bez zmian względem v1 (sekcje 9–12 tamtego dokumentu): klucze wersjonowane w Redis (znacznik = ostatnia edycja holdings + data EOD), argon2id + rotowane refresh tokeny, test izolacji dwóch użytkowników w CI od pierwszego sprintu, Serwist + IndexedDB dla offline-odczytu, Sentry + `ingestion_runs` + alerty, nocny `pg_dump`, docker-compose z Caddy.

---

## 9. Luki i ryzyka (zaktualizowane)

1. **Semantyka historii** — ADR-101, decyzja przed Fazą 1.
2. **Splity** — bez transakcji ilość użytkownika nie koryguje się sama; mitygacja: ceny skorygowane + heurystyka wykrywania splitu z przypomnieniem „sprawdź ilość" (sekcja 5.1).
3. **Sektor/geografia dla ETF** — przybliżenie + ręczny override (jak v1).
4. **Kalendarz dywidend GPW** — bez darmowego API; v1 pokrywa tylko rynki zagraniczne (Finnhub).
5. **Tagowanie newsów po tickerach w RSS** — heurystyka, akceptowana w v1.
6. **Stopa wolna od ryzyka** — konfigurowalna stała, domyślnie stopa NBP.

---

## 10. Droga powrotu do pełnej księgowości

Jeśli kiedyś wrócą transakcje: `holdings` staje się tabelą pochodną (projekcją) z `transactions`, snapshoty dostają kolumnę przepływów, wraca ADR-006. Nic w obecnym schemacie tego nie blokuje — dlatego `valid_from` i `NUMERIC(20,8)` od początku.
