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

---

# Dodatek v3 — dalszy plan rozwoju po Etapie 9

**Data dodatku:** 2026-08-10  
**Zasada aktualizacji:** poniższe etapy są dopisywane do istniejącego planu. **Etapy 0–9, ich kolejność, zakres i harmonogram pozostają bez zmian.** Nowe funkcjonalności realizować dopiero po działającym v2.

---

## Etap 10 — Single Asset Analysis (ok. 5–7 dni)

51. Przygotować model danych dla metadanych fundamentalnych i okresowych wartości wskaźników.
52. Rozszerzyć `DataProvider` o źródła danych fundamentalnych z zachowaniem istniejącego `FallbackChain`.
53. Dodać endpoint szczegółów aktywa: cena, zmiana, dane podstawowe, ryzyko, metadane i źródła danych.
54. Dodać wskaźniki fundamentalne: P/E, P/B, EV/EBITDA, ROE, ROA, marże, D/E, current ratio oraz dynamikę przychodów i zysków.
55. Dodać historię wybranych wskaźników i możliwość porównania z sektorem.
56. Rozszerzyć wykresy aktywów o MA50, MA200, RSI, MACD, Stochastic, Bollinger Bands, momentum i wolumen.
57. Dodać komunikaty ESPI/EBI oraz powiązanie ich z aktywem.
58. Oznaczać datę i źródło danych fundamentalnych.

---

## Etap 11 — Market Scanner 2.0 (ok. 4–6 dni)

59. Zbudować endpoint skanera z filtrami fundamentalnymi, technicznymi i rynkowymi.
60. Dodać filtrowanie po klasie aktywa, rynku, sektorze, kraju, kapitalizacji, płynności i zmienności.
61. Dodać filtry P/E, P/B, EV/EBITDA, rentowności, zadłużenia, dynamiki oraz dywidendy.
62. Dodać filtry MA50/MA200, RSI, momentum i podstawowe sygnały techniczne.
63. Zaimplementować zapisane skany / presety użytkownika.
64. Dodać predefiniowane widoki: Asia Tech Hub, LatAm Energy & Materials, EU Strategic Autonomy.
65. Wynik skanera prowadzi do Single Asset Analysis, a nie bezpośrednio do automatycznej rekomendacji.

---

## Etap 12 — Zaawansowane statystyki portfela (ok. 3–5 dni)

66. Dodać CAGR dla dostępnych pełnych okresów.
67. Dodać Sortino obok istniejącego Sharpe'a.
68. Dodać macierz korelacji aktywów i heatmapę korelacji.
69. Umożliwić filtrowanie korelacji po tagach, klasach aktywów i rynkach.
70. Dodać analizę wpływu kosztów / TER tam, gdzie dane są dostępne.
71. Przygotować podstawę pod rozdzielenie wyniku brutto i netto w przyszłej wersji z pełnym modelem kosztów.
72. Zachować obecne metryki i sposób liczenia zwrotów ze snapshotów.

---

## Etap 13 — Look-Through X-Ray / Net Exposure (ok. 6–10 dni)

73. Zaprojektować model składu ETF i wersjonowania jego komponentów.
74. Dodać źródło danych o składzie ETF z oznaczeniem daty obowiązywania.
75. Obliczać ekspozycję portfela na pojedynczą spółkę przez wszystkie posiadane ETF-y.
76. Agregować ekspozycję bezpośrednią i pośrednią.
77. Dodać net exposure dla sektorów, krajów i regionów.
78. Wykrywać nakładanie się ETF-ów.
79. Oznaczać niepełny lub przybliżony look-through.
80. Dodać widok „rzeczywista ekspozycja” jako rozwinięcie istniejącej analizy struktury.

---

## Etap 14 — Portfolio Drift i Smart Alerts (ok. 4–6 dni)

81. Dodać możliwość ustawiania docelowych wag portfela.
82. Obsłużyć cele dla klas aktywów, rynków, sektorów, walut i pojedynczych pozycji.
83. Obliczać drift względem wagi docelowej.
84. Dodać konfigurowalne progi tolerancji.
85. Zaimplementować Rules Engine dla alertów koncentracji, driftu, FX, drawdownu i nietypowych zmian.
86. Dodać centrum alertów z priorytetami i historią.
87. Nie wykonywać automatycznie zleceń — system generuje informację i ewentualną propozycję działania.

---

## Etap 15 — Atrybucja FX (ok. 3–5 dni)

88. Rozdzielić zmianę wartości instrumentu w walucie lokalnej od wpływu kursu walutowego.
89. Obliczać wynik FX per pozycja.
90. Agregować wpływ FX wg waluty, rynku i klasy aktywa.
91. Dodać widok „wynik instrumentu vs wynik walutowy”.
92. Zweryfikować obliczenia na scenariuszach testowych PLN/USD, PLN/EUR i innych walut.

---

## Etap 16 — Multi-Asset / Net Worth (ok. 5–8 dni)

93. Dodać typy aktywów bez tickerów: nieruchomość, fizyczne złoto, private asset, inne aktywo ręczne.
94. Dodać ręczną wycenę z datą, walutą i źródłem / komentarzem.
95. Dodać znacznik świeżości ręcznej wyceny.
96. Rozszerzyć dashboard o łączny Net Worth.
97. Oddzielić aktywa giełdowe od aktywów ręcznie wycenianych.
98. Przygotować integrację ceny spot złota jako osobne źródło danych w późniejszym kroku.

---

## Etap 17 — Opportunity Cost i koszty (ok. 3–4 dni)

99. Zbudować kalkulator wpływu opłat i kosztów przewalutowania.
100. Obsłużyć scenariusze z kosztem rocznym, jednorazowym i procentowym.
101. Pokazywać kapitał przed i po kosztach.
102. Dodać wykres utraconego kapitału w czasie.
103. Powiązać kalkulator z TER ETF-ów, jeśli dane są dostępne.

---

## Etap 18 — Scenariusze i Monte Carlo (ok. 5–8 dni)

104. Zbudować moduł symulacji scenariuszowych.
105. Wykorzystać historyczną zmienność i — gdy dostępna — korelację aktywów.
106. Dodać Monte Carlo z wieloma ścieżkami.
107. Prezentować medianę oraz percentyle / przedziały niepewności.
108. Dodać scenariusze pesymistyczny / bazowy / optymistyczny.
109. Każdy wynik oznaczać założeniami i okresem danych wejściowych.
110. Nie prezentować symulacji jako gwarantowanej prognozy.

---

## Etap 19 — Conversational BI / AI Analytics (ok. 5–10 dni)

111. Zbudować warstwę zapytań natural-language nad istniejącymi endpointami analitycznymi.
112. Ograniczyć dostęp AI do danych użytkownika po istniejącej warstwie autoryzacji.
113. Dodać pytania o wynik, ryzyko, koncentrację, FX, ekspozycję i zmiany portfela.
114. Dodać one-click drill-down z odpowiedzi AI do odpowiedniego widoku danych.
115. Każdą odpowiedź oprzeć na danych systemowych i zwracać kontekst obliczenia.
116. Dodać mechanizm wykrywania braku danych zamiast generowania odpowiedzi na podstawie domysłu.
117. Przetestować odpowiedzi na scenariuszach błędnych / niepełnych danych.

---

## Etap 20 — Rozszerzenie UX i Data Literacy (ok. 3–5 dni)

118. Ograniczyć główny dashboard do 5–7 najważniejszych KPI.
119. Ujednolicić one-click drill-down dla nowych KPI.
120. Oznaczać dane przybliżone, nieaktualne i niepełne.
121. Przejrzeć kontrast i paletę pod kątem accessibility.
122. Nie używać czerwonego / zielonego jako jedynego sposobu przekazywania informacji.
123. Dla każdej nowej wizualizacji określić pytanie analityczne, na które odpowiada.

---

## Etap 21 — Powrót do pełnej księgowości i podatków — tylko jeśli decyzja o transakcjach zostanie zmieniona

124. Nie rozpoczynać tego etapu w obecnym zakresie v2.
125. Jeżeli projekt wróci do transakcji, rozpocząć od modelu `transactions` i projekcji `holdings`.
126. Przywrócić przepływy pieniężne oraz mechanizm historii zgodnie z istniejącą sekcją 10 projektu.
127. Dodać FIFO.
128. Dodać TWR i XIRR.
129. Dodać zrealizowany P/L.
130. Dodać historyczne kursy NBP wymagane do rozliczeń.
131. Dodać przygotowanie danych do PIT-38.
132. Dodać rozliczanie dywidend i podatku u źródła.
133. Zweryfikować moduł podatkowy przed produkcyjnym użyciem.

---

## Etap 22 — Weryfikacja źródeł danych i jakość analityki (ciągłe, od Etapu 10)

134. Dla każdego nowego źródła zachować informację o providerze, czasie pobrania i świeżości danych.
135. Utrzymać istniejący `RateLimiter`, `CircuitBreaker` i `FallbackChain`.
136. Preferować źródła oficjalne / pierwotne przed agregatorami.
137. Dla fundamentalnych danych przechowywać datę raportu i datę pobrania.
138. Dla ETF przechowywać datę składu funduszu.
139. Dla danych makro przechowywać serię, jednostkę i źródło.
140. W UI wyraźnie oznaczać przybliżenia i brak danych.
141. Testować każdą nową metrykę na ręcznie policzonych przypadkach referencyjnych.

---

## Etap 23 — Early Beta i pętla feedbacku (po uruchomieniu stabilnego v2)

142. Udostępnić stabilne v2 przed dokładaniem funkcji AI / automatyzacji.
143. Zbierać feedback dotyczący najczęściej używanych analiz.
144. Mierzyć, które KPI, widoki i alerty są faktycznie używane.
145. Na podstawie feedbacku ustalać kolejność dalszych rozszerzeń, bez naruszania fundamentu v2.
146. Najpierw poprawiać jakość danych i interpretowalność, dopiero później zwiększać automatyzację.

---

## Harmonogram rozszerzeń — orientacyjny

| Zakres | Szacowany czas (1 osoba) |
|---|---|
| Etap 10 — Single Asset Analysis | ok. 5–7 dni |
| Etap 11 — Market Scanner 2.0 | ok. 4–6 dni |
| Etap 12 — statystyki portfela | ok. 3–5 dni |
| Etap 13 — Look-Through X-Ray | ok. 6–10 dni |
| Etap 14 — Drift + Smart Alerts | ok. 4–6 dni |
| Etap 15 — Atrybucja FX | ok. 3–5 dni |
| Etap 16 — Multi-Asset / Net Worth | ok. 5–8 dni |
| Etap 17 — Opportunity Cost | ok. 3–4 dni |
| Etap 18 — Monte Carlo | ok. 5–8 dni |
| Etap 19 — Conversational BI / AI | ok. 5–10 dni |
| Etap 20 — UX / Data Literacy | ok. 3–5 dni |
| Etap 21 — pełna księgowość + podatki | osobny duży moduł; po decyzji o transakcjach |

Powyższy harmonogram jest **dodatkiem** do istniejącego harmonogramu 6–9 tygodni. Nie zmienia on deklarowanego czasu realizacji v2.

---

## Docelowa kolejność rozwoju

`v2: monitoring + struktura + rynki + ryzyko`

↓

`Single Asset Analysis`

↓

`Market Scanner 2.0`

↓

`CAGR + Sortino + korelacje + koszty`

↓

`Look-Through X-Ray`

↓

`Portfolio Drift + Smart Alerts`

↓

`FX Attribution`

↓

`Multi-Asset / Net Worth`

↓

`Opportunity Cost + Monte Carlo`

↓

`Conversational BI / AI`

↓

`ewentualny powrót do transakcji → FIFO / TWR / XIRR / podatki`

---

## Zasada nadrzędna dla agenta Claude

**Nie zmieniaj istniejącego projektu v2 ani planu Etapów 0–9.** Wszystkie powyższe punkty są rozszerzeniami dopisywanymi po istniejącym zakresie. Nie usuwaj istniejących funkcji, nie przenoś etapów i nie przywracaj rejestru transakcji w ramach v2. Jeśli implementujesz rozszerzenie, zachowuj istniejące ADR-y, model snapshotów, izolację danych, DataProvider, cache i obecny przepływ `holdings → wycena → snapshot → analityka`.
