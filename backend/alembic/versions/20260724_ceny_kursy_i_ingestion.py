"""prices, asset_source_map, fx_rates, ingestion_runs, portfolio_valuations

Reszta tabel etapu 3 (plan krok 17-18), wszystkie z FK do tabel utworzonych
wcześniej w tej serii: `prices`/`asset_source_map` → `assets`
(`20260724_markets_i_assets`), `ingestion_runs` → `markets` (tamże),
`portfolio_valuations` → `portfolios` (`20260724_portfolios_i_holdings`,
`ON DELETE CASCADE` — kolejny odcinek ścieżki kaskadowej od `users`).
`fx_rates` bez FK (kod waluty ISO, nie odniesienie do innej tabeli).

Wycena i wykresy zawsze na `prices.close_adj` (CLAUDE.md #4) — stąd
`CHECK close_adj > 0`, nigdy `float`. Indeksy `(asset_id, date DESC)` i
`(market_code, started_at DESC)`/`(portfolio_id, date DESC)` tworzone
ręczną `CREATE INDEX` (kolejność kolumn z modyfikatorem `DESC`) —
autogenerate tego nie generuje poprawnie z listy nazw kolumn, `op.execute`
jest tu jednoznaczne.

Revision ID: fc63665c2e00
Revises: 47b1a13e36b6
Create Date: 2026-07-24 13:00:09.270545

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fc63665c2e00"
down_revision: str | None = "47b1a13e36b6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Utwórz `prices`, `asset_source_map`, `fx_rates`, `ingestion_runs`,
    `portfolio_valuations`."""
    op.create_table(
        "prices",
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(20, 8), nullable=True),
        sa.Column("high", sa.Numeric(20, 8), nullable=True),
        sa.Column("low", sa.Numeric(20, 8), nullable=True),
        sa.Column("close", sa.Numeric(20, 8), nullable=True),
        sa.Column("close_adj", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("asset_id", "date"),
        sa.CheckConstraint("close_adj > 0", name="close_adj_positive"),
    )
    op.execute("CREATE INDEX ix_prices_asset_id_date_desc ON prices (asset_id, date DESC)")

    op.create_table(
        "asset_source_map",
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_symbol", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("asset_id", "provider"),
    )

    op.create_table(
        "fx_rates",
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("rate_pln", sa.Numeric(20, 8), nullable=False),
        sa.PrimaryKeyConstraint("currency", "date"),
    )

    op.create_table(
        "ingestion_runs",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("assets_total", sa.Integer(), nullable=False),
        sa.Column("assets_ok", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["market_code"], ["markets.code"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE INDEX ix_ingestion_runs_market_code_started_at_desc "
        "ON ingestion_runs (market_code, started_at DESC)"
    )

    op.create_table(
        "portfolio_valuations",
        sa.Column("portfolio_id", sa.UUID(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value_pln", sa.Numeric(20, 8), nullable=False),
        sa.Column(
            "composition_change",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("portfolio_id", "date"),
    )
    op.execute(
        "CREATE INDEX ix_portfolio_valuations_portfolio_id_date_desc "
        "ON portfolio_valuations (portfolio_id, date DESC)"
    )


def downgrade() -> None:
    """Usuń tabele w odwrotnej kolejności (FK)."""
    op.execute("DROP INDEX ix_portfolio_valuations_portfolio_id_date_desc")
    op.drop_table("portfolio_valuations")

    op.execute("DROP INDEX ix_ingestion_runs_market_code_started_at_desc")
    op.drop_table("ingestion_runs")

    op.drop_table("fx_rates")

    op.drop_table("asset_source_map")

    op.execute("DROP INDEX ix_prices_asset_id_date_desc")
    op.drop_table("prices")
