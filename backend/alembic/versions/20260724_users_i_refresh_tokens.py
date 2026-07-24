"""users i refresh_tokens

Tabele korzeniowe auth (etap 2, plan krok 11): `users` — konto użytkownika,
oraz `refresh_tokens` — rotowane tokeny odświeżające z self-referencing
`replaced_by` (wykrywanie ponownego użycia unieważnionego tokena w łańcuchu
rotacji). `refresh_tokens.user_id` kaskaduje `ON DELETE CASCADE` z `users`
(CLAUDE.md #3.5) — to pierwszy odcinek ścieżki kasakadowej od użytkownika
w dół.

Autogenerate poprawnie wykrył `TIMESTAMPTZ` (dzięki jawnemu
`DateTime(timezone=True)` w modelu) i `ondelete` na obu FK — bez ręcznych
poprawek schematu. Bez migracji danych.

Revision ID: d1c1ef826b78
Revises: 0001
Create Date: 2026-07-24

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1c1ef826b78"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Utwórz `users` i `refresh_tokens`."""
    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["replaced_by"], ["refresh_tokens.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_refresh_tokens_token_hash"), "refresh_tokens", ["token_hash"], unique=False
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)


def downgrade() -> None:
    """Usuń `refresh_tokens` (ma FK do `users`), potem `users`."""
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_token_hash"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
