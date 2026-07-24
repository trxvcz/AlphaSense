# Indeks decyzji architektonicznych

Seria 0xx — decyzje przeniesione z v1. Seria 1xx — decyzje v2.

| ADR | Tytuł | Status |
|---|---|---|
| [ADR-001](ADR-001-modularny-monolit.md) | Modularny monolit zamiast mikroserwisów | Zaakceptowana |
| [ADR-002](ADR-002-izolacja-danych.md) | Izolacja danych: zależność aplikacyjna + RLS w Fazie 2 | Zaakceptowana |
| [ADR-003](ADR-003-snapshoty-dzienne.md) | Snapshoty dzienne wartości portfela | Zaakceptowana (uproszczona) |
| [ADR-004](ADR-004-scheduler-w-workerze.md) | APScheduler w osobnym kontenerze | Zaakceptowana |
| [ADR-005](ADR-005-wlasny-auth.md) | Własny auth: argon2id + JWT + OAuth Google | Zaakceptowana |
| ADR-006 | Model przepływów pieniężnych | **Wycofana** — bezprzedmiotowa w v2 |
| [ADR-101](ADR-101-semantyka-historii.md) | Semantyka historii przy edycji pozycji | Proponowana |
| [ADR-102](ADR-102-slownik-rynkow.md) | Słownik rynków i indeksów referencyjnych | Proponowana |

Nowy ADR: komenda `/adr <temat>` albo szablon `_szablon.md`.
