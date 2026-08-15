"""Kontrakt dostawców newsów (`NewsProvider`), DTO `NewsItem` i strażnik
`GuardedNews` (plan krok 46, etap 9).

**Dlaczego osobny protokół zamiast dopisania metody do `DataProvider`:**
`DataProvider` (`marketdata/providers/base.py`) opisuje trzy operacje —
OHLCV, FX i metadane — i wszystkie są **per symbol**. News nie jest żadną
z nich: feed RSS Bankiera nie przyjmuje symbolu, tylko oddaje strumień
wszystkiego, co się dziś ukazało, a wiązanie z aktywem robimy sami po
stronie ingestii. Dopisanie `get_news` do tamtego protokołu zmusiłoby
NBP, Stooq, Binance i yfinance do implementowania metody, której nigdy
nie wywołają, a `Guarded` — do delegowania czwartej metody dla providerów,
które jej nie mają. Stąd własny, dwuelementowy protokół tutaj.

**Odporność jest ta sama, nie podobna.** `GuardedNews` reużywa `RateLimiter`
i `CircuitBreaker` z modułu `marketdata` — te same klasy, ten sam Redis, ta
sama semantyka otwartego obwodu (CLAUDE.md #23). Powielona jest wyłącznie
pętla delegująca, bo `Guarded` ma na sztywno wpisane trzy metody
`DataProvider` i rozszerzanie go o czwartą oznaczałoby zmianę w cudzym
module „przy okazji" (CLAUDE.md §4.3).

**`NewsItem` jest zamrożoną dataclassą, nie modelem Pydantic** — dokładnie
z tego powodu co `PriceBar`: to DTO między providerem a warstwą ingestii,
nigdy nie przekracza granicy HTTP, a wyrozumiała koercja Pydantic
maskowałaby błędy parsowania dat w feedach, które i tak są głównym
źródłem kłopotów przy RSS.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, TypeVar, runtime_checkable
from urllib.parse import urlsplit

import structlog

from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.circuit_breaker import CircuitBreaker
from app.modules.marketdata.providers.rate_limiter import RateLimiter

logger = structlog.get_logger(__name__)

_T = TypeVar("_T")


class NewsCapability(StrEnum):
    """Możliwości dostawcy newsów.

    `FEED` — strumień wszystkiego, co się ukazało (RSS). Wiązanie z aktywami
    robi warstwa ingestii, dopasowując tickery i nazwy spółek do treści.

    `PER_SYMBOL` — dostawca umie oddać newsy dla konkretnego symbolu
    (Finnhub `/company-news`). Wiązanie jest wtedy pewne, bo pochodzi od
    źródła, a nie z naszego dopasowania tekstu.
    """

    FEED = "feed"
    PER_SYMBOL = "per_symbol"


# Adres newsa jest w całości pod kontrolą cudzego feedu i trafia prosto
# do `href` w przeglądarce użytkownika. React **nie** blokuje `javascript:`
# ani `data:` w `href` — wypisuje ostrzeżenie w konsoli i renderuje link,
# więc jeden wpis w przejętym feedzie wydawcy wystarczy do wykonania skryptu
# w kontekście zalogowanej sesji. Dziedzina jest domknięta od strony
# dozwolonych schematów (allowlist), nie od strony zakazanych: lista
# schematów, które przeglądarki umieją wykonać, rośnie, a lista tych,
# których potrzebuje link do artykułu, ma dokładnie dwa elementy.
_SAFE_URL_SCHEMES = frozenset({"http", "https"})


def is_safe_http_url(url: str) -> bool:
    """Czy adres nadaje się do wstawienia w `href` bez ryzyka wykonania kodu.

    Znaki sterujące odrzucane osobno i **przed** parsowaniem, bo przeglądarki
    usuwają je z adresu przed interpretacją schematu: `"java\\nscript:alert(1)"`
    przechodzi przez `urlsplit` jako ścieżka względna bez schematu, a w `href`
    wykonuje się jako `javascript:`. `urlsplit` sam z siebie tej różnicy nie widzi.

    Wymagany jest też niepusty host — `http:///cokolwiek` ma poprawny schemat,
    ale nie jest adresem, pod który da się pójść.
    """
    if not url or any(ch in url for ch in "\t\r\n") or any(ord(ch) < 0x20 for ch in url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        # Nieparsowalny adres (np. nawiasy kwadratowe w IPv6 bez domknięcia).
        return False
    return parts.scheme.lower() in _SAFE_URL_SCHEMES and bool(parts.netloc)


@dataclass(frozen=True, slots=True)
class NewsItem:
    """Jedna informacja zwrócona przez dostawcę — jeszcze bez `asset_id`
    i bez `content_hash`. Jedno i drugie dokłada warstwa ingestii: tłumaczenie
    na aktywa wymaga bazy, a hash jest naszą konwencją deduplikacji, nie
    własnością źródła.

    `url` **musi przejść przez `is_safe_http_url`** po stronie providera —
    wpis z niebezpiecznym schematem jest pomijany tak samo jak wpis bez
    tytułu czy bez daty, a nie wpuszczany do bazy z nadzieją, że front go
    odfiltruje. Warstwa ingestii dostaje adresy już bezpieczne.

    `published_at` **musi być świadome strefy czasowej**. Feedy RSS bywają
    pod tym względem niechlujne (czas lokalny bez strefy, `+0000` doklejone
    do czasu warszawskiego) — normalizacja należy do konkretnego providera,
    bo tylko on wie, jaką strefę zakłada jego źródło. Warstwa ingestii
    dostaje już poprawny moment w czasie i nie zgaduje.

    `sentiment` jest `None` wszędzie tam, gdzie źródło go nie podaje — czyli
    w praktyce we wszystkich polskich feedach RSS. To **stan normalny**,
    nie brak do uzupełnienia (CLAUDE.md #3.15). `sentiment_source` niesie
    nazwę dostawcy oceny, żeby UI umiało odróżnić „oceniono jako neutralne"
    od „nikt nie oceniał".
    """

    title: str
    url: str
    source: str
    published_at: datetime
    summary: str | None = None
    sentiment: Decimal | None = None
    sentiment_source: str | None = None
    symbols: tuple[str, ...] = ()


@runtime_checkable
class NewsProvider(Protocol):
    """Kontrakt dostawcy newsów.

    `symbol` jest opcjonalny, bo dwa rodzaje źródeł zachowują się inaczej:
    feed RSS ignoruje go i oddaje wszystko, dostawca per-symbol bez niego
    nie ma czego zwrócić. Implementacja, która nie obsługuje trybu, ma
    zwrócić pustą listę — nie rzucać wyjątkiem, bo brak wsparcia nie jest
    awarią i nie powinien otwierać obwodu w `CircuitBreaker`.
    """

    name: str
    supports: set[NewsCapability]

    async def get_news(self, *, symbol: str | None = None) -> list[NewsItem]: ...


@runtime_checkable
class BatchNewsProvider(NewsProvider, Protocol):
    """Dostawca, który umie oddać newsy dla **wielu symboli w jednym
    zapytaniu** (Alpha Vantage: `tickers=AAPL,MSFT`).

    Osobny protokół, a nie pole w `NewsProvider`, bo to nie jest wariant
    tej samej operacji — to inny koszt. Dla dostawcy z dobowym limitem
    zapytań (Alpha Vantage: 25/dobę na darmowym planie) pętla „symbol po
    symbolu" i jedno zapytanie zbiorcze różnią się o rząd wielkości
    w budżecie, więc wołający musi tę różnicę widzieć w typie, a nie
    odkrywać ją po wyczerpaniu limitu.
    """

    async def get_news_batch(self, symbols: list[str]) -> list[NewsItem]: ...


class GuardedNews:
    """Opakowuje `NewsProvider` w limiter zapytań i bezpiecznik.

    Kolejność jest istotna i taka sama jak w `Guarded`: najpierw sprawdzenie
    obwodu (nie ma sensu czekać na token dla dostawcy, który i tak jest
    uznany za martwy), potem token limitera, dopiero potem żądanie.
    """

    def __init__(
        self,
        provider: NewsProvider,
        limiter: RateLimiter,
        breaker: CircuitBreaker,
    ) -> None:
        self._provider = provider
        self._limiter = limiter
        self._breaker = breaker

    @property
    def name(self) -> str:
        return self._provider.name

    @property
    def supports(self) -> set[NewsCapability]:
        return self._provider.supports

    async def _guarded_call(self, call: Callable[[], Awaitable[_T]]) -> _T:
        if await self._breaker.is_open() and not await self._breaker.allow_trial():
            raise ProviderUnavailableError(
                "Dostawca newsów tymczasowo wyłączony przez bezpiecznik.",
                details={"provider": self._provider.name},
            )
        await self._limiter.acquire()
        try:
            result = await call()
        except Exception:
            await self._breaker.record_failure()
            raise
        await self._breaker.record_success()
        return result

    async def get_news(self, *, symbol: str | None = None) -> list[NewsItem]:
        return await self._guarded_call(lambda: self._provider.get_news(symbol=symbol))

    async def get_news_batch(self, symbols: list[str]) -> list[NewsItem]:
        """Jedno zapytanie na wiele symboli — tylko dla `BatchNewsProvider`.

        Brak wsparcia jest tu **błędem programisty**, nie stanem
        środowiska, więc `TypeError`, a nie `ProviderUnavailableError`:
        cichy fallback na pętlę `get_news` wyglądałby jak sukces, a byłby
        wielokrotnością zapytań u dostawcy, którego jedynym powodem do
        istnienia w tej roli jest oszczędzanie zapytań (patrz
        `BatchNewsProvider`).
        """
        provider = self._provider
        if not isinstance(provider, BatchNewsProvider):
            raise TypeError(f"Dostawca {provider.name!r} nie obsługuje trybu zbiorczego.")
        return await self._guarded_call(lambda: provider.get_news_batch(symbols))
