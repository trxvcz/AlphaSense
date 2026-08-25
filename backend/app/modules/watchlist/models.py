"""Modele ORM modułu `watchlist`: `watchlists`, `watchlist_items`.

Plan krok 43 (etap 8). `docs/model-danych.md:28` rezerwował te tabele jako
„Faza 2" bez kolumn — schemat powstaje razem z migracją tego kroku.

**Watchlista to lista OBSERWOWANYCH aktywów, nie drugi portfel.** Nie ma
ilości, nie ma wyceny, nie ma snapshotów i nie wchodzi do żadnej analityki
(CLAUDE.md #3.11 — nie rozszerzamy v2 „przy okazji"). Gdyby kiedyś miała
mieć wycenę, byłby to portfel i należałoby użyć `portfolios`.

`Watchlist.user_id` kaskaduje `ON DELETE CASCADE` z `users` (CLAUDE.md
#3.5) — kolejny odcinek ścieżki kaskadowej w dół, po `portfolios`.
`WatchlistItem` kaskaduje dalej z `watchlists`. FK do `assets` **bez**
kaskady, dokładnie jak `Holding.asset_id`: wygaszenie aktywa nie może
wymazywać cudzych list (od tego jest `assets.is_active`).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Watchlist(Base):
    """Nazwana lista obserwowanych aktywów, należąca do użytkownika.

    `UNIQUE (user_id, name)` — dwie listy o tej samej nazwie u jednego
    użytkownika to prawie zawsze pomyłka, a przy wyborze z listy rozwijanej
    byłyby nieodróżnialne. Ograniczenie jest **per użytkownik**, nie
    globalne: nazwa „Obserwowane" nie może być zajęta przez kogoś obcego.
    """

    __tablename__ = "watchlists"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_watchlists_user_name"),
        CheckConstraint("length(trim(name)) > 0", name="ck_watchlists_name_not_blank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WatchlistItem(Base):
    """Jedno aktywo na liście obserwowanych.

    Klucz główny złożony `(watchlist_id, asset_id)` zamiast sztucznego `id`:
    to samo aktywo dwa razy na tej samej liście nie ma znaczenia, a klucz
    naturalny daje idempotentne „dodaj do listy" (`ON CONFLICT DO NOTHING`)
    bez osobnego `UNIQUE`.

    `note` to notatka użytkownika („czekam na wyniki Q3"), nie dana
    rynkowa — jedyny powód, dla którego watchlista jest czymś więcej niż
    zbiorem tickerów.
    """

    __tablename__ = "watchlist_items"

    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watchlists.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id"), primary_key=True
    )
    note: Mapped[str | None] = mapped_column(String(500), default=None)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Lista użytkownika czytana jest zawsze „wszystkie moje listy, alfabetycznie",
# więc indeks po `user_id` (nazwa i tak jest w UNIQUE wyżej).
Index("ix_watchlists_user_id", Watchlist.user_id)
# Odwrotny kierunek: „na których listach jest to aktywo" — potrzebne przy
# usuwaniu aktywa z widoku aktywa i przy przyszłym powiązaniu z newsami.
Index("ix_watchlist_items_asset_id", WatchlistItem.asset_id)
