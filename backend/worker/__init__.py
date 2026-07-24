"""Worker AlphaSense — osobny proces/kontener od API, ten sam obraz Dockera
(`backend/Dockerfile`), inny `command:` w `docker-compose.yml` (dodawane w
kolejnym podkroku, poza zakresem tego pakietu — plan krok 23, etap 4).

Świadomie `backend/worker/`, nie top-level `worker/` (decyzja architektoniczna
z użytkownikiem): dzielenie obrazu Dockera z `app/` (API) bez kombinowania z
kontekstem budowania (`docker-compose.yml`: `api.build.context: ./backend`
kopiuje całe `backend/`, w tym ten katalog, `COPY . .` w Dockerfile).

`worker/scheduler.py` to entrypoint (APScheduler, harmonogram z `markets`),
`worker/jobs/` to poszczególne joby EOD wołane albo przez scheduler, albo
ręcznie (`python -m app.cli ingest`, `app/cli.py`).
"""

from __future__ import annotations
