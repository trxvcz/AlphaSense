"""markets i assets

Słownik rynków (ADR-102, etap 3, plan krok 17-18) i aktywa. Cykl FK
`markets ⇄ assets` (`markets.index_asset_id → assets.id`,
`assets.market_code → markets.code`) rozwiązany trzyetapowo (skill
`alembic-migracja`, sekcja „Kolejność tworzenia tabel”): tu tworzymy
`markets` **bez** `index_asset_id` i `assets` z FK do `markets.code`;
kolumnę `index_asset_id` dopisuje kolejna migracja
(`20260724_markets_index_asset_id`) addytywnie, po tym jak `assets` już
istnieje.

Bez `ON DELETE CASCADE` od `users` — dane rynkowe nie są własnością
użytkownika (CLAUDE.md #3.5 dotyczy tylko `users → portfolios →
holdings/portfolio_valuations`).

Revision ID: f15f1ce29ca0
Revises: f4ae90c764c6
Create Date: 2026-07-24 13:00:06.822663

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f15f1ce29ca0"
down_revision: str | None = "f4ae90c764c6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Utwórz `markets` (bez `index_asset_id`) i `assets`."""
    op.create_table(
        "markets",
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("eod_time", sa.Time(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )

    op.create_table(
        "assets",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("asset_class", sa.String(), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("isin", sa.String(), nullable=True),
        sa.Column("sector", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("region", sa.String(), nullable=True),
        sa.Column("metadata_source", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(["market_code"], ["markets.code"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assets_market_code", "assets", ["market_code"])
    op.create_index("ix_assets_symbol", "assets", ["symbol"])


def downgrade() -> None:
    """Usuń `assets` (ma FK do `markets`), potem `markets`."""
    op.drop_index("ix_assets_symbol", table_name="assets")
    op.drop_index("ix_assets_market_code", table_name="assets")
    op.drop_table("assets")

    op.drop_table("markets")
