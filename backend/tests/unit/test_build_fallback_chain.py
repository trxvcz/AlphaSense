"""Testy `build_fallback_chain` (`app.modules.marketdata.service`) — wzorzec
kompozycji per rynek (plan krok 22, etap 4), niepodłączony do żadnego joba
w tym kroku (patrz docstring funkcji).
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.modules.marketdata.service import build_fallback_chain


def test_crypto_market_uses_binance_first_then_yfinance_fallback() -> None:
    chain = build_fallback_chain("CRYPTO")
    assert [g.name for g in chain] == ["binance", "yfinance"]


def test_gpw_market_uses_stooq_first_then_yfinance_fallback() -> None:
    chain = build_fallback_chain("GPW")
    assert [g.name for g in chain] == ["stooq", "yfinance"]


def test_foreign_market_skips_finnhub_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Nie zakładamy pustego `FINNHUB_API_KEY` w środowisku uruchamiającym
    # testy (lokalnie klucz bywa realnie skonfigurowany, plan krok 0) —
    # wymuszamy pusty explicite, żeby test nie zależał od `.env`.
    settings = get_settings()
    monkeypatch.setattr(settings, "finnhub_api_key", "")

    chain = build_fallback_chain("US")

    assert [g.name for g in chain] == ["yfinance"]


def test_foreign_market_includes_finnhub_when_api_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "finnhub_api_key", "test-key")

    chain = build_fallback_chain("US")

    assert [g.name for g in chain] == ["yfinance", "finnhub"]
