"""Testy inicjalizacji Sentry (`core/observability.py`, plan krok 37).

Jednostkowe: `sentry_sdk.init` jest podmieniane, więc nic nie leci do sieci,
a test sprawdza to, co realnie da się zepsuć przy późniejszej zmianie —
**czy Sentry w ogóle się nie włącza bez DSN** (dev i testy nie mogą zacząć
wysyłać zdarzeń tylko dlatego, że ktoś dodał pakiet) i **czy opcje
prywatności są takie, jak deklaruje docstring modułu**.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core import observability
from app.core.config import Settings

# DSN o poprawnej składni, wskazujący na domenę zarezerwowaną (RFC 2606) —
# gdyby `sentry_sdk.init` jednak nie zostało podmienione, nie ma dokąd wysłać.
_FAKE_DSN = "https://public@sentry.example/1"


def test_init_sentry_is_noop_without_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bez `SENTRY_DSN` (dev, CI) SDK nie jest inicjalizowane w ogóle."""
    monkeypatch.setattr(observability, "get_settings", lambda: Settings(sentry_dsn=""))

    def _fail_init(**_kwargs: Any) -> None:
        raise AssertionError("sentry_sdk.init nie powinno zostać wywołane bez DSN")

    monkeypatch.setattr(observability.sentry_sdk, "init", _fail_init)

    assert observability.init_sentry("api") is False


def test_init_sentry_sets_privacy_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """Z DSN: SDK startuje, ale bez PII i bez ciał żądań.

    `send_default_pii=False` włącza domyślny `EventScrubber` (czyści m.in.
    `authorization`, `cookie`, `token`, `password`), a
    `max_request_body_size="never"` nie dopuszcza do wysłania ciała
    `POST /auth/login` — hasło jedzie tam jawnym tekstem i scrubber nie ma
    tam nazwanego pola do rozpoznania.
    """
    monkeypatch.setattr(
        observability,
        "get_settings",
        lambda: Settings(sentry_dsn=_FAKE_DSN, env="dev", app_version="1.2.3"),
    )
    captured: dict[str, Any] = {}
    monkeypatch.setattr(observability.sentry_sdk, "init", lambda **kwargs: captured.update(kwargs))
    tags: dict[str, str] = {}
    monkeypatch.setattr(
        observability.sentry_sdk, "set_tag", lambda key, value: tags.update({key: value})
    )

    assert observability.init_sentry("worker") is True

    assert captured["dsn"] == _FAKE_DSN
    assert captured["send_default_pii"] is False
    assert captured["max_request_body_size"] == "never"
    assert captured["environment"] == "dev"
    assert captured["release"] == "1.2.3"
    assert tags == {"component": "worker"}
