"""Modele ORM modułu `news`: `news` i `news_assets`.

Plan krok 46 (etap 9). `docs/model-danych.md:30` rezerwował te tabele jako
„Faza 3" bez kolumn — schemat powstaje tutaj, razem z migracją.

Newsy nie są własnością użytkownika, tak samo jak `assets` i `prices`:
jedna depesza o KGHM dotyczy każdego, kto ma KGHM w portfelu, więc
przechowujemy ją raz i wiążemy z aktywem, nie z użytkownikiem. Izolacja
danych dzieje się przy **odczycie** — endpoint filtruje newsy po aktywach
z portfela przekazanego przez `get_owned_portfolio` (CLAUDE.md #3.2).
Stąd brak jakiegokolwiek FK do `users` i brak `ON DELETE CASCADE`
z tej strony.

**Deduplikacja stoi na dwóch niezależnych filarach**, bo jeden nie wystarcza:

- `url` z ograniczeniem UNIQUE łapie ponowne pobranie tego samego wpisu
  przy kolejnym przebiegu joba (RSS oddaje przesuwające się okno, więc
  większość pozycji w każdym przebiegu jest już w bazie);
- `content_hash` łapie **tę samą depesję pod różnymi adresami** — PAP-owa
  informacja trafia do Bankiera, Money i StockWatch osobno, każdy z własnym
  URL-em i własnymi parametrami śledzącymi. Bez tego feed użytkownika
  byłby potrojony.

`content_hash` liczymy z tytułu i daty publikacji po normalizacji, nie
z treści — RSS-y oddają skróty różnej długości, więc treść nie jest stabilną
podstawą porównania. Kolizja hashów oznacza dwie różne depesze o identycznym
tytule opublikowane w tej samej minucie; przy takim zbiegu okoliczności
zwinięcie ich w jeden wpis jest zachowaniem właściwym, nie błędem.

**`sentiment` jest nullowalny i to jest stan normalny, nie brak danych do
uzupełnienia** (CLAUDE.md #3.15). Polskie feedy RSS sentymentu nie niosą,
a darmowe źródła, które go dają (Finnhub, Alpha Vantage), pokrywają w praktyce
wyłącznie spółki amerykańskie. `sentiment_source` istnieje po to, żeby UI
mogło odróżnić „dostawca ocenił neutralnie" od „nikt tego nie ocenił" —
sama wartość `sentiment` tego nie rozróżnia.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class News(Base):
    """Pojedyncza informacja z RSS albo od dostawcy danych.

    `published_at` pochodzi od źródła i bywa nieufne (feedy potrafią oddać
    czas lokalny bez strefy) — normalizacja do UTC dzieje się w warstwie
    ingestii, tu trzyma już `timezone=True`. `fetched_at` to nasz własny
    czas pobrania i jest zawsze wiarygodny; oba są potrzebne, bo świeżość
    danych mierzymy naszym zegarem, a kolejność w feedzie — zegarem źródła
    (CLAUDE.md #23).
    """

    __tablename__ = "news"
    __table_args__ = (
        UniqueConstraint("url", name="uq_news_url"),
        UniqueConstraint("content_hash", name="uq_news_content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    title: Mapped[str] = mapped_column(String())
    url: Mapped[str] = mapped_column(String())
    source: Mapped[str] = mapped_column(String())
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str | None] = mapped_column(String(), default=None)
    sentiment: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), default=None)
    sentiment_source: Mapped[str | None] = mapped_column(String(), default=None)


class NewsAsset(Base):
    """Powiązanie informacji z aktywem — relacja wiele-do-wielu.

    Jedna depesza o kursie złota dotyczy i XAU, i spółek wydobywczych,
    a jedno aktywo ma wiele newsów. Klucz złożony `(news_id, asset_id)`
    zamiast sztucznego `id`: wiersz nie ma tożsamości poza tą parą,
    a ograniczenie unikalności jest tu potrzebne i tak — ponowne
    tagowanie tego samego newsu nie ma tworzyć duplikatu.

    `ON DELETE CASCADE` w obie strony: usunięcie newsu albo aktywa
    nie ma zostawiać osieroconego powiązania. To nie jest ścieżka
    własności użytkownika, więc nie kłóci się z CLAUDE.md #3.5.

    Indeks `(asset_id, published_at DESC)` był **z góry przewidziany**
    w `docs/model-danych.md:42` i realizuje główne zapytanie feedu:
    „najnowsze newsy dla tego zbioru aktywów". `published_at` jest
    zdenormalizowane z `news` właśnie po to — bez tego każde zapytanie
    feedu sortowałoby po `JOIN`-ie, nie po indeksie.
    """

    __tablename__ = "news_assets"

    news_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("news.id", ondelete="CASCADE"),
        primary_key=True,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # `source` — powiązanie podał dostawca (Finnhub pytany o symbol);
    # `heuristic` — wynik dopasowania tekstu po naszej stronie
    # (`matching.py`). Rozróżnienie musi dojść do UI, bo to fakt kontra
    # przybliżenie (CLAUDE.md #3.15). Domyślnie `heuristic`: to wartość
    # ostrożniejsza, więc pominięcie jej przy zapisie zaniża pewność,
    # zamiast fałszywie ją podnosić.
    match_confidence: Mapped[str] = mapped_column(String(), server_default=text("'heuristic'"))


# Feed bez filtra po aktywach (widok „wszystko, co dotyczy Twojego portfela"
# przy pustym portfelu, a także panel diagnostyczny ingestii) czyta wyłącznie
# najnowsze wpisy — stąd osobny indeks malejący po samej dacie publikacji.
Index("ix_news_published_at_desc", News.published_at.desc())


# Poza klasą, tak jak `ix_prices_asset_id_date_desc` w module `marketdata`:
# `mapped_column` nie przyjmuje kierunku sortowania, a `DESC` jest tu istotne
# — feed czyta wyłącznie najnowsze wpisy dla zbioru aktywów.
Index(
    "ix_news_assets_asset_id_published_at_desc",
    NewsAsset.asset_id,
    NewsAsset.published_at.desc(),
)
