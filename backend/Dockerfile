# Dev image — hot reload przez bind-mount w docker-compose.yml.
# Obraz produkcyjny (bez --reload, bez requirements-dev) powstaje w etapie 7.
FROM python:3.12-slim

# WORKDIR odpowiada temu, co lokalnie jest `backend/` (kontekst budowania),
# żeby `docker compose exec api mypy app` / `pytest` / `alembic upgrade head`
# z Makefile działały bez `cd` (patrz notatka w zadaniu kroku 6).
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
