"""`NbpReferenceRatesProvider` — stopa referencyjna NBP (plan krok 41a, etap 8).

Sharpe potrzebuje stopy wolnej od ryzyka. Plan kroku 41 mówi „stopa
referencyjna NBP jako konfigurowalny parametr"; decyzją użytkownika
(2026-08-25) bierzemy ją z **rzeczywistego źródła**, nie ze stałej w ENV,
i to w wariancie historycznym — Sharpe liczony na wieloletniej serii ze
stałą dzisiejszą stopą byłby po prostu policzony źle (stopa referencyjna
szła w tym okresie od 0,10% do 6,75%).

**Źródło.** `api.nbp.pl` (którego używa `NbpProvider` do kursów i złota)
**nie wystawia stóp procentowych** — sprawdzone na żywo, `/api/interestrates`
zwraca 404. NBP publikuje je jako statyczne pliki XML:

- `https://static.nbp.pl/dane/stopy/stopy_procentowe.xml` — stan bieżący,
- `https://static.nbp.pl/dane/stopy/stopy_procentowe_archiwum.xml` —
  **pełna historia zmian od 1998-02-26**, każda zmiana jako `<pozycje
  obowiazuje_od="...">` z pozycjami `ref`/`lom`/`dep`/`red`/`dys`.

Bierzemy **wyłącznie archiwum**: zweryfikowane na żywo, że jego ostatni
wpis (`2026-03-05`, `ref = 3,75`) jest identyczny z plikiem bieżącym, więc
archiwum jest nadzbiorem i drugie żądanie nic by nie wniosło poza kolejnym
punktem awarii.

**Pułapka: `data_publikacji` w archiwum kłamie.** Atrybut korzenia to
`data_publikacji="2015-03-04"`, mimo że treść sięga 2026-03-05 (NBP go nie
aktualizuje). Świeżość liczymy **wyłącznie** z `max(obowiazuje_od)` —
gdybyśmy wzięli `data_publikacji`, `/meta/freshness` raportowałby dane jako
przeterminowane o dekadę.

**Format liczb.** `oprocentowanie="3,75"` — przecinek dziesiętny, wartość
w **procentach**. Zwracamy ułamek (`Decimal("0.0375")`), bo tak wchodzi do
wzoru na Sharpe'a; zamiana idzie przez `Decimal(str)`, nigdy przez `float`
(CLAUDE.md #3.1).

**Bierzemy tylko `ref`.** Pozostałe stopy (lombardowa, depozytowa,
redyskontowa, dyskontowa) nie mają w tym projekcie żadnego odbiorcy;
zapisywanie ich „na zapas" to zakres, którego nikt nie zamawiał
(CLAUDE.md #3.11).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Final
from xml.etree import ElementTree

import httpx
import structlog

from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.circuit_breaker import CircuitBreaker
from app.modules.marketdata.providers.rate_limiter import RateLimiter

logger = structlog.get_logger(__name__)

ARCHIVE_URL: Final[str] = "https://static.nbp.pl/dane/stopy/stopy_procentowe_archiwum.xml"

# Identyfikator stopy referencyjnej w XML-u NBP.
_REFERENCE_RATE_ID: Final[str] = "ref"

_DEFAULT_TIMEOUT_SECONDS: Final[float] = 15.0

# Twardy limit rozmiaru odpowiedzi przed parsowaniem XML. Parsujemy
# `xml.etree.ElementTree` ze standardowej biblioteki (bez dokładania
# `defusedxml` — nowa zależność wymagałaby osobnej decyzji, CLAUDE.md #10).
# ElementTree w CPythonie nie rozwiązuje encji zewnętrznych, więc realnym
# ryzykiem zostaje wyłącznie rozdęcie encjami wewnętrznymi („billion
# laughs"), a to zatrzymuje właśnie limit rozmiaru wejścia. Plik NBP ma
# ~37 kB, więc 4 MB to zapas rzędu stukrotnego, a nie ciasny próg.
_MAX_RESPONSE_BYTES: Final[int] = 4 * 1024 * 1024

_PERCENT: Final[Decimal] = Decimal("100")


@dataclass(frozen=True)
class ReferenceRate:
    """Stopa referencyjna NBP obowiązująca **od** `effective_from`.

    `rate` jest ułamkiem rocznym (`0.0375` = 3,75% p.a.), nie procentem —
    jednostka jest tu częścią kontraktu, bo pomyłka o czynnik 100 w Sharpie
    nie rzuca wyjątkiem, tylko daje wynik, który wygląda wiarygodnie.

    Zapis jest punktowy (zmiana stopy), nie dzienny — obowiązywanie do
    następnej zmiany wynika z lookupu `max(effective_from) <= D` przy
    odczycie, dokładnie jak przy kursach walut (CLAUDE.md #3.5).
    """

    effective_from: date
    rate: Decimal


class NbpReferenceRatesProvider:
    """Pobiera pełną historię stopy referencyjnej NBP z archiwum XML.

    Świadomie **nie** implementuje `Protocol DataProvider` — stopa
    procentowa to nie `Capability.FX` ani `OHLCV`, a wciskanie jej w tamten
    kontrakt (np. jako pseudo-waluty) zaśmieciłoby `FallbackChain`
    dostawcą, którego żaden `Capability` nie opisuje. Stąd też osobny,
    wąski wrapper `GuardedReferenceRates` zamiast `Guarded` (ten proxy'uje
    konkretne metody `DataProvider`).
    """

    name = "nbp"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        archive_url: str = ARCHIVE_URL,
    ) -> None:
        self._client = client if client is not None else httpx.AsyncClient()
        self._owns_client = client is None
        self._archive_url = archive_url

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_reference_rates(self) -> list[ReferenceRate]:
        """Wszystkie zmiany stopy referencyjnej, rosnąco po `effective_from`.

        Rzuca `ProviderUnavailableError` przy błędzie sieci/HTTP/parsowania
        — w odróżnieniu od `NbpProvider.get_fx`, gdzie 404 znaczy „brak
        notowań w zakresie" (weekend). Tu nie ma odpowiednika weekendu:
        archiwum stóp albo jest, albo źródło padło.
        """
        try:
            response = await self._client.get(self._archive_url, timeout=_DEFAULT_TIMEOUT_SECONDS)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                "Nie udało się pobrać archiwum stóp procentowych NBP.",
                details={"provider": self.name, "url": self._archive_url},
            ) from exc

        payload = response.content
        if len(payload) > _MAX_RESPONSE_BYTES:
            raise ProviderUnavailableError(
                "Archiwum stóp procentowych NBP przekracza dopuszczalny rozmiar.",
                details={"provider": self.name, "size": len(payload)},
            )

        rates = _parse_archive(payload)
        logger.info(
            "nbp_rates.fetched",
            count=len(rates),
            latest=rates[-1].effective_from.isoformat() if rates else None,
        )
        return rates


def _parse_archive(payload: bytes) -> list[ReferenceRate]:
    """Parsuje archiwum XML do posortowanej listy zmian stopy referencyjnej.

    Wpisy bez pozycji `ref` (formalnie dopuszczalne — najstarsze tabele NBP
    mają różne zestawy stóp) są **pomijane z logiem**, nie wywalają całego
    przebiegu: jedna dziura w 1998 roku nie może odciąć nas od stopy
    z zeszłego miesiąca.
    """
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise ProviderUnavailableError(
            "Archiwum stóp procentowych NBP nie jest poprawnym XML-em.",
            details={"provider": "nbp"},
        ) from exc

    rates: list[ReferenceRate] = []
    for entry in root.findall("pozycje"):
        effective_raw = entry.get("obowiazuje_od")
        if not effective_raw:
            continue
        reference = next(
            (item for item in entry.findall("pozycja") if item.get("id") == _REFERENCE_RATE_ID),
            None,
        )
        if reference is None:
            logger.info("nbp_rates.entry_without_reference_rate", effective_from=effective_raw)
            continue
        try:
            effective_from = date.fromisoformat(effective_raw)
            rate = _as_fraction(reference.get("oprocentowanie"))
        except (ValueError, InvalidOperation):
            logger.warning(
                "nbp_rates.unparsable_entry",
                effective_from=effective_raw,
                rate=reference.get("oprocentowanie"),
            )
            continue
        rates.append(ReferenceRate(effective_from=effective_from, rate=rate))

    if not rates:
        raise ProviderUnavailableError(
            "Archiwum stóp procentowych NBP nie zawiera żadnej stopy referencyjnej.",
            details={"provider": "nbp"},
        )
    # Plik NBP jest posortowany rosnąco, ale to jego wewnętrzna konwencja,
    # nie kontrakt — sortujemy sami, bo od kolejności zależy poprawność
    # lookupu i `latest` w logu.
    rates.sort(key=lambda item: item.effective_from)
    return rates


def _as_fraction(raw: str | None) -> Decimal:
    """`"3,75"` (procent, przecinek dziesiętny) → `Decimal("0.0375")` (ułamek)."""
    if raw is None:
        raise ValueError("brak atrybutu `oprocentowanie`")
    return Decimal(raw.strip().replace(",", ".")) / _PERCENT


class GuardedReferenceRates:
    """`NbpReferenceRatesProvider` owinięty limiterem i bezpiecznikiem.

    Ta sama kolejność co w `Guarded`/`GuardedNews`: obwód → token → żądanie.
    Job jest tygodniowy i robi jedno żądanie, więc limiter nie ma tu czego
    dławić — bezpiecznik ma. Bez niego padnięty `static.nbp.pl` oznaczałby
    pełny timeout przy każdym przebiegu i przy każdym ręcznym uruchomieniu;
    dywidendy (krok 47) tej ochrony nie dostały i było to znalezisko
    recenzji, którego tu nie powtarzamy.
    """

    def __init__(
        self,
        provider: NbpReferenceRatesProvider,
        limiter: RateLimiter,
        breaker: CircuitBreaker,
    ) -> None:
        self._provider = provider
        self._limiter = limiter
        self._breaker = breaker

    @property
    def name(self) -> str:
        return self._provider.name

    async def get_reference_rates(self) -> list[ReferenceRate]:
        if await self._breaker.is_open() and not await self._breaker.allow_trial():
            raise ProviderUnavailableError(
                "Źródło stóp procentowych NBP tymczasowo wyłączone przez bezpiecznik.",
                details={"provider": self.name},
            )
        await self._limiter.acquire()
        try:
            result = await self._provider.get_reference_rates()
        except Exception:
            await self._breaker.record_failure()
            raise
        await self._breaker.record_success()
        return result
