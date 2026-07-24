"""Rate limiting (`slowapi`, plan krok 16) — liczniki w Redisie.

`Limiter` jest skonfigurowany z `storage_uri=settings.redis_url`, nie z
domyślnym magazynem w pamięci procesu: w pamięci procesu limity nie
przetrwałyby restartu kontenera ani nie działałyby poprawnie z wieloma
replikami API, a Redis jest już częścią stacku (`core/cache.py`).

Uwaga: to inny przypadek użycia Redisa niż `core/cache.py`. `cache.py` to
czysty cache (CLAUDE.md #3.7) — Redis można wyczyścić i aplikacja działa
dalej, wolniej. Tutaj awaria Redisa musi być widoczna: przepuszczenie
wszystkich żądań bez ograniczeń przy padzie Redisa byłoby dziurą
bezpieczeństwa (np. brute-force na `/auth/login`), więc `swallow_errors`
i `in_memory_fallback` pozostają wyłączone (wartości domyślne slowapi).

Limit domyślny (`Settings.rate_limit_default_per_minute`) jest rejestrowany
globalnie w `app.main` (`SlowAPIMiddleware`) i liczony per adres IP +
ścieżka. `AUTH_RATE_LIMIT` (`Settings.rate_limit_auth_per_minute`) jest
ostrzejszy i nakładany wyłącznie na `/auth/register` i `/auth/login`
dekoratorem `@limiter.limit(AUTH_RATE_LIMIT)` w `modules/auth/routes.py` —
to jedyne dwie trasy podatne na zgadywanie hasła / zalewanie rejestracjami.
`/auth/refresh`, `/auth/logout` i `/auth/google/*` zostają na limicie
globalnym: `refresh`/`logout` wymagają już poprawnego refresh tokenu
(nie da się nimi zgadywać hasła), a `/google/*` idzie przez Google
(własny rate limiting po ich stronie) i nie przyjmuje hasła.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

_settings = get_settings()

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_settings.redis_url,
    default_limits=[f"{_settings.rate_limit_default_per_minute}/minute"],
)

AUTH_RATE_LIMIT = f"{_settings.rate_limit_auth_per_minute}/minute"
