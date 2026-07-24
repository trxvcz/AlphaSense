"""portfolios i holdings

Portfele i pozycje (etap 3, plan krok 17-18). `portfolios.user_id`
kaskaduje `ON DELETE CASCADE` z `users` (CLAUDE.md #3.5) — kolejny odcinek
ścieżki kaskadowej po `refresh_tokens`; `holdings.portfolio_id` kaskaduje
dalej z `portfolios`. `holdings.asset_id` wskazuje na `assets` (już
istnieje po `20260724_markets_i_assets`) — bez `ON DELETE CASCADE`
(usunięcie aktywa nie jest w zakresie tego etapu).

`NUMERIC(20,8)` jawnie dla `quantity`/`avg_cost` (CLAUDE.md #3.1) —
autogenerate bywa zgubny na precyzji, tu wpisane ręcznie i zweryfikowane.

Revision ID: 47b1a13e36b6
Revises: e3b43d7f496b
Create Date: 2026-07-24 13:00:08.443773

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "47b1a13e36b6"
down_revision: str | None = "e3b43d7f496b"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Utwórz `portfolios` i `holdings`."""
    op.create_table(
        "portfolios",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("holdings_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portfolios_user_id", "portfolios", ["user_id"])

    op.create_table(
        "holdings",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("portfolio_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("avg_cost", sa.Numeric(20, 8), nullable=True),
        sa.Column("cost_currency", sa.String(length=3), nullable=True),
        sa.Column(
            "valid_from",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=True,
        ),
        sa.Column("note", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("portfolio_id", "asset_id", name="uq_holdings_portfolio_asset"),
        sa.CheckConstraint("quantity >= 0", name="quantity_nonneg"),
        sa.CheckConstraint(
            "avg_cost IS NULL OR cost_currency IS NOT NULL",
            name="avg_cost_needs_currency",
        ),
    )
    op.create_index("ix_holdings_portfolio_id", "holdings", ["portfolio_id"])


def downgrade() -> None:
    """Usuń `holdings` (ma FK do `portfolios`/`assets`), potem `portfolios`."""
    op.drop_index("ix_holdings_portfolio_id", table_name="holdings")
    op.drop_table("holdings")

    op.drop_index("ix_portfolios_user_id", table_name="portfolios")
    op.drop_table("portfolios")
