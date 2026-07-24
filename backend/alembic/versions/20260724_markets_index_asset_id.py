"""markets index_asset_id

Ostatni odcinek cyklu FK `markets ⇄ assets` (patrz
`20260724_markets_i_assets`): teraz, gdy `assets` istnieje, dopisujemy
`markets.index_asset_id` (FK → `assets.id`) — aktywo reprezentujące indeks
referencyjny rynku (np. WIG dla GPW, ADR-102). Migracja addytywna:
kolumna `NULL`, żadny istniejący wiersz `markets` nie jest naruszony.

Revision ID: e3b43d7f496b
Revises: f15f1ce29ca0
Create Date: 2026-07-24 13:00:07.634952

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3b43d7f496b"
down_revision: str | None = "f15f1ce29ca0"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Dopisz `markets.index_asset_id` (FK → `assets.id`, nullable)."""
    op.add_column("markets", sa.Column("index_asset_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_markets_index_asset_id_assets",
        "markets",
        "assets",
        ["index_asset_id"],
        ["id"],
    )


def downgrade() -> None:
    """Usuń FK i kolumnę `index_asset_id`."""
    op.drop_constraint("fk_markets_index_asset_id_assets", "markets", type_="foreignkey")
    op.drop_column("markets", "index_asset_id")
