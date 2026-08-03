"""Testy komendy `python -m app.cli alert` (plan krok 38).

Ta komenda jest jedyną drogą, którą nocny backup (`infra/backup/backup.sh`,
cron na hoście) mówi o swojej awarii. Testy pilnują trzech rzeczy, które da się
zepsuć cicho: że bez `SENTRY_DSN` nic nie leci do sieci, że z DSN-em zdarzenie
faktycznie powstaje **z fingerprintem od wołającego** (bez niego powtarzalna
awaria byłaby nową sprawą co dobę) i że bufor transportu jest opróżniany przed
wyjściem z procesu.

Jednostkowe: `init_sentry` i `capture_message` są podmieniane, więc żadne
żądanie sieciowe nie powstaje.
"""

from __future__ import annotations

from typing import Any

import pytest

from app import cli


class _FakeScope:
    def __init__(self) -> None:
        self.fingerprint: list[str] | None = None
        self.tags: dict[str, str] = {}

    def set_tag(self, key: str, value: str) -> None:
        self.tags[key] = value

    def __enter__(self) -> _FakeScope:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _patch_sentry(monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> dict[str, Any]:
    """Podmienia Sentry i zwraca słownik z tym, co komenda próbowała wysłać."""
    recorded: dict[str, Any] = {"messages": [], "flushed": False, "scope": _FakeScope()}

    monkeypatch.setattr(cli, "init_sentry", lambda component: enabled)
    monkeypatch.setattr(cli.sentry_sdk, "new_scope", lambda: recorded["scope"])
    monkeypatch.setattr(
        cli.sentry_sdk,
        "capture_message",
        lambda message, level=None: recorded["messages"].append((message, level)),
    )
    monkeypatch.setattr(
        cli.sentry_sdk,
        "flush",
        lambda timeout=None: recorded.update(flushed=True),
    )
    return recorded


def test_alert_sends_message_with_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = _patch_sentry(monkeypatch, enabled=True)

    exit_code = cli.main(
        [
            "alert",
            "--level",
            "warning",
            "--fingerprint",
            "backup-failed",
            "--message",
            "Backup nie powiódł się",
        ]
    )

    assert exit_code == 0
    assert recorded["messages"] == [("Backup nie powiódł się", "warning")]
    # Bez fingerprintu Sentry grupowałoby po treści; treść niesie kod wyjścia i
    # numer linii, więc każda noc byłaby osobnym problemem.
    assert recorded["scope"].fingerprint == ["backup-failed"]
    # Proces CLI kończy się natychmiast po `capture_message` — bez `flush`
    # zdarzenie zostałoby w kolejce transportu i alert nigdy by nie doleciał.
    assert recorded["flushed"] is True


def test_alert_defaults_to_error_level(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = _patch_sentry(monkeypatch, enabled=True)

    assert cli.main(["alert", "--fingerprint", "backup-failed", "--message", "Awaria"]) == 0
    assert recorded["messages"] == [("Awaria", "error")]


def test_alert_is_noop_without_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bez DSN: zero ruchu sieciowego i kod 0.

    Kod 0, bo pusty `SENTRY_DSN` to poprawna konfiguracja (dev, wdrożenie bez
    Sentry) — o niepowodzeniu backupu decyduje kod wyjścia `backup.sh`, nie tej
    komendy. Gdyby `alert` zwracał tu błąd, `backup.sh` raportowałby awarię
    alertowania zamiast awarii backupu.
    """
    recorded = _patch_sentry(monkeypatch, enabled=False)

    assert cli.main(["alert", "--fingerprint", "backup-failed", "--message", "Awaria"]) == 0
    assert recorded["messages"] == []
    assert recorded["flushed"] is False


def test_alert_requires_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--fingerprint` jest obowiązkowy — argparse ma to wyłapać przed Sentry."""
    _patch_sentry(monkeypatch, enabled=True)

    with pytest.raises(SystemExit) as exc:
        cli.main(["alert", "--message", "Awaria"])

    assert exc.value.code == 2
