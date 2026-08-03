"""Sentry — jedna inicjalizacja dla API i workera (plan krok 37).

**Wyłączony, dopóki `SENTRY_DSN` jest pusty.** Dev i testy nie ustawiają DSN,
więc `init_sentry()` kończy się logiem i niczym więcej — żadnego ruchu
sieciowego, żadnego przechwytywania wyjątków, zero zmian w zachowaniu
aplikacji. Produkcja dostaje DSN w `.env.prod` (patrz `docs/wdrozenie.md`).

**Co trafia do Sentry bez żadnej dodatkowej konfiguracji:**

- nieobsłużony wyjątek w żądaniu HTTP — integracja FastAPI/Starlette (SDK
  włącza ją sam, gdy framework jest zainstalowany);
- nieobsłużony wyjątek w jobie APScheduler — nie przez integrację (SDK jej dla
  APSchedulera nie ma), tylko przez `LoggingIntegration`: APScheduler raportuje
  padnięty job przez `logging.exception`, a domyślny `event_level=ERROR` robi
  z tego zdarzenie. `structlog` w tym repo pisze **poza** `logging` (brak
  `structlog.configure`), więc nasze własne `logger.error(...)` do Sentry NIE
  trafiają — sygnały operacyjne wysyłamy jawnym `capture_message`
  (`worker/jobs/ingest_market.py`).

**Prywatność.** `send_default_pii=False` — bez adresów IP, bez ciasteczek, bez
identyfikatorów użytkownika. Włącza też domyślny `EventScrubber`, który czyści
pola z listy zawierającej m.in. `authorization`, `cookie`, `token`, `password`,
`secret` — czyli dokładnie to, czym w tej aplikacji są access/refresh JWT i
sekrety OAuth. Dodatkowo `max_request_body_size="never"`: ciało `POST
/auth/login` niesie hasło w jawnej postaci, a scrubber działa na polach o
znanych nazwach, nie na surowym bajcie ciała — taniej jest nie wysyłać go
wcale niż liczyć na to, że zostanie rozpoznane.
"""

from __future__ import annotations

import sentry_sdk
import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)


def init_sentry(component: str) -> bool:
    """Inicjalizuje Sentry dla `component` (`"api"` / `"worker"` / `"cli"` / `"infra"`).

    Zwraca `True`, jeśli SDK zostało włączone. Wołane raz, przy starcie
    procesu — dla API w `app/main.py`, dla workera w `worker/scheduler.py`
    i `app/cli.py` (ręczne uruchomienia jobów mają raportować tak samo jak
    automatyczne — inaczej `python -m app.cli ingest` na produkcji byłby
    ślepą plamą).

    `component` ląduje jako tag zdarzenia: API i worker dzielą DSN (jeden
    projekt backendowy, decyzja z planu etapu 7), więc bez tego taga nie
    dałoby się odfiltrować „awarie jobów EOD" od „błędy żądań HTTP".
    `"infra"` to skrypty z hosta (`infra/backup/*.sh` przez `python -m app.cli
    alert`, krok 38) — awaria nocnego backupu ma inny adresata i inną pilność
    niż wyjątek w żądaniu użytkownika.
    """
    settings = get_settings()

    if not settings.sentry_dsn:
        logger.info("sentry.disabled", component=component, reason="brak SENTRY_DSN")
        return False

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.env,
        # Wersja wdrożonego kodu (`APP_VERSION`, na produkcji skrót commita) —
        # bez tego każdy błąd wygląda tak samo niezależnie od wdrożenia i nie
        # da się powiedzieć, czy poprawka pomogła.
        release=settings.app_version,
        send_default_pii=False,
        max_request_body_size="never",
        # Śledzenie wydajności (transakcje) świadomie wyłączone: krok 37 to
        # alerty o awariach, a nie profilowanie. Każda transakcja to osobne
        # zdarzenie w limicie darmowego planu — włączać dopiero, gdy pojawi
        # się realne pytanie o wydajność, i wtedy z próbkowaniem < 1.0.
        traces_sample_rate=0.0,
    )
    sentry_sdk.set_tag("component", component)

    logger.info(
        "sentry.enabled",
        component=component,
        environment=settings.env,
        release=settings.app_version,
    )
    return True
