# ADR-104: Moduł AI Fund / Vibe-Trading jako rozszerzenie poza mapą Etapów 0–23

**Status:** Proponowana
**Data:** 2026-09-06
**Dotyczy etapów:** nowy obszar, roboczo „Etap AI-1" … „Etap AI-5" (specyfikacja: `ai_fund_gemini_plan.md`); najbliżej powiązane z Etapem 10 (Single Asset Analysis) i Etapem 19 (Conversational BI) z `docs/plan-dzialania-portfel-v3.md`

## Kontekst

`ai_fund_gemini_plan.md` opisuje 6-agentowy system LLM (Research, Vibe, Debate,
Backtest, Risk, Review) oparty na Google Gemini 1.5 Flash, z pamięcią
samodoskonalącą (`AILesson`, docelowo `pgvector`/RAG), analityką sentymentu i
ocen analityków (Finnhub) oraz krokiem „Zatwierdź strategię (Paper Trading)".

To nie jest realizacja punktu z zatwierdzonej mapy etapów w `CLAUDE.md` §5.
Najbliższe punkty — Etap 10 (Single Asset Analysis) i Etap 19 (Conversational
BI/AI) — nie obejmują autonomicznych agentów LLM generujących prognozy cenowe
(`AIPrediction`), samodzielnego cyklu ewaluacji/samokorekty ani kroku
zatwierdzania strategii. `CLAUDE.md` §10 wymaga pytania użytkownika przed:
zmianą zakresu, dodaniem zależności zewnętrznej, dodaniem płatnego/nowego
źródła danych oraz przy zmianach dotykających pieniędzy użytkownika. Ten plan
uderza we wszystkie cztery naraz:

- nowa zależność zewnętrzna: SDK Google Gemini (`google-genai`) — wybrane
  oficjalne SDK, nie LiteLLM (decyzja użytkownika, 2026-09-06);
- nowa zależność bazodanowa: rozszerzenie `pgvector` w PostgreSQL (na razie
  tylko kolumna `embedding` w `AILesson`, bez realnego RAG w Etapie 1);
- Finnhub jako źródło ocen analityków (`AssetAnalystRating`) — Finnhub jest już
  używany w projekcie (dywidendy, fallback cen), więc to rozszerzenie
  istniejącej integracji, nie nowe konto/klucz;
- „Paper Trading" i `AIPrediction` z ceną docelową dotykają obszaru bliskiego
  Etapowi 21 (transakcje), choć nie wykonują żadnych realnych zleceń ani nie
  wprowadzają rejestru transakcji — to symulowane prognozy, nie księgowość.

Użytkownik potwierdził (2026-09-06, w rozmowie) świadomą decyzję o rozszerzeniu
zakresu o ten moduł, pod warunkiem spisania ADR i aktualizacji planu/STATUS.md
przed rozpoczęciem implementacji.

## Rozważane opcje

| Opcja | Złożoność | Zachowanie |
|---|---|---|
| A. Wdrożyć jako część Etapu 10/19, bez ADR | Niska (brak formalności) | Zaciera granicę między zatwierdzoną mapą v2/v3 a nowym, eksperymentalnym obszarem; narusza CLAUDE.md §11 („nie rozszerzaj v2 przy okazji") |
| B. Osobny, udokumentowany obszar „AI Fund" z własnym ADR i wpisem w STATUS.md, wdrażany etapami z `code-review` po każdym | Średnia (dodatkowa dokumentacja, ale jasna granica) | Moduł izolowany (`ai_fund/`), nie modyfikuje istniejącego kontraktu v2, łatwo go wyłączyć/wycofać jeśli się nie sprawdzi |
| C. Odrzucić plan, trzymać się wyłącznie Etapów 0–23 | Brak | Zero ryzyka scope creep, ale użytkownik jawnie chce tego rozszerzenia |

## Decyzja

Wybrano opcję **B**: moduł `ai_fund` traktujemy jako świadomie zaakceptowane
rozszerzenie poza dotychczasową mapą etapów, izolowane w osobnym module
backendu (`backend/app/modules/ai_fund/`) i osobnej sekcji `STATUS.md`, z
własną numeracją etapów (AI-1 … AI-5) niezależną od kroków 1–50 i Etapów
10–23. Integracja LLM przez oficjalne SDK Google (`google-genai`), zgodnie z
zatwierdzoną przez użytkownika opcją.

## Konsekwencje

- (+) Jasna granica: istniejący kontrakt v2 (`holdings → wycena → snapshot →
  analityka`) oraz Etapy 0–9 pozostają nietknięte; `ai_fund` to nakładka,
  którą można wyłączyć lub usunąć bez wpływu na resztę systemu.
- (+) Reguła SSoT wymuszona architektonicznie: LLM nigdy nie zwraca cen/wyników
  symulacji bezpośrednio do użytkownika — tylko JSON z parametrami, które
  wykonuje deterministyczny kod (`backtester.py`).
- (−) Nowa zależność zewnętrzna (Gemini) oznacza nowy sekret API, koszt
  (nawet przy „zero-cost" tier może się zmienić) i dodatkowy punkt awarii
  poza kontrolą projektu.
- (−) `pgvector` to nowe rozszerzenie Postgresa — wymaga zmiany obrazu/
  migracji na produkcyjnym VPS, nie tylko `alembic upgrade head`; w Etapie 1
  kolumna `embedding` zostaje pusta (przygotowanie pod RAG), co jest kosztem
  bez natychmiastowej korzyści.
- (−) „Paper Trading" i `AIPrediction` z ceną docelową to funkcjonalność
  blisko granicy Etapu 21 (transakcje). Nie wykonujemy zleceń ani nie
  budujemy rejestru transakcji, ale UI, które sugeruje użytkownikowi decyzje
  inwestycyjne na bazie prognoz LLM, wymaga później osobnej, jawnej rewizji
  UX pod kątem „AI nie jest źródłem prawdy" (CLAUDE.md zasada 13).
- (−) Podwójna numeracja etapów (1–50/Etapy 0–23 vs. AI-1…AI-5) zwiększa
  ryzyko pomyłki w `STATUS.md` — wymaga osobnej, wyraźnie oznaczonej sekcji.
- (do rewizji) Jeśli moduł okaże się wartościowy i stabilny, rozważyć
  formalne wpisanie go do `docs/plan-dzialania-portfel-v3.md` jako właściwy
  Etap (np. 10b) zamiast trzymać osobną numerację AI-*.
- (do rewizji) Wybór `pgvector` bez realnego użycia w Etapie 1 — jeśli RAG
  nie zostanie wdrożony w rozsądnym czasie (np. Etap AI-3), rozważyć usunięcie
  kolumny `embedding`, żeby nie trzymać martwej zależności.
