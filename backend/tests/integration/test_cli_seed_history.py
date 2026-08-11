"""Testy guardów `app.cli._run_seed_history` (etap 8, krok zerowy).

`seed-history` dopisuje do `portfolio_valuations` wyceny odtworzone wstecz.
Ma dwa zabezpieczenia i oba są tu sprawdzane **na wywołaniu, nie na kodzie
wyjścia**: test, który potwierdza tylko „zwróciło 2", przeszedłby także
wtedy, gdyby komenda najpierw zapisała pół roku snapshotów, a dopiero potem
odmówiła. Stąd szpieg na `snapshot_portfolios` w każdym teście odmowy.

1. **`ENV != dev`** — na produkcji te wiersze byłyby nieodróżnialne od
   prawdziwych snapshotów i łamałyby ADR-101 (historia nie jest
   przeliczana).
2. **Dolna granica zakresu** — silnik wyceny pomija pozycję bez ceny
   zamiast liczyć ją jako zero, więc dzień bez kompletu notowań daje wycenę
   cząstkową. Seria zaczynałaby się blisko zera i skakała w miarę
   „pojawiania się" pozycji: krok 40 policzyłby z tego absurdalny zwrot,
   krok 41 — drawdown 100%.

`held_asset_price_coverage` jest podmieniane na atrybucie modułu `app.cli`
(konwencja „where to patch") — realny odczyt z bazy pokrywa
`test_portfolio_repository_coverage.py`.
"""

from __future__ import annotations

from datetime import date

import pytest

import app.cli as cli_module
from app.cli import _run_seed_history
from app.modules.portfolio.repository import HeldAssetPriceCoverage

_START = date(2026, 1, 1)
_END = date(2026, 1, 31)


@pytest.fixture
def snapshot_spy(monkeypatch: pytest.MonkeyPatch) -> list[date]:
    """Rejestruje dni, dla których komenda faktycznie policzyła snapshot."""
    called: list[date] = []

    async def _spy(run_date: date) -> None:
        called.append(run_date)

    monkeypatch.setattr(cli_module, "snapshot_portfolios", _spy)
    return called


def _coverage(
    first_full: date | None = date(2020, 1, 1), missing: tuple[str, ...] = ()
) -> HeldAssetPriceCoverage:
    return HeldAssetPriceCoverage(first_full_date=first_full, assets_without_prices=missing)


@pytest.fixture(autouse=True)
def _full_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Domyślnie pokrycie jest pełne — testy guardu pokrycia nadpisują."""
    monkeypatch.setattr(cli_module, "held_asset_price_coverage", lambda _db: _noop(_coverage()))


async def _noop(value: HeldAssetPriceCoverage) -> HeldAssetPriceCoverage:
    return value


@pytest.mark.parametrize("env", ["prod", "staging", ""])
async def test_refuses_outside_dev_without_writing_anything(
    env: str, snapshot_spy: list[date], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = cli_module.get_settings()
    monkeypatch.setattr(settings, "env", env)
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)

    result = await _run_seed_history(start=_START, end=_END, include_weekends=False)

    assert result == 2
    assert snapshot_spy == [], "odmowa musi nastąpić PRZED jakimkolwiek zapisem"


async def test_refuses_reversed_range(snapshot_spy: list[date]) -> None:
    result = await _run_seed_history(start=_END, end=_START, include_weekends=False)

    assert result == 2
    assert snapshot_spy == []


async def test_refuses_when_some_held_asset_has_no_prices_at_all(
    snapshot_spy: list[date], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli_module,
        "held_asset_price_coverage",
        lambda _db: _noop(_coverage(first_full=None, missing=("AAPL",))),
    )

    result = await _run_seed_history(start=_START, end=_END, include_weekends=False)

    assert result == 2
    assert snapshot_spy == []


async def test_refuses_when_range_starts_before_full_price_coverage(
    snapshot_spy: list[date], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Realny stan bazy dev: CDR ma historię od 2025-08, PKN od 2026-07,
    bitcoin od 2026-06 — pięcioletni `seed-history` zapisałby ~1000 wycen
    cząstkowych, zanim doszedłby do pierwszego pełnego dnia."""
    monkeypatch.setattr(
        cli_module,
        "held_asset_price_coverage",
        lambda _db: _noop(_coverage(first_full=date(2026, 7, 20))),
    )

    result = await _run_seed_history(start=_START, end=_END, include_weekends=False)

    assert result == 2
    assert snapshot_spy == []


async def test_allow_incomplete_overrides_coverage_guard(
    snapshot_spy: list[date], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Świadome wymuszenie działa — guard jest zabezpieczeniem, nie zakazem."""
    monkeypatch.setattr(
        cli_module,
        "held_asset_price_coverage",
        lambda _db: _noop(_coverage(first_full=date(2026, 7, 20))),
    )

    result = await _run_seed_history(
        start=date(2026, 1, 5), end=date(2026, 1, 9), include_weekends=False, allow_incomplete=True
    )

    assert result == 0
    assert snapshot_spy == [date(2026, 1, i) for i in range(5, 10)]


async def test_weekends_are_skipped_by_default(snapshot_spy: list[date]) -> None:
    """2026-01-03 i 04 to sobota i niedziela — wycena czytałaby ceny z
    piątku przez `max(date) <= D`, rozcieńczając zmienność dwoma dniami
    zerowego zwrotu w tygodniu (krok 41 zakłada obserwacje sesyjne)."""
    result = await _run_seed_history(
        start=date(2026, 1, 1), end=date(2026, 1, 5), include_weekends=False
    )

    assert result == 0
    assert snapshot_spy == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 5)]
