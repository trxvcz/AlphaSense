# SPECYFIKACJA LOGIKI: AI Fund, Vibe-Trading & Self-Improving Memory (Gemini 1.5 Flash)

Zadaniem jest wdrożenie 6-etapowego systemu agentowego AI Hedge Fund, analityki sentymentu oraz systemu samodoskonalenia. System opiera się na modelu Google Gemini 1.5 Flash (przez oficjalne SDK lub LiteLLM). Samodzielnie decyduj o strukturze plików, ale **rygorystycznie przestrzegaj poniższych reguł biznesowych oraz pliku CLAUDE.md**.

## 1. Złote Reguły Architektury (Zero-Cost & Guardrails)
*   **Wymuszony JSON:** Gemini musi zawsze zwracać ustrukturyzowane dane (`response_mime_type="application/json"`).
*   **Single Source of Truth (SSoT):** Modele LLM absolutnie nie mogą wymyślać cen ani wyników symulacji.
*   **Zakaz generowania kodu przez AI:** Agent Backtest nie może pisać skryptów w Pythonie. Napisz w `backend/app/modules/ai_fund/backtester.py` deterministyczną klasę, która wykonuje symulację na danych `prices` (`close_adj`) z naszej bazy. Agent AI dostarcza wyłącznie JSON z parametrami (wagi, stop-loss), które ten kod wykonuje.
*   **Data Literacy (Zasada #15):** Brak danych (np. brak ocen analityków dla GPW) musi być jawnie oznaczony w UI ("Brak pokrycia dla tego rynku"), a nie maskowany zerami lub pustym wykresem.
*   **Izolacja Danych:** Każdy endpoint w module musi przechodzić przez `Depends(get_owned_portfolio)`. Żaden użytkownik nie widzi sesji ani lekcji AI innego użytkownika.

---

## ETAP 1: Modele Danych i Pamięć "Vector-Ready" (Backend)
1. **Nowe modele w `ai_fund/models.py` i `marketdata/models.py`:**
   *   `AIFundSession`: `id`, `portfolio_id`, `status` (Enum), `config` (JSONB - tu przechowujemy `memory_ttl_days`).
   *   `AIAgentLog`: `id`, `session_id`, `agent_type` (Enum: research, vibe, debate, backtest, risk, review), `parsed_data` (JSONB).
   *   `AssetVibeMetric`: `asset_id`, `date`, `social_volume` (Int), `hype_score` (Numeric).
   *   `AssetAnalystRating`: `asset_id`, `period` (DATE), `strong_buy`, `buy`, `hold`, `sell`, `strong_sell` (Int).
   *   `AIPrediction`: `id`, `session_id`, `asset_id`, `predicted_trend`, `target_price`, `expected_drawdown`, `expiration_date`.
   *   `AILesson`: `id`, `asset_id`, `asset_class`, `lesson_text`, `created_at`. **Uwaga:** Użyj rozszerzenia `pgvector`, aby dodać do `AILesson` kolumnę `embedding (Vector)`. Na razie będzie pusta, przygotowujemy fundament pod RAG.
2. Zarejestruj modele i wygeneruj migrację Alembic.
3. Utwórz cotygodniowy job w workerze: `ingest_analyst_ratings.py` pobierający dane z Finnhub przy użyciu `RateLimiter`. Ignoruj GPW. Użyj `ON CONFLICT DO UPDATE`.

---

## ETAP 2: Silnik 6 Agentów (Pipeline)
1.  **Research:** Zbiera twarde dane z bazy (`close_adj`, newsy) i ładuje do Gemini z prośbą o analizę.
2.  **Vibe:** Zlicza wzmianki/newsy i klasyfikuje hype w skali 1-5.
3.  **Debate:** Zderza fundamenty z hype'em, szukając dysonansu.
4.  **Backtest:** Wypluwa JSON z parametrami. Twardy kod w Pythonie przeprowadza test na historii portfela.
5.  **Risk:** Zwraca JSON modyfikujący parametry. **Hard Limit:** Jeśli Vibe Agent zdiagnozował "Manię/Euforię", twardy kod backendu musi nadpisać parametry Risk Agenta: ściąć pozycję o 50% i aktywować Trailing Stop-Loss.
6.  **Review:** Gemini pisze raport w formacie tekstowym, podsumowujący liczby. Zapisuje prognozę do `AIPrediction` z terminem ważności (np. 14 dni).

---

## ETAP 3: Architektura Samodoskonalenia (Memory Decay)
1. **Agent Ewaluator (Sędzia):**
   *   Napisz skrypt w `worker/jobs/evaluate_ai_sessions.py` (uruchamiany codziennie).
   *   Wyszukuje wygasłe `AIPrediction`, pobiera z bazy rzeczywiste ceny `close_adj` z tego okresu i wylicza faktyczny wynik.
   *   Jeśli AI się pomyliło, wysyła dane do Gemini z poleceniem: "Zrób autokrytykę. Wygeneruj 1-zdaniową lekcję na przyszłość." Zapisuje wynik w `AILesson`.
2. **Wstrzykiwanie Lekcji z filtrem (Self-Correction):**
   *   Zmodyfikuj orkiestrator. Zanim uruchomisz agentów dla aktywa, pobierz historię z `AILesson` używając SQL: `WHERE created_at >= NOW() - INTERVAL '{memory_ttl_days} days'`.
   *   Jeśli sesja nie ma `memory_ttl_days`, użyj domyślnych: Krypto (60 dni), Akcje (180 dni), ETF (365 dni).
   *   Wstrzyknij pobrane lekcje do parametru `system_instruction` w Gemini: "Poprzednie błędy: [LEKCJE]. Jeśli warunki się zmieniły, zignoruj lekcję, ale napisz dlaczego."

---

## ETAP 4: Single Asset Analysis (Sentyment i Analitycy)
1. **Sentyment (`GET /assets/{id}/sentiment`):** Oblicz średnią matematyczną z `overall_sentiment_score` (newsy z ostatnich 7 dni). Wyślij najnowsze nagłówki do Gemini, by wygenerować 2-zdaniowe tekstowe TL;DR nastrojów (tylko objaśnienie tekstów).
2. **Analitycy (`GET /assets/{id}/analyst-ratings`):** Zwróć ustrukturyzowane oceny Finnhub z bazy.
3. **UI (`app/assets/[id]/page.tsx`):**
   *   ECharts Gauge (Wskaźnik wychyłowy) dla Sentymentu.
   *   ECharts Stacked Bar (Skumulowany słupkowy) dla ocen Analityków.
   *   Jawny komunikat stanu pustego w przypadku braku danych (np. GPW).

---

## ETAP 5: Wizualizacja (Advanced TradingView) i Interfejs
1. **Modyfikacja `CandleChart.tsx`:**
   *   Dodaj dolny panel z histogramem wolumenu pod świecami.
   *   Dodaj obsługę `Markers` na świecach OHLC na podstawie API (np. ikony 🚀/⚠️ dla Vibe Agenta i strzałki dla zrealizowanego Backtestu).
2. **Control Room (`app/portfolios/[id]/ai-fund/page.tsx`):**
   *   Formularz: limit straty, max ryzyko oraz **Suwak Pamięci AI (Memory TTL)**.
   *   Dynamiczny pasek postępu (Stepper) z rozwijanymi kartami JSON/Text dla każdego Agenta.
   *   Zintegrowany wykres `CandleChart.tsx`, odświeżający markery po zakończeniu kroku Backtest.
   *   Przycisk "Zatwierdź strategię (Paper Trading)" (tylko w stanie `awaiting_approval`).

Uruchamiaj `make check` na backendzie po każdym ukończonym etapie. Eliminuj błędy MyPy i lintera na bieżąco.