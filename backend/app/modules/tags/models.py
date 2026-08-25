"""Modele ORM modułu `tags`: `tags`, `asset_tags`.

Plan krok 43 (etap 8). `docs/model-danych.md:29` rezerwował te tabele jako
„Faza 2" bez kolumn — schemat powstaje razem z migracją tego kroku.

**Tag wisi na AKTYWIE, nie na pozycji.** Tak to rezerwuje model danych
(`asset_tags`) i tak jest użyteczniej: „dywidendowe" albo „spekulacyjne" to
cecha spółki, nie konkretnego wiersza w konkretnym portfelu. Dzięki temu
tag nadany raz działa we wszystkich portfelach użytkownika, a filtr
struktury (`GET /allocation?tags=`) zawęża pozycje po tagach ich aktywów.

**Tag należy do użytkownika, aktywo jest globalne.** `assets` to słownik
wspólny dla całej instancji, więc `asset_tags` nie może być „tagiem na
aktywie" w sensie globalnym — własność niesie `tags.user_id`, a izolacja
przy odczycie idzie zawsze przez `JOIN tags`. Bez tego użytkownik A
zobaczyłby, że ktoś oznaczył PKN jako „do sprzedania".
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


class Tag(Base):
    """Etykieta użytkownika, nadawana aktywom.

    `UNIQUE (user_id, name)` — dwa tagi „dywidendowe" u jednego użytkownika
    byłyby nieodróżnialne w filtrze i dzieliłyby pozycje na dwie grupy bez
    powodu. Per użytkownik, nie globalnie.

    `color` jest opcjonalny i **nigdy nie jest jedynym nośnikiem
    informacji** (CLAUDE.md §21) — UI zawsze pokazuje nazwę tagu obok
    koloru. Trzymany jako tekst (`#rrggbb`), walidowany w schemacie
    Pydantic, nie w bazie: paleta należy do prezentacji.
    """

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_tags_user_name"),
        CheckConstraint("length(trim(name)) > 0", name="ck_tags_name_not_blank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(60))
    color: Mapped[str | None] = mapped_column(String(7), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssetTag(Base):
    """Powiązanie tag ↔ aktywo (M:N).

    Klucz główny złożony `(tag_id, asset_id)`: to samo powiązanie dwa razy
    nie znaczy nic, a klucz naturalny daje idempotentne „otaguj"
    (`ON CONFLICT DO NOTHING`) bez osobnego `UNIQUE`.

    Kaskada tylko od strony `tags` — usunięcie tagu ma zdjąć wszystkie jego
    powiązania, ale wygaszenie aktywa nie może usuwać tagów użytkownika
    (ta sama zasada co przy `Holding.asset_id` i `WatchlistItem.asset_id`).
    """

    __tablename__ = "asset_tags"

    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("ix_tags_user_id", Tag.user_id)
# „Jakie tagi ma to aktywo" — kierunek czytany przy liście pozycji, gdzie
# dla każdego aktywa trzeba pokazać jego etykiety.
Index("ix_asset_tags_asset_id", AssetTag.asset_id)
