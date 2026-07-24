# ADR-005: Własny auth zamiast dostawcy zewnętrznego

**Status:** Zaakceptowana (przeniesiona z v1)
**Data:** 2026-07-20

## Decyzja

argon2id do haseł, JWT access 15 minut, refresh rotowany w httpOnly cookie, OAuth Google wyłącznie przez Authorization Code + PKCE po stronie backendu.

## Konsekwencje

Obowiązuje bez zmian w v2. Szczegóły w dokumencie projektu systemu v1, sekcja 4.
