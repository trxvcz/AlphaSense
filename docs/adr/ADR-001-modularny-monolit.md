# ADR-001: Modularny monolit zamiast mikroserwisów

**Status:** Zaakceptowana (przeniesiona z v1)
**Data:** 2026-07-20

## Decyzja

Jeden proces FastAPI z wyraźnym podziałem na moduły (auth, portfolio, marketdata, analytics, news), plus osobny kontener workera. Granice modułów są umowne, ale egzekwowane w review

## Konsekwencje

Obowiązuje bez zmian w v2. Szczegóły w dokumencie projektu systemu v1, sekcja 4.
