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

---

# Dodatek v3 — rozszerzenia funkcjonalne wynikające z nowej specyfikacji

**Data dodatku:** 2026-08-10  
**Zasada aktualizacji:** niniejszy dodatek **nie zmienia ani nie usuwa** żadnej decyzji, zakresu ani funkcjonalności opisanej powyżej. Rozszerzenia są kolejną warstwą systemu, przeznaczoną do realizacji po obecnej wersji v2.

---

## 11. Rozszerzenie analityki pojedynczego aktywa (Single Asset Analysis)

Obecny projekt posiada wyszukiwanie aktywów, dane cenowe, wykresy oraz newsy. Kolejna warstwa rozszerza to o pełną analizę pojedynczej spółki, ETF-u lub innego instrumentu. Specyfikacja zakłada połączenie analizy fundamentalnej, technicznej i danych kontekstowych w jednym widoku aktywa. fileciteturn1file0L16-L26

### 11.1 Analiza fundamentalna

- Wskaźniki wyceny: **P/E, P/B, EV/EBITDA**.
- Wskaźniki rentowności: **ROE, ROA, marże**.
- Wskaźniki zadłużenia i płynności: **D/E, current ratio**.
- Dynamika przychodów i zysków.
- Historia wybranych wskaźników zamiast wyłącznie wartości bieżącej.
- Porównanie spółki z sektorem oraz własną historią.
- Normalizacja danych historycznych z raportów finansowych.
- Oznaczenie źródła i daty każdej wartości fundamentalnej.

### 11.2 Analiza techniczna

- Średnie kroczące **MA50 / MA200**.
- **RSI, MACD, Stochastic**.
- Wstęgi Bollingera.
- Momentum.
- Analiza wolumenu.
- Automatyczne oznaczanie podstawowego trendu.
- Rozszerzenie istniejących wykresów aktywów o warstwę wskaźników technicznych.
- Integracja z biblioteką wykresową wykorzystywaną już w systemie zamiast budowania osobnego silnika wykresów. fileciteturn1file0L20-L26

### 11.3 Dane fundamentalne i komunikaty

- Obsługa komunikatów **ESPI/EBI** dla aktywów z GPW.
- Powiązanie komunikatów z konkretnym aktywem.
- Historia publikacji wyników i najważniejszych zdarzeń.
- Rozszerzenie istniejącego modułu newsów o źródła pierwotne emitentów.

---

## 12. Market Scanner 2.0

Do istniejącego wyszukiwania aktywów zostaje dopisana warstwa skanera pozwalająca przejść od ręcznego wyszukiwania do systematycznej selekcji instrumentów. Skaner ma zasilać późniejszą analizę portfela, a nie zastępować decyzję użytkownika. fileciteturn1file0L27-L35

### 12.1 Filtry ogólne

- klasa aktywa,
- rynek / giełda,
- sektor,
- kraj / region,
- kapitalizacja,
- P/E, P/B, EV/EBITDA,
- dynamika przychodów i zysków,
- rentowność,
- zadłużenie,
- zmienność,
- płynność,
- momentum / RSI,
- stopa dywidendy.

### 12.2 Predefiniowane widoki skanera

- **Asia Tech Hub** — spółki technologiczne z Azji,
- **LatAm Energy & Materials** — energia i surowce krytyczne w Ameryce Łacińskiej,
- **EU Strategic Autonomy** — sektory obronne i przemysłowe związane z europejską autonomią strategiczną. fileciteturn1file0L27-L35

### 12.3 Zasada projektowa

Skaner nie generuje automatycznej rekomendacji „kup/sprzedaj”. Wynik skanowania prowadzi do widoku **Single Asset Analysis**, a następnie — jeżeli aktywo znajduje się lub trafi do portfela — do analizy jego wpływu na całą strukturę.

---

## 13. Rozszerzenie analityki portfela

Obecne metryki pozostają bez zmian. Do istniejącego modułu ryzyka zostają dopisane dodatkowe statystyki wynikające z nowej specyfikacji oraz wcześniejszego researchu: **CAGR, Sortino, macierz korelacji, analiza struktury oraz wpływ kosztów**. fileciteturn1file5L215-L225

### 13.1 Metryki wyników

- **CAGR** dla pełnych okresów historycznych.
- **Sortino** obok istniejącego Sharpe'a.
- Stopa zwrotu dla okresów: 1M / 3M / 6M / 1R / YTD / MAX.
- Porównanie wyniku portfela z benchmarkiem.
- W dalszej kolejności możliwość rozdzielenia wyniku brutto i netto po uwzględnieniu kosztów.

### 13.2 Macierz korelacji

- Korelacja aktywów w portfelu na podstawie wspólnej historii cen.
- Heatmapa korelacji.
- Możliwość filtrowania po klasie aktywa, rynku i tagach.
- Wykorzystanie korelacji jako dodatkowego sygnału jakości dywersyfikacji, obok HHI i koncentracji.

### 13.3 Koszty i wynik netto

- Ewidencja kosztów funduszu / ETF, w szczególności **TER** jako parametr analityczny.
- Opcjonalna ewidencja prowizji i kosztów przewalutowania.
- Rozdzielenie wyniku brutto i wyniku po kosztach tam, gdzie dane są dostępne.
- Wskaźnik wpływu kosztów na długoterminowy wynik portfela. fileciteturn2file0L11-L22

---

## 14. Look-Through X-Ray — rzeczywista ekspozycja portfela

Kolejna warstwa analizy ma wykrywać sytuację, w której ta sama spółka lub sektor występuje jednocześnie bezpośrednio i poprzez ETF-y. System będzie mógł pokazywać **ekspozycję netto (Total Weight)** zamiast traktowania każdej pozycji jako niezależnej. fileciteturn1file2L121-L125

### 14.1 Zakres

- skład ETF-ów,
- wagi komponentów ETF,
- agregacja ekspozycji bezpośredniej i pośredniej,
- ekspozycja końcowa na spółkę,
- ekspozycja końcowa na sektor,
- ekspozycja końcowa na kraj / region,
- wykrywanie nakładających się ETF-ów.

### 14.2 Przykład

Jeżeli użytkownik posiada akcje spółki X bezpośrednio oraz posiada trzy ETF-y zawierające spółkę X, system pokazuje łączną ekspozycję na X zamiast czterech niezależnych pozycji.

### 14.3 Ograniczenie jakości danych

Look-Through działa tylko dla ETF-ów, dla których dostępny jest wiarygodny skład funduszu. Brak danych nie może być zastępowany zgadywaniem — UI oznacza brak lub przybliżenie danych.

---

## 15. Portfolio Drift, cele alokacji i Smart Alerts

Do obecnej analizy struktury zostaje dopisana warstwa **docelowej alokacji**. Użytkownik może zdefiniować oczekiwane wagi, a system monitoruje odchylenie od celu. Specyfikacja przewiduje Rules Engine oraz alerty po przekroczeniu progów tolerancji. fileciteturn1file2L126-L131

### 15.1 Cele alokacji

Cele mogą być definiowane dla:

- klas aktywów,
- rynków,
- sektorów,
- walut,
- pojedynczych aktywów.

### 15.2 Portfolio Drift

System oblicza:

`drift = waga_aktualna − waga_docelowa`

oraz pokazuje:

- aktualną wagę,
- wagę docelową,
- odchylenie w punktach procentowych,
- próg tolerancji,
- status: OK / obserwuj / przekroczono próg.

### 15.3 Smart Alerts

Przykładowe alerty:

- przekroczenie maksymalnej wagi pozycji,
- zbyt duża ekspozycja na jeden sektor,
- zbyt duża ekspozycja walutowa,
- przekroczenie udziału rynku,
- nietypowy wzrost koncentracji,
- przekroczenie ustalonego drawdownu,
- istotny wzrost korelacji między pozycjami.

Alerty są informacyjne. System nie wykonuje transakcji automatycznie w obecnym zakresie projektu.

---

## 16. Atrybucja walutowa (FX Attribution)

Do istniejącej ekspozycji walutowej zostaje dopisana możliwość rozdzielenia wpływu ceny aktywa i kursu walutowego na wynik. Celem jest pokazanie, jaka część wyniku wynika ze zmiany wartości instrumentu, a jaka ze zmiany PLN względem waluty aktywa. fileciteturn1file1L53-L55

### 16.1 Zakres

- wynik aktywa w walucie lokalnej,
- wynik wynikający z FX,
- wynik końcowy w PLN,
- agregacja wpływu FX dla całego portfela,
- agregacja wg waluty, rynku i klasy aktywa.

### 16.2 Prezentacja

Na poziomie portfela i pozycji użytkownik powinien móc zobaczyć:

`wynik instrumentu + wynik FX = wynik w PLN`

Zachowanie obecnej wyceny w PLN i wykorzystanie kursów NBP pozostaje bez zmian.

---

## 17. Multi-Asset / Net Worth

Jako kolejne rozszerzenie, niezależne od obecnego zakresu giełdowego, system może obsłużyć aktywa, których nie reprezentuje klasyczny ticker giełdowy. Specyfikacja wskazuje na konsolidację aktywów giełdowych z **private assets, nieruchomościami oraz kruszcami**. fileciteturn1file2L108-L118

### 17.1 Nowe typy aktywów

- nieruchomości,
- fizyczne złoto / kruszce,
- aktywa prywatne,
- inne aktywa ręcznie wyceniane.

### 17.2 Zasada wyceny

Aktywa bez bieżącego źródła rynkowego mogą posiadać:

- wartość ręczną,
- datę ostatniej aktualizacji,
- walutę,
- źródło / komentarz wyceny,
- znacznik jakości danych.

Fizyczne złoto może w przyszłości korzystać z ceny spot.

---

## 18. Powrót do pełnej księgowości i moduł podatkowy — przyszła warstwa

Niniejsza sekcja **nie zmienia decyzji o obecnym braku rejestru transakcji**. Jest wyłącznie przyszłą ścieżką rozwoju zgodną z istniejącą sekcją 10 oraz nową specyfikacją.

Po ewentualnym przywróceniu transakcji można dodać:

- rejestr wpłat i wypłat,
- FIFO,
- TWR,
- XIRR,
- zrealizowany P/L,
- historię kosztów nabycia,
- kurs NBP z odpowiedniej daty,
- PIT-38,
- rozliczanie dywidend i podatku u źródła. fileciteturn1file1L56-L68

Moduł podatkowy powinien być osobną warstwą domenową i nie może zmieniać semantyki obecnych snapshotów portfela.

---

## 19. Opportunity Cost Calculator

Kolejne rozszerzenie analityczne pokazuje długoterminowy wpływ kosztów, prowizji i przewalutowania. Specyfikacja wskazuje możliwość symulowania utraconego kapitału wynikającego z pozornie niewielkich kosztów. fileciteturn1file1L65-L68

### 19.1 Dane wejściowe

- kapitał początkowy,
- okres inwestycji,
- oczekiwana stopa zwrotu,
- opłata roczna,
- prowizja,
- koszt przewalutowania,
- częstotliwość kosztu.

### 19.2 Wynik

- kapitał bez kosztów,
- kapitał po kosztach,
- łączny koszt alternatywny,
- różnica procentowa,
- wykres wpływu kosztów w czasie.

---

## 20. Symulacje i scenariusze

Do modułu ryzyka zostaje dopisana możliwość symulacji przyszłej wartości portfela. Wynik powinien być prezentowany jako **rozkład / przedział niepewności**, a nie jako pojedyncza prognoza. fileciteturn1file4L184-L194

### 20.1 Monte Carlo

- symulacja wielu ścieżek,
- mediana,
- percentyle,
- przedział niepewności,
- scenariusze pesymistyczny / bazowy / optymistyczny,
- możliwość wykorzystania historycznej zmienności i korelacji portfela.

### 20.2 Zasada prezentacji

System nie powinien przedstawiać wyniku Monte Carlo jako pewnej prognozy. Każda symulacja musi zawierać informację o założeniach i niepewności.

---

## 21. Conversational BI i warstwa AI

Do istniejącego dashboardu zostaje dopisana warstwa pytań w języku naturalnym. Specyfikacja przewiduje możliwość zadawania pytań dotyczących przyczyn zmian wyniku oraz przechodzenia z KPI do szczegółów. fileciteturn1file4L184-L194

### 21.1 Przykładowe pytania

- „Dlaczego portfel spadł dzisiaj?”
- „Które aktywa odpowiadają za największą część ryzyka?”
- „Jak zmieniła się moja ekspozycja na USA?”
- „Które pozycje najbardziej zwiększają koncentrację?”
- „Ile mojego wyniku wynika z USD?”
- „Które aktywa mają najwyższą korelację?”

### 21.2 Zasada bezpieczeństwa

Warstwa AI nie może wymyślać danych. Odpowiedź musi być generowana wyłącznie na podstawie danych dostępnych w systemie i wskazywać źródło / zakres danych użyty do wyliczenia.

---

## 22. Standard dashboardu i UX — rozszerzenie

Obecny dashboard pozostaje bez zmian funkcjonalnych. Dodatkowo obowiązują następujące zasady dla nowych widoków:

1. **Reguła 5–7 KPI** na głównym ekranie.
2. **One-click drill-down** z KPI do danych składowych.
3. Czytelne oznaczenie danych przybliżonych, niepełnych i nieaktualnych.
4. Paleta przyjazna dla osób z zaburzeniami rozpoznawania kolorów.
5. Czerwony / zielony wyłącznie jako sygnał anomalii lub kierunku zmiany, a nie jako jedyne źródło informacji.
6. Każdy wykres powinien odpowiadać na konkretne pytanie analityczne, a nie być wyłącznie wizualizacją danych. fileciteturn1file4L184-L194

---

## 23. Źródła danych i warstwa analityczna — rozszerzenie

Obecna architektura DataProvider pozostaje obowiązująca. W kolejnych modułach można dodać źródła wspierające analizę fundamentalną, makroekonomiczną i sentymentową. W researchu jako darmowe źródła wskazano m.in. Yahoo Finance, Google Finance, Stooq, Investing.com, GPW, KNF, GUS, NBP i FRED. fileciteturn2file1L63-L69

### 23.1 Zasada hierarchii źródeł

1. źródło oficjalne / pierwotne,
2. źródło giełdowe lub regulator,
3. dostawca danych agregowanych,
4. źródło pomocnicze / społecznościowe.

Dane z niższej warstwy nie powinny nadpisywać danych z wyższym priorytetem bez jawnej reguły.

### 23.2 Analiza fundamentalna — źródła

- raporty okresowe emitentów,
- GPW / ESPI,
- KNF,
- Yahoo Finance / yfinance,
- Stooq,
- Macrotrends dla danych historycznych spółek USA,
- Google Sheets / GOOGLEFINANCE jako narzędzie pomocnicze. fileciteturn2file3L94-L105

### 23.3 Analiza makro

- NBP,
- GUS,
- FED / FRED,
- ECB,
- OECD / IMF,
- kalendarze makro jako źródło pomocnicze.

### 23.4 Sentyment

W późniejszej fazie można agregować:

- newsy,
- komunikaty spółek,
- indeksy nastrojów,
- wybrane źródła społecznościowe,
- Google Trends jako sygnał pomocniczy.

Sentyment nie powinien być traktowany jako samodzielny sygnał inwestycyjny. fileciteturn2file1L45-L60

---

## 24. Zasada priorytetyzacji rozszerzeń

Rozszerzenia realizować warstwowo:

1. **Analiza pojedynczego aktywa** — fundamentalna + techniczna.
2. **Market Scanner 2.0**.
3. **CAGR / Sortino / korelacje / koszty**.
4. **Look-Through X-Ray**.
5. **Portfolio Drift + Smart Alerts**.
6. **Atrybucja FX**.
7. **Multi-Asset / Net Worth**.
8. **Opportunity Cost + scenariusze / Monte Carlo**.
9. **Conversational BI / AI**.
10. **Pełna księgowość + podatki** wyłącznie po ewentualnym przywróceniu rejestru transakcji.

Macierz priorytetyzacji z nowej specyfikacji rozdziela część funkcjonalności na MVP i PRO; w naszym projekcie kolejność powyżej zachowuje obecne MVP v2 i dopiero później dokłada warstwę zaawansowaną. fileciteturn1file4L195-L204

---

## 25. Kompatybilność z obecną architekturą

Nowe funkcje powinny być dokładane jako moduły, bez zmiany podstawowego przepływu:

`holdings → wycena → snapshot → analityka`

Do tego przepływu mogą zostać dołączone kolejne warstwy:

`market data → single asset analysis → scanner`

`portfolio snapshot → risk → correlation → attribution → alerts`

`ETF composition → look-through → net exposure`

`transactions (future) → FIFO/TWR/XIRR/tax`

Obecne decyzje dotyczące FastAPI, PostgreSQL, Redis, Next.js PWA, DataProvider, workerów EOD, snapshotów append-only, izolacji danych i `NUMERIC` pozostają obowiązujące.

---

## 26. Nowe luki i ryzyka

1. **Jakość danych fundamentalnych** — różne źródła mogą podawać różne definicje wskaźników.
2. **Skład ETF** — dane look-through mogą być opóźnione lub niepełne.
3. **Atrybucja FX** — wymaga jednoznacznej definicji okresu i bazowego kursu walutowego.
4. **Korelacje** — zależą od wybranego okna czasowego i częstotliwości danych.
5. **Smart Alerts** — zbyt wiele alertów może prowadzić do „alert fatigue”; progi muszą być konfigurowalne.
6. **Monte Carlo** — wynik zależy od założeń statystycznych i nie może być prezentowany jako gwarantowana prognoza.
7. **AI / Conversational BI** — ryzyko halucynacji; odpowiedzi muszą być oparte na danych systemowych.
8. **Dane prywatnych aktywów** — ręczne wyceny mogą być nieaktualne i wymagają oznaczenia daty oraz źródła.
9. **Moduł podatkowy** — wymaga osobnej walidacji prawnej i podatkowej przed użyciem produkcyjnym.
10. **Koszty i podatki** — wynik netto wymaga pełnego modelu kosztów, który w obecnej wersji bez transakcji nie jest dostępny.

---

## 27. Docelowa wizja systemu

Docelowo system pozostaje przede wszystkim **systemem analityczno-monitoringowym**, a nie automatycznym systemem transakcyjnym. Jego rozwój prowadzi od prostego monitorowania pozycji do:

`pozycje → wycena → struktura → ryzyko → analiza aktywa → rzeczywista ekspozycja → cele i alerty → scenariusze → decyzja użytkownika`

Ewentualne automatyzowanie wykonania transakcji pozostaje poza obecnym zakresem i może być rozpatrywane dopiero po zbudowaniu oraz zweryfikowaniu całej warstwy analitycznej.
