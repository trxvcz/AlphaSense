"""Modele ORM modułu `portfolio`: `portfolios`, `holdings`, `portfolio_valuations`.

Plan krok 17-18 (etap 3). `Portfolio.user_id` kaskaduje `ON DELETE CASCADE`
z `users` (CLAUDE.md #3.5, docs/model-danych.md) — kolejny odcinek ścieżki
kaskadowej od użytkownika w dół, po `refresh_tokens`. `Holding` i
`PortfolioValuation` kaskadują dalej z `portfolios`.

`Holding.asset_id` wskazuje na `assets` (moduł `marketdata`) — FK bez
`ondelete="CASCADE"` (usunięcie aktywa nie jest w zakresie tego etapu i nie
powinno kaskadowo wymazywać pozycji użytkownika; `assets.is_active` służy do
„wygaszania” aktywów).

CRUD i logika wyceny (`schemas.py`, `service.py`) — kolejne kroki planu
(etap 5), poza zakresem tego pliku.
"""

from __future__ import annotations

import uuid
from datetime import date as date_
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Portfolio(Base):
    """Portfel inwestycyjny użytkownika.

    `holdings_version` jest znacznikiem do klucza cache Redis
    (`{zasób}:{portfolio_id}:{holdings_version}:{data_eod}`, CLAUDE.md #3.7)
    — inkrementowany przy każdej zmianie składu `holdings` (etap 5); tutaj
    tylko kolumna, logika inkrementacji poza zakresem tego kroku.
    `holdings_changed_at` to data ostatniej zmiany składu (dla
    `PortfolioValuation.composition_change` w jobie snapshotów EOD, ADR-101)
    — nullable, ustawiana logiką aplikacyjną przy CRUD pozycji (etap 5).
    """

    __tablename__ = "portfolios"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String())
    type: Mapped[str] = mapped_column(String())
    holdings_version: Mapped[int] = mapped_column(Integer(), server_default=text("0"))
    holdings_changed_at: Mapped[date_ | None] = mapped_column(Date(), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Holding(Base):
    """Pozycja w portfelu — jedna sztuka aktywa na portfel (`UNIQUE`).

    `avg_cost`/`cost_currency` są opcjonalne (użytkownik może nie znać/nie
    podawać kosztu nabycia — serce produktu to struktura, nie księgowość,
    CLAUDE.md #1); jeśli `avg_cost` jest podany, `cost_currency` jest
    wymagany (CHECK `avg_cost_needs_currency`). `valid_from` domyślnie data
    dodania pozycji — snapshoty są append-only (ADR-101), edycja wpływa
    tylko na przyszłość.
    """

    __tablename__ = "holdings"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "asset_id", name="uq_holdings_portfolio_asset"),
        CheckConstraint("quantity >= 0", name="quantity_nonneg"),
        CheckConstraint(
            "avg_cost IS NULL OR cost_currency IS NOT NULL",
            name="avg_cost_needs_currency",
        ),
        Index("ix_holdings_portfolio_id", "portfolio_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portfolios.id", ondelete="CASCADE"),
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id"),
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    avg_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), default=None)
    cost_currency: Mapped[str | None] = mapped_column(String(3), default=None)
    valid_from: Mapped[date_ | None] = mapped_column(Date(), server_default=func.current_date())
    note: Mapped[str | None] = mapped_column(String(), default=None)


class PortfolioValuation(Base):
    """Dzienny snapshot wartości portfela w PLN (ADR-101, opcja A).

    Append-only — bez kolumny przepływów pieniężnych (poza zakresem, patrz
    CLAUDE.md #1). `composition_change` oznacza dzień, w którym skład
    portfela się zmienił (informacyjnie, dla wykresów — żeby nie sugerować
    zwrotu, którego portfel nie „przeżył” w tym składzie).
    """

    __tablename__ = "portfolio_valuations"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        primary_key=True,
    )
    date: Mapped[date_] = mapped_column(Date(), primary_key=True)
    value_pln: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    composition_change: Mapped[bool] = mapped_column(Boolean(), server_default=text("false"))


# Indeks `(portfolio_id, date DESC)` — zapytania o historię wyceny portfela
# sortują od najnowszej daty; wyrażenie `.desc()` wymaga atrybutu klasy
# (dostępny dopiero po zdefiniowaniu mapowania), stąd poza `__table_args__`.
Index(
    "ix_portfolio_valuations_portfolio_id_date_desc",
    PortfolioValuation.portfolio_id,
    PortfolioValuation.date.desc(),
)
