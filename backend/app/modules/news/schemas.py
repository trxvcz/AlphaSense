"""Schematy Pydantic modułu `news` (plan krok 46, etap 9)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer


class NewsAssetRefOut(BaseModel):
    """Aktywo, którego dotyczy news, wraz z **pochodzeniem powiązania**.

    `match_confidence`:

    - `source` — powiązanie podał dostawca pytany o symbol (Finnhub
      `/company-news`, Alpha Vantage `ticker_sentiment`). To fakt.
    - `heuristic` — dopasowanie polskiego tekstu po naszej stronie
      (`matching.py`). To przybliżenie i UI **musi** je oznaczyć
      (CLAUDE.md #3.15).

    Pole jest per aktywo, nie per news, i to jest istotne: jedna depesza
    potrafi być pewnie powiązana z AAPL (bo Finnhub tak powiedział)
    i jednocześnie zgadnięta dla złota (bo padło słowo „złoto"). Jedna
    zbiorcza flaga na news musiałaby wybrać jedną z tych dwóch prawd
    i drugą przekłamać.
    """

    symbol: str
    match_confidence: str


class NewsItemOut(BaseModel):
    """Jeden wpis feedu.

    `sentiment` jako `string | null` — kwoty i liczby dziesiętne wychodzą
    z API tekstem (CLAUDE.md #3.1), także wtedy, gdy nie są pieniędzmi:
    `float` w JSON-ie to ta sama utrata precyzji niezależnie od jednostki,
    a front ma jeden formater dla wszystkich liczb dziesiętnych.

    `sentiment_source` istnieje po to, żeby UI odróżniło „dostawca ocenił
    jako neutralne" (`sentiment=0`, źródło podane) od „nikt nie oceniał"
    (`sentiment=null`, źródło `null`). Bez tego pola oba wyglądałyby na
    brak opinii, a to dwie różne informacje (CLAUDE.md #3.15).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    url: str
    source: str
    published_at: datetime
    summary: str | None
    sentiment: Decimal | None
    sentiment_source: str | None
    # Wyłącznie aktywa **z portfela pytającego** (zawężenie w
    # `repository.list_news_links`) — ta sama depesza bywa powiązana
    # z pozycjami innych użytkowników i ich symbole nie mają tu wstępu
    # (CLAUDE.md #3.2).
    assets: list[NewsAssetRefOut]

    @field_serializer("sentiment")
    def _serialize_sentiment(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class NewsFeedOut(BaseModel):
    """Feed dla portfela wraz z informacją o tym, czego w nim NIE ma.

    `assets_without_news` nie jest ozdobnikiem: użytkownik z pozycją, o której
    nic się nie ukazało, i użytkownik, którego pozycji nie umiemy rozpoznać
    w tekście (patrz ograniczenie odmiany w `matching.py`), widzą ten sam
    pusty feed. To pole pozwala UI powiedzieć, których pozycji feed nie
    obejmuje, zamiast milczeć.
    """

    items: list[NewsItemOut]
    assets_covered: int
    assets_without_news: list[str]
