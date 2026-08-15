# CLAUDE.md — instrukcja pracy nad projektem „AlphaSense"

Ten plik czytasz automatycznie przy każdej sesji. Traktuj go jako nadrzędny wobec własnych domyślnych nawyków.

## 1. Czym jest ten projekt

Aplikacja webowa (PWA) do **monitoringu i analizy składu portfela inwestycyjnego**. Użytkownik wpisuje posiadane aktywa (pozycje), system je wycenia w PLN, rozkłada portfel na klasy/sektory/geografię/waluty/rynki i pozwala obserwować indeksy rynków, na których użytkownik jest zainwestowany.

**Serce produktu to analityka struktury i ranking rynków — nie księgowość.**

Aktualny zakres v2 nadal świadomie NIE obejmuje rejestru transakcji, FIFO, zrealizowanego P/L, XIRR/TWR z przepływami, importu CSV od brokerów ani rozliczeń podatkowych. Te funkcje zostały odsunięte do osobnego, przyszłego Etapu 21 i **nie wolno ich implementować w ramach v2 ani Etapów 0–20 bez jawnej decyzji użytkownika o zmianie zakresu**.

Rozszerzenia po v2 są opisane w `docs/plan-dzialania-portfel-v3.md` i obejmują m.in. Single Asset Analysis, Market Scanner 2.0, zaawansowane statystyki, Look-Through X-Ray, rebalancing, atrybucję FX, Multi-Asset / Net Worth, Opportunity Cost, Monte Carlo, Conversational BI oraz rozszerzenia UX/Data Literacy.

Dokumenty źródłowe (czytaj zanim zaczniesz kodzić w nowym obszarze):

- `docs/projekt-systemu-portfel-v2.md` — projekt systemu (architektura, model danych, obliczenia)
- `docs/plan-dzialania-portfel-v2.md` — plan 50 kroków w 10 etapach
- `docs/projekt-systemu-portfel-v3.md` — **dalsze rozszerzenia funkcjonalne po v2**; nie zastępuje v2, tylko je rozszerza
- `docs/plan-dzialania-portfel-v3.md` — **Etapy 10–23**, dopisywane po istniejącym planie
- `docs/adr` — decyzje architektoniczne (ADR-101, ADR-102 i przeniesione z v1)
- `docs/model-danych.md`, `docs/api-kontrakt.md`, `docs/konwencje.md`, `docs/slownik-rynkow.md`
- `../STATUS.md` — **gdzie aktualnie jesteśmy** i co jest następne

## 2. Stack

| Warstwa  | Technologia                                                               |
| -------- | ------------------------------------------------------------------------- |
| Backend  | Python 3.12, FastAPI, SQLAlchemy 2.x (async), Pydantic v2, Alembic        |
| Baza     | PostgreSQL 16                                                             |
| Cache    | Redis 7 (czysty cache, nigdy źródło prawdy)                               |
| Worker   | osobny kontener, APScheduler + blokady doradcze Postgresa                 |
| Frontend | Next.js (App Router) + TypeScript + TanStack Query + Tailwind             |
| Wykresy  | ECharts (portfel, struktura), Lightweight Charts (świece)                 |
| Proxy    | Caddy (TLS automatyczny)                                                  |
| Infra    | docker-compose na jednym VPS                                              |
| Testy    | pytest + pytest-asyncio + httpx (backend), Vitest + Playwright (frontend) |

## 3. Zasady, które łamiesz tylko po jawnej zgodzie użytkownika

1. **Kwoty i ilości:** **`NUMERIC(20,8)`** **w bazie,** **`Decimal`** **w Pythonie,** **`string`** **w JSON. Nigdy** **`float`****.**
2. **Żaden endpoint nie przyjmuje „gołego" ID z path.** Zawsze przez zależność `get_owned_portfolio` / `get_owned_holding`, która weryfikuje własność względem `current_user`. Zobacz skill `izolacja-danych`.
3. **Snapshoty są append-only** (ADR-101, opcja A). Edycja pozycji wpływa tylko na przyszłość. Nie buduj mechanizmu przeliczania historii.
4. **Wycena i wykresy zawsze na** **`close_adj`**, nigdy na surowym `close`.
5. **Kursy walut wyłącznie z NBP**, lookup `max(date) <= D` (cofanie do ostatniego dnia roboczego).
6. **Godziny jobów EOD czytasz ze słownika** **`markets`**, nie z hardkodu w kodzie workera (ADR-102).
7. **Redis można w każdej chwili wyczyścić** i aplikacja musi działać. Klucze wersjonowane: `{zasób}:{portfolio_id}:{ostatnia_edycja_holdings}:{data_eod}`.
8. **Migracja Alembic do każdej zmiany modelu**, w tym samym commicie. Nigdy `create_all()` w produkcji.
9. **Nie commituj sekretów.** Konfiguracja przez zmienne środowiskowe (pydantic-settings), wzorzec w `.env.example`.
10. **Każdy nowy endpoint dostaje test izolacji dwóch użytkowników** — parametryzowany test w CI ma go złapać automatycznie.
11. **Nie rozszerzaj v2 „przy okazji”.** Funkcje z Etapów 10–23 wdrażaj tylko jako osobne, zaplanowane rozszerzenia i zachowuj istniejący kontrakt v2, chyba że zmiana została jawnie zaakceptowana.
12. **Nie przywracaj transakcji w ramach v2.** Model `transactions`, FIFO, TWR/XIRR, zrealizowany P/L i podatki należą do Etapu 21 i wymagają osobnej decyzji o zmianie zakresu.
13. **AI nie jest źródłem prawdy.** Conversational BI może interpretować i objaśniać dane istniejących endpointów, ale nie może wymyślać danych, wyników ani brakujących wartości.
14. **Symulacje nie są prognozami gwarantowanymi.** Monte Carlo musi prezentować założenia, okres danych i przedziały niepewności.
15. **Dane przybliżone i niepełne muszą być oznaczane.** Nie przedstawiaj przybliżenia ETF, starej wyceny ręcznej ani niepełnego look-through jako danych dokładnych.

## 4. Jak pracujesz (pętla)

Przy każdym zadaniu:

1. **Zorientuj się** — przeczytaj `../STATUS.md`, znajdź numer kroku z planu, którego dotyczy zadanie.
2. **Zaplanuj** — rozpisz plan w TODO. Jeśli krok z planu jest większy niż ~1 dzień pracy, podziel go.
3. **Wykonaj** — najmniejsza zmiana, która domyka krok. Nie robisz „przy okazji" refaktorów w innych modułach.
4. **Zweryfikuj** — uruchom `make check` (lint + typy + testy backendu + build frontendu). Zielone albo nie kończysz.
5. **Zapisz** — zaktualizuj `../STATUS.md` (krok → zrobiony, notatki, co blokuje) i, jeśli podjęto decyzję architektoniczną, dopisz ADR w `docs/adr`.
6. **Podsumuj** — krótko: co zrobione, co dalej, co wymaga decyzji użytkownika.

**Każdy etap kończy się czymś działającym.** Jeśli po twojej zmianie `docker compose up` nie wstaje — nie skończyłeś.

Przy rozszerzeniach po v2 dodatkowo:

- najpierw sprawdź, czy dana funkcja nie narusza obecnego modelu `holdings → wycena → snapshot → analityka`;
- nowe dane zapisuj z informacją o źródle, dacie pobrania i świeżości, jeśli dana funkcja tego wymaga;
- każdą nową metrykę przetestuj na ręcznie policzonych przypadkach referencyjnych;
- przy funkcjach AI najpierw buduj deterministyczne endpointy/analitykę, dopiero potem warstwę języka naturalnego;
- przy zmianach modelu danych dodaj migrację Alembic i testy kompatybilności z istniejącym v2.

## 5. Kolejność etapów (nie przeskakuj)

### Obecny plan v2

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

### Rozszerzenia po stabilnym v2

```
10. Single Asset Analysis       → fundamentalna + techniczna analiza aktywa
11. Market Scanner 2.0          → screening fundamentalny/techniczny/rynkowy
12. Zaawansowane statystyki     → CAGR, Sortino, korelacje, koszty
13. Look-Through X-Ray          → rzeczywista ekspozycja / net exposure
14. Portfolio Drift + Alerts    → cele, drift, Smart Alerts
15. Atrybucja FX                → wynik instrumentu vs wpływ waluty
16. Multi-Asset / Net Worth     → nieruchomości, złoto, private assets, aktywa ręczne
17. Opportunity Cost            → wpływ opłat i przewalutowania
18. Scenariusze + Monte Carlo   → ścieżki, percentyle, przedziały niepewności
19. Conversational BI / AI      → pytania naturalnym językiem + drill-down
20. UX / Data Literacy          → 5–7 KPI, accessibility, oznaczenia jakości danych
21. Transakcje + podatki        → TYLKO po osobnej decyzji o zmianie zakresu
22. Jakość danych               → ciągła walidacja źródeł i metryk
23. Early Beta / feedback       → po stabilnym v2, iteracja na podstawie użycia
```

**Nie przeskakuj do Etapów 10–23, jeśli odpowiadający im fundament v2 nie jest stabilny.** W szczególności Etap 13 wymaga wiarygodnego modelu aktywów/ETF, Etap 15 wymaga poprawnej wyceny walutowej, Etap 19 wymaga działającej analityki deterministycznej, a Etap 21 wymaga osobnej decyzji o powrocie do transakcji.

Największe ryzyko v2 pozostaje **etap 4** (jakość darmowych źródeł) i **etap 6** (tu powstaje wartość). W rozszerzeniach największe ryzyka to jakość danych fundamentalnych/ETF, poprawność look-through i interpretowalność zaawansowanych metryk.

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
  worker/          scheduler.py, jobs/ (ten sam obraz Dockera co API, inny `command:` w compose)
  alembic/versions/
  tests/           unit/, integration/, test_isolation.py
frontend/
  app/             App Router: (auth)/, dashboard/, portfel/, rynki/, struktura/
  components/      ui/, charts/, forms/
  lib/             api client, query keys, formatery Decimal
docs/              projekt, plan, adr/, konwencje, model danych, kontrakt API
.claude/           agents/, commands/, skills/
```

Wraz z późniejszymi etapami można rozszerzyć moduły, ale nie zmieniaj istniejącego układu bez potrzeby. Preferowane rozszerzenia to m.in. `analytics/fundamental.py`, `analytics/technical.py`, `analytics/correlation.py`, `analytics/xray.py`, `analytics/rebalancing.py`, `analytics/fx.py`, `analytics/scenarios.py` oraz odpowiednie moduły danych i API.

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

**Testy:** każdy endpoint — test szczęśliwej ścieżki + test 404 dla obcego zasobu (nie zdradzamy istnienia zasobu innego użytkownika, patrz skill `izolacja-danych`). Logika obliczeniowa (wycena, HHI, zwroty, drawdown, a później CAGR/Sortino/FX/X-Ray/Monte Carlo) — testy jednostkowe na znanych liczbach, bez mocków bazy tam, gdzie obliczenie jest czysto matematyczne.

Dla nowych źródeł danych testuj także:

- świeżość i datę danych,
- poprawność fallbacku,
- oznaczenie danych przybliżonych/niepełnych,
- zachowanie przy braku danych,
- deterministyczność obliczeń.

## 9. Język

Rozmowa z użytkownikiem, dokumentacja, ADR-y, komunikaty UI: **polski**.
Kod, nazwy zmiennych, tabel, endpointów, commity: **angielski**.

## 10. Kiedy pytać, a kiedy działać

**Działaj bez pytania:** implementacja kroku z planu, testy, migracje wynikające z modelu, poprawki lintera, uzupełnianie dokumentacji.

**Zapytaj:** zmiana zakresu (szczególnie powrót do transakcji), zmiana ADR, dodanie zależności zewnętrznej, dodanie płatnego źródła danych, zmiana schematu, która wymaga migracji łamiącej, cokolwiek co dotyka pieniędzy użytkownika lub bezpieczeństwa auth.

Przy Etapach 10–20 działaj zgodnie z zatwierdzonym planem v3, o ile implementacja mieści się w opisanym zakresie. Przy Etapie 21 **zawsze zapytaj o jawną decyzję o zmianie zakresu**, nawet jeśli technicznie da się go rozpocząć bez niej.

---

# Dodatek — zasady rozszerzeń po v2

## 11. Single Asset Analysis

Analiza pojedynczego aktywa ma łączyć dane fundamentalne, techniczne, rynkowe i kontekst informacyjny. Minimalny zakres obejmuje m.in. P/E, P/B, EV/EBITDA, ROE, ROA, marże, D/E, current ratio oraz dynamikę przychodów i zysków. Analiza techniczna obejmuje MA50/MA200, RSI, MACD, Stochastic, Bollinger Bands, momentum i wolumen.

Dane fundamentalne muszą mieć datę raportu i datę pobrania. Komunikaty ESPI/EBI powinny być powiązane z aktywem. Wynik analizy nie jest automatyczną rekomendacją kupna/sprzedaży.

## 12. Market Scanner 2.0

Scanner ma filtrować aktywa po danych fundamentalnych, technicznych i rynkowych. Obsługuj m.in. klasę aktywa, rynek, sektor, kraj, kapitalizację, płynność, zmienność, P/E, P/B, EV/EBITDA, rentowność, zadłużenie, dynamikę, dywidendę, MA50/MA200, RSI i momentum.

Presety użytkownika oraz widoki `Asia Tech Hub`, `LatAm Energy & Materials` i `EU Strategic Autonomy` są częścią późniejszego zakresu. Scanner prowadzi do Single Asset Analysis, nie do automatycznej decyzji inwestycyjnej.

## 13. Zaawansowane statystyki portfela

Dodawaj CAGR, Sortino, macierz korelacji i analizę kosztów bez usuwania istniejących metryk. Obecna semantyka zwrotów ze snapshotów pozostaje źródłem prawdy dla v2.

## 14. Look-Through X-Ray / Net Exposure

ETF może być rozwijany do jego komponentów. System ma umieć policzyć ekspozycję bezpośrednią + pośrednią oraz wykrywać nakładanie się ETF-ów. Niepełny lub przybliżony skład ETF musi być oznaczony.

## 15. Portfolio Drift i Smart Alerts

System może posiadać wagi docelowe dla klas aktywów, rynków, sektorów, walut i pojedynczych pozycji. Rules Engine oblicza drift i generuje alerty dotyczące driftu, koncentracji, FX, drawdownu i nietypowych zmian.

**Nie wykonuj automatycznie zleceń.** System może przedstawić propozycję działania, ale wykonanie transakcji nie należy do obecnego zakresu.

## 16. Atrybucja FX

Rozdzielaj zmianę wartości instrumentu w walucie lokalnej od wpływu kursu PLN. Pokazuj wynik instrumentu oraz wynik walutowy per pozycja i agreguj go wg waluty, rynku i klasy aktywa.

## 17. Multi-Asset / Net Worth

Rozszerzenie może obejmować aktywa bez tickerów: nieruchomości, fizyczne złoto, private assets i inne aktywa ręczne. Każda ręczna wycena powinna mieć datę, walutę, źródło/komentarz i informację o świeżości.

## 18. Opportunity Cost

Kalkulator ma pokazywać wpływ prowizji, kosztów przewalutowania, kosztów rocznych i jednorazowych na wynik długoterminowy. Wynik powinien być prezentowany jako różnica kapitału przed i po kosztach oraz utracony kapitał w czasie.

## 19. Scenariusze i Monte Carlo

Symulacje mają korzystać z jawnych danych wejściowych i założeń. Prezentuj wiele ścieżek, medianę oraz percentyle/przedziały niepewności. Każdy wynik oznaczaj okresem danych i założeniami. Nigdy nie przedstawiaj Monte Carlo jako gwarantowanej prognozy.

## 20. Conversational BI / AI Analytics

Warstwa AI działa **nad istniejącą analityką**, a nie zamiast niej. Pytania naturalnym językiem mogą dotyczyć wyniku, ryzyka, koncentracji, FX, ekspozycji i zmian portfela.

AI:

- korzysta wyłącznie z danych dostępnych użytkownikowi;
- respektuje istniejącą izolację danych;
- powinno zwracać kontekst obliczenia;
- musi jasno zgłaszać brak danych;
- nie może wymyślać wartości ani rekomendacji opartych na brakujących danych;
- powinno umożliwiać one-click drill-down do źródłowego widoku/KPI.

## 21. UX i Data Literacy

Główny dashboard powinien utrzymywać zasadę **5–7 KPI**. Każdy KPI powinien prowadzić do szczegółów. Dane przybliżone, nieaktualne i niepełne muszą być widocznie oznaczone.

Accessibility jest wymaganiem funkcjonalnym: nie używaj czerwonego/zielonego jako jedynego kanału informacji. Każda nowa wizualizacja musi mieć jasno określone pytanie analityczne, na które odpowiada.

## 22. Transakcje i podatki — odroczony zakres

Ten zakres nadal jest **poza v2**. Dopiero po jawnej decyzji użytkownika można rozpocząć model `transactions`, projekcję `holdings`, przepływy pieniężne, FIFO, TWR, XIRR, zrealizowany P/L, historyczne kursy NBP wymagane do rozliczeń, PIT-38, dywidendy i withholding tax.

Nie dodawaj żadnego z tych elementów „na zapas" do v2.

## 23. Jakość danych i źródła

Dla każdego nowego źródła zachowuj provider, czas pobrania i świeżość danych. Utrzymuj `RateLimiter`, `CircuitBreaker` i `FallbackChain`. Preferuj źródła oficjalne/pierwotne przed agregatorami.

Dla danych fundamentalnych przechowuj datę raportu i pobrania. Dla ETF przechowuj datę składu. Dla danych makro przechowuj serię, jednostkę i źródło. W UI oznaczaj przybliżenia i brak danych.

## 24. Early Beta i feedback

Stabilne v2 ma zostać uruchomione przed dokładaniem funkcji AI i automatyzacji. Feedback użytkowników służy do ustalania kolejności kolejnych rozszerzeń, ale nie może prowadzić do chaotycznego naruszania fundamentu v2.

Najpierw poprawiaj jakość danych i interpretowalność, dopiero później zwiększaj automatyzację.

---

## Zasada nadrzędna

**Nie zmieniaj istniejącego projektu v2 ani planu Etapów 0–9.** Wszystkie Etapy 10–23 są rozszerzeniami dopisywanymi po istniejącym zakresie. Nie usuwaj istniejących funkcji, nie przenoś etapów i nie przywracaj rejestru transakcji w ramach v2.

Jeśli implementujesz rozszerzenie, zachowuj istniejące ADR-y, model snapshotów, izolację danych, DataProvider, cache i obecny przepływ:

`holdings → wycena → snapshot → analityka`

Każda zmiana, która wymaga odejścia od tej zasady albo wejścia w transakcje/księgowość/podatki, wymaga osobnej decyzji użytkownika.
