---
description: Wdrożenie na produkcję z listą kontrolną
---

Przeprowadź wdrożenie produkcyjne.

Przed:
1. `make check` zielone, `pytest tests/test_isolation.py` zielone.
2. Uruchom subagenta `security-auditor` — brak znalezisk krytycznych i wysokich.
3. Sprawdź, czy migracje mają `downgrade()` i czy istnieje świeży backup (`pg_dump` z ostatniej doby).
4. Sprawdź zmienne środowiskowe na serwerze względem `.env.example` — brakująca zmienna to najczęstsza przyczyna nieudanego wdrożenia.

Wdrożenie (subagent `devops`):
5. `git pull`, build obrazów, kontener `migrate`, potem start API, workera i frontendu.
6. `/health` odpowiada, Caddy wystawia certyfikat, Sentry przyjmuje zdarzenia.

Po:
7. Smoke test: logowanie, dodanie pozycji, dashboard, ranking rynków — na 375 px i desktopie.
8. Sprawdź `ingestion_runs` po najbliższym jobie EOD.
9. Wpis w dzienniku sesji w `../../../STATUS.md`.

Plan wycofania: poprzedni tag obrazu + `alembic downgrade` do rewizji sprzed wdrożenia. Opisz go **zanim** wdrożysz.
