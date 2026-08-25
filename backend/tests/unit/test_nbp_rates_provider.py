"""Testy `NbpReferenceRatesProvider` (`app.modules.marketdata.providers.nbp_rates`).

Zero sieci — odpowiedzi przechwycone przez `respx`, treść z nagranych
fixture'ów w `tests/fixtures/providers/nbp/`.

**Pochodzenie fixture'ów:** `stopy_archiwum.xml` i `stopy_biezace.xml` to
odpowiedzi z **realnego** `static.nbp.pl` pobrane 2026-08-25 przy pisaniu
tego kroku (`GET /dane/stopy/stopy_procentowe_archiwum.xml` i
`/dane/stopy/stopy_procentowe.xml`). Kształt dokumentu (`<pozycje
obowiazuje_od>` → `<pozycja id="ref" oprocentowanie="3,75">`) jest więc
zweryfikowany na żywo, nie tylko z dokumentacji.

`stopy_biezace.xml` nie jest używany przez kod produkcyjny (bierzemy samo
archiwum, patrz docstring modułu providera) — służy jednemu testowi, który
pilnuje, że to założenie nadal jest prawdziwe: ostatni wpis archiwum musi
zgadzać się ze stanem bieżącym. Gdyby NBP przestał aktualizować archiwum,
ten test to wychwyci przy najbliższym odświeżeniu fixture'ów.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree

import httpx
import pytest
import respx

from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.nbp_rates import (
    ARCHIVE_URL,
    NbpReferenceRatesProvider,
    ReferenceRate,
)

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "providers" / "nbp"


def _fixture_bytes(name: str) -> bytes:
    return (_FIXTURES_DIR / name).read_bytes()


def _mock_archive(*, content: bytes | None = None, status_code: int = 200) -> None:
    respx.get(ARCHIVE_URL).mock(
        return_value=httpx.Response(
            status_code,
            content=content if content is not None else _fixture_bytes("stopy_archiwum.xml"),
        )
    )


@respx.mock
@pytest.mark.asyncio
async def test_parses_full_history_ascending() -> None:
    _mock_archive()
    provider = NbpReferenceRatesProvider()

    rates = await provider.get_reference_rates()
    await provider.aclose()

    assert len(rates) == 96
    assert [r.effective_from for r in rates] == sorted(r.effective_from for r in rates)
    # Pierwsza i ostatnia decyzja w nagranym archiwum — wartości odczytane
    # wprost z pliku, nie z pamięci o tym, co NBP kiedyś ustalił.
    assert rates[0].effective_from == date(1998, 2, 26)
    assert rates[0].rate == Decimal("0.24")
    assert rates[-1].effective_from == date(2026, 3, 5)
    assert rates[-1].rate == Decimal("0.0375")


@respx.mock
@pytest.mark.asyncio
async def test_percent_with_comma_becomes_fraction() -> None:
    """`"3,75"` → `0.0375`, przez `Decimal`, bez przejścia przez `float`.

    Pomyłka o czynnik 100 w tym miejscu nie rzuca wyjątkiem — daje Sharpe'a,
    który wygląda wiarygodnie i jest nieprawdziwy. Stąd osobny test na samą
    jednostkę.
    """
    _mock_archive(
        content=b"""<?xml version="1.0" encoding="utf-8"?>
        <stopy_procentowe_archiwum data_publikacji="2015-03-04">
            <pozycje obowiazuje_od="2026-03-05">
                <pozycja id="ref" oprocentowanie="3,75" />
            </pozycje>
        </stopy_procentowe_archiwum>"""
    )
    provider = NbpReferenceRatesProvider()

    rates = await provider.get_reference_rates()
    await provider.aclose()

    assert rates == [ReferenceRate(effective_from=date(2026, 3, 5), rate=Decimal("0.0375"))]
    assert isinstance(rates[0].rate, Decimal)


@respx.mock
@pytest.mark.asyncio
async def test_entry_without_reference_rate_is_skipped_not_fatal() -> None:
    """Wpis bez pozycji `ref` pomijamy — jedna dziura nie może odciąć reszty."""
    _mock_archive(
        content=b"""<?xml version="1.0" encoding="utf-8"?>
        <stopy_procentowe_archiwum>
            <pozycje obowiazuje_od="1998-02-26">
                <pozycja id="lom" oprocentowanie="27,00" />
            </pozycje>
            <pozycje obowiazuje_od="2026-03-05">
                <pozycja id="ref" oprocentowanie="3,75" />
            </pozycje>
        </stopy_procentowe_archiwum>"""
    )
    provider = NbpReferenceRatesProvider()

    rates = await provider.get_reference_rates()
    await provider.aclose()

    assert [r.effective_from for r in rates] == [date(2026, 3, 5)]


@respx.mock
@pytest.mark.asyncio
async def test_unsorted_input_is_sorted() -> None:
    """Kolejność w pliku NBP to jego konwencja, nie kontrakt — sortujemy sami."""
    _mock_archive(
        content=b"""<?xml version="1.0" encoding="utf-8"?>
        <stopy_procentowe_archiwum>
            <pozycje obowiazuje_od="2026-03-05">
                <pozycja id="ref" oprocentowanie="3,75" />
            </pozycje>
            <pozycje obowiazuje_od="2025-12-04">
                <pozycja id="ref" oprocentowanie="4,00" />
            </pozycje>
        </stopy_procentowe_archiwum>"""
    )
    provider = NbpReferenceRatesProvider()

    rates = await provider.get_reference_rates()
    await provider.aclose()

    assert [r.effective_from for r in rates] == [date(2025, 12, 4), date(2026, 3, 5)]


@respx.mock
@pytest.mark.asyncio
async def test_http_error_raises_provider_unavailable() -> None:
    """404/500 to awaria źródła, nie „brak danych".

    Odwrotnie niż w `NbpProvider.get_fx`, gdzie 404 znaczy „weekend, brak
    notowań w zakresie" i zwraca pustą listę. Tu nie ma odpowiednika
    weekendu — archiwum stóp albo jest, albo źródło padło, a ciche `[]`
    wyglądałoby jak „RPP nigdy nie ustaliła stopy".
    """
    _mock_archive(content=b"nie ma", status_code=404)
    provider = NbpReferenceRatesProvider()

    with pytest.raises(ProviderUnavailableError):
        await provider.get_reference_rates()
    await provider.aclose()


@respx.mock
@pytest.mark.asyncio
async def test_broken_xml_raises_provider_unavailable() -> None:
    _mock_archive(content=b"<stopy_procentowe_archiwum><pozycje")
    provider = NbpReferenceRatesProvider()

    with pytest.raises(ProviderUnavailableError):
        await provider.get_reference_rates()
    await provider.aclose()


@respx.mock
@pytest.mark.asyncio
async def test_archive_without_any_reference_rate_raises() -> None:
    """Pusty wynik to awaria, nie stan — patrz `test_http_error_...`."""
    _mock_archive(
        content=b"""<?xml version="1.0" encoding="utf-8"?>
        <stopy_procentowe_archiwum />"""
    )
    provider = NbpReferenceRatesProvider()

    with pytest.raises(ProviderUnavailableError):
        await provider.get_reference_rates()
    await provider.aclose()


def test_archive_is_superset_of_current_file() -> None:
    """Ostatni wpis archiwum == stan bieżący (założenie „jedno żądanie").

    Bez sieci: porównanie dwóch nagranych fixture'ów. Test pilnuje decyzji
    projektowej (pobieramy tylko archiwum), więc gdyby NBP rozjechał te dwa
    pliki, dowiemy się przy odświeżeniu fixture'ów, a nie z błędnego Sharpe'a.
    """
    archive = ElementTree.fromstring(_fixture_bytes("stopy_archiwum.xml"))
    current = ElementTree.fromstring(_fixture_bytes("stopy_biezace.xml"))

    last_entry = archive.findall("pozycje")[-1]
    archive_ref = next(p for p in last_entry.findall("pozycja") if p.get("id") == "ref")
    current_ref = next(
        p for p in current.iter("pozycja") if p.get("id") == "ref" and p.get("oprocentowanie")
    )

    assert last_entry.get("obowiazuje_od") == current_ref.get("obowiazuje_od")
    assert archive_ref.get("oprocentowanie") == current_ref.get("oprocentowanie")


def test_archive_publication_date_attribute_is_stale() -> None:
    """Dokumentuje pułapkę: `data_publikacji` w archiwum jest nieaktualna.

    Ten test nie broni kodu — broni komentarza. Gdyby ktoś kiedyś sięgnął po
    `data_publikacji` jako miarę świeżości, ten plik pokazuje czarno na
    białym, że atrybut stoi w 2015 roku, mimo że treść sięga 2026.
    """
    archive = ElementTree.fromstring(_fixture_bytes("stopy_archiwum.xml"))
    published = archive.get("data_publikacji") or ""
    latest = archive.findall("pozycje")[-1].get("obowiazuje_od") or ""

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", published)
    assert published < latest
