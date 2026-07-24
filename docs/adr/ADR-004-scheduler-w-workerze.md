# ADR-004: APScheduler w osobnym kontenerze

**Status:** Zaakceptowana (przeniesiona z v1)
**Data:** 2026-07-20

## Decyzja

Harmonogram działa w dedykowanym kontenerze workera, nie w procesie API. Blokady doradcze Postgresa chronią przed podwójnym uruchomieniem joba.

## Konsekwencje

Obowiązuje bez zmian w v2. Szczegóły w dokumencie projektu systemu v1, sekcja 4.
