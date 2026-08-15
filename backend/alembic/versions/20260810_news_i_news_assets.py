"""news i news_assets

Tabele newsów (etap 9, plan krok 46). `docs/model-danych.md` rezerwował je
jako „Faza 3" bez kolumn — schemat powstaje razem z tą migracją.

Newsy nie należą do użytkownika, więc żaden FK nie prowadzi do `users`
i nie ma tu kaskady z CLAUDE.md #3.5. Izolacja danych dzieje się przy
odczycie: endpoint filtruje po aktywach z portfela zweryfikowanego przez
`get_owned_portfolio`.

Dwa ograniczenia unikalności zamiast jednego: `url` łapie powtórne pobranie
tego samego wpisu przy kolejnym przebiegu joba, a `content_hash` — tę samą
depeszę PAP rozesłaną przez Bankiera, Money i StockWatch pod trzema różnymi
adresami. Bez drugiego feed byłby potrojony.

Oba indeksy są **malejące** po `published_at` — feed czyta wyłącznie
najnowsze wpisy i nigdy nie skanuje od najstarszego.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6812ced23486"
down_revision: str | Sequence[str] | None = "926b382d1715"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "news",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("sentiment", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("sentiment_source", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash", name="uq_news_content_hash"),
        sa.UniqueConstraint("url", name="uq_news_url"),
    )
    op.create_index(
        "ix_news_published_at_desc",
        "news",
        [sa.literal_column("published_at DESC")],
        unique=False,
    )
    op.create_table(
        "news_assets",
        sa.Column("news_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["news_id"], ["news.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("news_id", "asset_id"),
    )
    op.create_index(
        "ix_news_assets_asset_id_published_at_desc",
        "news_assets",
        ["asset_id", sa.literal_column("published_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_news_assets_asset_id_published_at_desc", table_name="news_assets")
    op.drop_table("news_assets")
    op.drop_index("ix_news_published_at_desc", table_name="news")
    op.drop_table("news")
