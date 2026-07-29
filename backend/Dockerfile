# Obraz wielostopniowy: `dev` (hot reload, narzędzia) i `prod` (bez
# requirements-dev, użytkownik nie-root). Stopień wybiera compose przez
# `target:` — `docker-compose.yml` → dev, `docker-compose.prod.yml` → prod.
#
# Ten sam obraz obsługuje API i workera (różni je `command:` w compose,
# CLAUDE.md §6) — stąd brak `CMD` specyficznego dla workera.

FROM python:3.12-slim AS base

# WORKDIR odpowiada temu, co lokalnie jest `backend/` (kontekst budowania),
# żeby `docker compose exec api mypy app` / `pytest` / `alembic upgrade head`
# z Makefile działały bez `cd` (patrz notatka w zadaniu kroku 6).
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Zależności produkcyjne instalowane przed skopiowaniem kodu — warstwa
# przetrwa w cache każdą zmianę w `app/`, przebudowa nie ściąga pakietów.
COPY requirements.txt ./
RUN pip install -r requirements.txt


FROM base AS dev

COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

# Kod i tak jest przykryty bind-mountem z compose; kopiowany, żeby obraz
# dało się uruchomić samodzielnie (np. `docker run` przy diagnostyce).
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


FROM base AS prod

# Nie-root: proces API nie ma powodu móc pisać po własnym kodzie ani po
# systemie plików kontenera. UID na sztywno, żeby ewentualny wolumen
# montowany do kontenera miał przewidywalnego właściciela.
RUN useradd --create-home --uid 1000 app

COPY --chown=app:app . .

USER app

EXPOSE 8000

# Bez `--reload` (watcher plików to narzut i ryzyko restartu na produkcji).
#
# `--proxy-headers` jest domyślnie włączone; o poprawność decyduje
# `FORWARDED_ALLOW_IPS` ustawiane w compose na KONKRETNY adres Caddy'ego.
# Nigdy `*` — przy `*` uvicorn bierze SKRAJNIE LEWY wpis `X-Forwarded-For`,
# w całości kontrolowany przez klienta, co pozwoliłoby obejść rate limiting
# na `/auth/login` przez podmianę nagłówka (patrz `app/core/rate_limit.py`).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
