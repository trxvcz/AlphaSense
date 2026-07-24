"""TODO(etap 5, krok 26-27): silnik wyceny jeszcze nie istnieje.

Ten moduł ma docelowo wołać `valuation_service.current_value(...)` per
portfel i zapisywać `portfolio_valuations` (`upsert_valuation`,
`composition_change` — SKILL `job-eod`, sekcja „Snapshot portfeli”), *po*
zakończeniu ingestii EOD danego dnia, nie równolegle z nią.

Świadomie pusty w tym kroku (plan krok 23, etap 4) — CRUD pozycji i wycena
PLN to etap 5. Nie podłączony do `worker/scheduler.py`. Nie zapisuje żadnych
fałszywych/placeholderowych wartości do `portfolio_valuations`.
"""

from __future__ import annotations
