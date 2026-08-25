"""watchlists_tags

Cztery tabele kroku 43 (etap 8): `watchlists` + `watchlist_items` oraz
`tags` + `asset_tags`. `docs/model-danych.md:28-29` rezerwował je jako
„Faza 2" bez kolumn — schemat powstaje razem z tą migracją.

Obie tabele łączące (`watchlist_items`, `asset_tags`) mają **złożony klucz
główny z pary naturalnej**, bez sztucznego `id` i bez osobnego `UNIQUE`:
to samo aktywo drugi raz na tej samej liście (albo to samo powiązanie
tag ↔ aktywo) nie niesie żadnej informacji, a klucz naturalny daje
idempotentne „dodaj" przez `ON CONFLICT DO NOTHING`.

FK do `assets` celowo **bez** `ON DELETE CASCADE` — tak samo jak
`holdings.asset_id`. Wygaszenie aktywa w słowniku nie może wymazywać list
ani tagów użytkownika; od wygaszania jest `assets.is_active`.

Kaskada z `users` w dół: `users → watchlists → watchlist_items` oraz
`users → tags → asset_tags` (CLAUDE.md #3.5).

Revision ID: f76793e14dad
Revises: 7a1c4e2b9f38
Create Date: 2026-08-25 12:03:49.510279

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f76793e14dad"
down_revision: str | Sequence[str] | None = "7a1c4e2b9f38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_tags_name_not_blank"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_tags_user_name"),
    )
    op.create_index("ix_tags_user_id", "tags", ["user_id"], unique=False)
    op.create_table(
        "watchlists",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_watchlists_name_not_blank"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_watchlists_user_name"),
    )
    op.create_index("ix_watchlists_user_id", "watchlists", ["user_id"], unique=False)
    op.create_table(
        "asset_tags",
        sa.Column("tag_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tag_id", "asset_id"),
    )
    op.create_index("ix_asset_tags_asset_id", "asset_tags", ["asset_id"], unique=False)
    op.create_table(
        "watchlist_items",
        sa.Column("watchlist_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
        ),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("watchlist_id", "asset_id"),
    )
    op.create_index("ix_watchlist_items_asset_id", "watchlist_items", ["asset_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_watchlist_items_asset_id", table_name="watchlist_items")
    op.drop_table("watchlist_items")
    op.drop_index("ix_asset_tags_asset_id", table_name="asset_tags")
    op.drop_table("asset_tags")
    op.drop_index("ix_watchlists_user_id", table_name="watchlists")
    op.drop_table("watchlists")
    op.drop_index("ix_tags_user_id", table_name="tags")
    op.drop_table("tags")
