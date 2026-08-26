"""Testy `AlphaVantageDividendsProvider` (plan krok 47, etap 9).

Zero sieci — `respx` przechwytuje HTTP, payloady budowane w miejscu wg
kształtu odpowiedzi `DIVIDENDS` (ten sam wzorzec co
`tests/unit/test_alphavantage_news_provider.py`).

Sedno tych testów: **pusta lista i awaria muszą być rozróżnialne**.
Alpha Vantage nie sygnalizuje błędów kodem HTTP — wyczerpany limit dobowy
wraca jako `200 OK` z kluczem `Information`. Gdyby provider zamienił to na
zero zdarzeń, kalendarz użytkownika napisałby „brak nadchodzących dywidend",
czyli fałszywy fakt zamiast informacji o awarii (CLAUDE.md #3.15).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from app.core.cache import get_redis
from app.core.errors import ProviderUnavailableError
from app.modules.dividends.providers.alphavantage_dividends import (
    AlphaVantageDividendsProvider,
)
from app.modules.marketdata.providers.rate_limiter import RateLimiter

_URL = "https://www.alphavantage.co/query"


@pytest.fixture(autouse=True)
async def _cleanup_rate_limiter_keys() -> AsyncGenerator[None, None]:
    yield
    async for key in get_redis().scan_iter("rate_limiter:test-av-div-*"):
        await get_redis().delete(key)


def _provider(
    client: httpx.AsyncClient, *, api_key: str | None = "test-key"
) -> AlphaVantageDividendsProvider:
    limiter = RateLimiter(f"test-av-div-{uuid.uuid4().hex}", 60, redis=get_redis())
    return AlphaVantageDividendsProvider(client, limiter=limiter, api_key=api_key)


def _row(**overrides: Any) -> dict[str, Any]:
    row = {
        "ex_dividend_date": "2026-08-10",
        "declaration_date": "2026-07-30",
        "record_date": "2026-08-10",
        "payment_date": "2026-08-13",
        "amount": "0.27",
    }
    row.update(overrides)
    return row


@respx.mock
async def test_parsuje_cztery_daty_i_kwote() -> None:
    respx.get(_URL).mock(
        return_value=httpx.Response(200, json={"symbol": "AAPL", "data": [_row()]})
    )

    async with httpx.AsyncClient() as client:
        events = await _provider(client).get_dividends("AAPL")

    assert len(events) == 1
    event = events[0]
    assert event.ex_date == date(2026, 8, 10)
    assert event.declaration_date == date(2026, 7, 30)
    assert event.record_date == date(2026, 8, 10)
    assert event.pay_date == date(2026, 8, 13)
    assert event.amount == Decimal("0.27")
    # Waluty dostawca NIE podaje — uzupełnia ją ingestia z `assets.currency`.
    # Gdyby provider zgadywał „pewnie USD", kolumna, której jedynym zadaniem
    # jest mówić prawdę o kwocie, niosłaby domysł.
    assert event.currency == ""


@respx.mock
async def test_nieznana_data_wyplaty_nie_wywala_wpisu() -> None:
    """Alpha Vantage wstawia w nieustalone daty literał `"None"` (string,
    nie `null`). Zdarzenie z ex-datą i bez daty wypłaty jest normalne —
    wypłata bywa ogłaszana później."""
    respx.get(_URL).mock(
        return_value=httpx.Response(
            200, json={"symbol": "AAPL", "data": [_row(payment_date="None", record_date="None")]}
        )
    )

    async with httpx.AsyncClient() as client:
        events = await _provider(client).get_dividends("AAPL")

    assert len(events) == 1
    assert events[0].pay_date is None
    assert events[0].record_date is None
    assert events[0].ex_date == date(2026, 8, 10)


@respx.mock
async def test_wpis_bez_ex_daty_jest_pomijany() -> None:
    """`ex_date` jest jedyną datą wymaganą — bez niej zdarzenia nie da się
    umieścić w kalendarzu, a podstawienie `pay_date` przesunęłoby je
    o tygodnie."""
    respx.get(_URL).mock(
        return_value=httpx.Response(
            200, json={"symbol": "AAPL", "data": [_row(ex_dividend_date="None"), _row()]}
        )
    )

    async with httpx.AsyncClient() as client:
        events = await _provider(client).get_dividends("AAPL")

    assert len(events) == 1


@respx.mock
@pytest.mark.parametrize("amount", ["0", "-1.5", "None", "", "NaN", "Infinity", "1e12"])
async def test_kwota_niedodatnia_lub_nieparsowalna_jest_pomijana(amount: str) -> None:
    """Zerowa kwota w kalendarzu wygląda jak zapowiedź wypłaty niczego,
    a ujemna jest artefaktem danych.

    `"NaN"`/`"Infinity"` to osobna pułapka: `Decimal` przyjmuje je bez
    błędu, a `Decimal("NaN") <= 0` rzuca `InvalidOperation` — czyli naiwna
    kontrola znaku wywaliłaby cały symbol zamiast pominąć jeden wiersz.
    `1e12` przekracza pojemność `NUMERIC(20,8)` i wysadziłaby dopiero
    `INSERT`, po spaleniu zapytania u dostawcy.
    """
    respx.get(_URL).mock(
        return_value=httpx.Response(200, json={"symbol": "AAPL", "data": [_row(amount=amount)]})
    )

    async with httpx.AsyncClient() as client:
        events = await _provider(client).get_dividends("AAPL")

    assert events == []


@respx.mock
@pytest.mark.parametrize("key", ["Information", "Note", "Error Message"])
async def test_odmowa_dostawcy_to_wyjatek_a_nie_pusta_lista(key: str) -> None:
    """**Najważniejszy test tego pliku.** Wyczerpany limit dobowy wraca jako
    `200 OK` z komunikatem zamiast danych. Zamiana tego na zero zdarzeń
    kazałaby kalendarzowi napisać „nic Cię nie czeka" w sytuacji, w której
    po prostu nie wiemy — i nie otworzyłaby bezpiecznika."""
    respx.get(_URL).mock(
        return_value=httpx.Response(200, json={key: "Thank you for using Alpha Vantage!"})
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(ProviderUnavailableError):
            await _provider(client).get_dividends("AAPL")


@respx.mock
async def test_brak_klucza_api_to_wyjatek() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ProviderUnavailableError):
            await _provider(client, api_key="").get_dividends("AAPL")


@respx.mock
async def test_pusta_lista_data_to_poprawna_odpowiedz() -> None:
    """Tak wygląda odpowiedź dla spółki z GPW (`PKN.WAR` → `data: []`,
    sprawdzone na żywo 2026-08-23) i dla spółki niepłacącej dywidendy.
    To NIE jest awaria — rozróżnienie „nie pokrywamy" od „nie płaci"
    robi warstwa wyżej, po mapowaniu `asset_source_map`."""
    respx.get(_URL).mock(return_value=httpx.Response(200, json={"symbol": "PKN.WAR", "data": []}))

    async with httpx.AsyncClient() as client:
        assert await _provider(client).get_dividends("PKN.WAR") == []
