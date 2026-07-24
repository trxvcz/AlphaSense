"""Modele ORM modułu `auth`: `users`, `refresh_tokens`.

Plan krok 11 (etap 2). `User` jest korzeniem ścieżki `ON DELETE CASCADE`
(CLAUDE.md #3.5, docs/model-danych.md) — wszystko poniżej w hierarchii
(`refresh_tokens`, a w etapie 3 `portfolios` i dalej) kaskaduje z `users`.

Rejestracja/logowanie/JWT (`schemas.py`, `service.py`) — kolejny krok planu,
poza zakresem tego pliku.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class User(Base):
    """Konto użytkownika. Korzeń ścieżki `ON DELETE CASCADE`.

    `password_hash` jest `NULL` dla kont OAuth-only (Google, plan krok 13) —
    takie konto nigdy nie przechodzi przez `/auth/login`, tylko przez
    `/auth/google/*`. Tożsamość między kontem hasłowym i kontem Google jest
    dopasowywana po `email` (bez osobnej kolumny `google_id`/`oauth_provider`
    — świadomie, żeby nie rozszerzać schematu bez wyraźnej potrzeby; patrz
    raport kroku 13).
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshToken(Base):
    """Refresh token JWT — rotowany, z wykrywaniem ponownego użycia.

    `replaced_by` wskazuje na token, który go zastąpił w rotacji (self-FK);
    pozwala wykryć próbę ponownego użycia unieważnionego tokena (reużycie
    tokena, który już ma następcę, jest sygnałem kompromitacji).
    """

    __tablename__ = "refresh_tokens"

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
    token_hash: Mapped[str] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        default=None,
    )
