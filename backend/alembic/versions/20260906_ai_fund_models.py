"""ai_fund_models

Modele Etapu AI-1 modułu `ai_fund` (ADR-104, `ai_fund_gemini_plan.md`).
Sześć tabel: dwie "właścicielskie" pary rodzic/dziecko (sesja pipeline'u i
jej logi/prognozy — kaskadują z `portfolios`, jak `holdings`) oraz trzy
tabele domenowe bez `user_id` (wskaźniki hype'u, oceny analityków, lekcje) —
wzorem `dividend_events`, kaskadują z `assets`.

**`CREATE EXTENSION vector` przed `ai_lessons`, kolejność ma znaczenie** —
`Vector(768)` w kolumnie `embedding` wymaga typu z rozszerzenia `pgvector`
zarejestrowanego w Postgresie, inaczej `CREATE TABLE` padnie na nieznanym
typie. Downgrade odwraca kolejność: najpierw `DROP TABLE ai_lessons`,
dopiero potem `DROP EXTENSION` — bezpieczne, bo to jedyne miejsce w
projekcie używające `vector` (sprawdzone przy planowaniu tej migracji).

**RLS (ADR-002, `20260826_rls_policies.py`) — od razu, nie "kiedyś".**
`ai_fund_sessions` jest własnością portfela (rodzica), `ai_agent_logs` i
`ai_predictions` — własnością sesji (rodzica ich rodzica); ten sam wzorzec
`_OWNED_VIA_PARENT` co `holdings`/`portfolio_valuations`, z podzapytaniem,
które samo podlega polityce swojego rodzica. `asset_vibe_metrics`,
`asset_analyst_ratings` i `ai_lessons` polityk NIE dostają — to dane bez
właściciela-użytkownika, jak `dividend_events`/`prices` (wyłączenie opisane
w docstringu `20260826_rls_policies.py`).

Revision ID: 536d54e5daf3
Revises: 8d1f2a6c40b7
Create Date: 2026-09-06 19:40:33.627844

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "536d54e5daf3"
down_revision: str | Sequence[str] | None = "8d1f2a6c40b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UID = "NULLIF(current_setting('app.user_id', true), '')::uuid"

# (tabela, kolumna FK, tabela-rodzic) — patrz `_OWNED_VIA_PARENT`
# w `20260826_rls_policies.py`. `ai_agent_logs`/`ai_predictions` wskazują na
# `ai_fund_sessions`, nie na `portfolios` bezpośrednio — podzapytanie działa,
# bo `ai_fund_sessions` samo jest ograniczone własną polityką.
_OWNED_VIA_PARENT = (
    ("ai_fund_sessions", "portfolio_id", "portfolios"),
    ("ai_agent_logs", "session_id", "ai_fund_sessions"),
    ("ai_predictions", "session_id", "ai_fund_sessions"),
)


def upgrade() -> None:
    # Rozszerzenie musi istnieć PRZED `create_table("ai_lessons", ...)`,
    # bo kolumna `embedding` używa typu `vector` z tego rozszerzenia.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "ai_fund_sessions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("portfolio_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "awaiting_approval",
                "approved",
                "rejected",
                "completed",
                "failed",
                name="ai_fund_session_status",
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_fund_sessions_portfolio_id", "ai_fund_sessions", ["portfolio_id"], unique=False
    )

    op.create_table(
        "ai_agent_logs",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column(
            "agent_type",
            sa.Enum(
                "research",
                "vibe",
                "debate",
                "backtest",
                "risk",
                "review",
                name="ai_agent_type",
            ),
            nullable=False,
        ),
        sa.Column("parsed_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["ai_fund_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_agent_logs_session_id", "ai_agent_logs", ["session_id"], unique=False)

    op.create_table(
        "ai_predictions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("predicted_trend", sa.String(length=40), nullable=False),
        sa.Column("target_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("expected_drawdown", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["ai_fund_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_predictions_expiration_date", "ai_predictions", ["expiration_date"], unique=False
    )
    op.create_index("ix_ai_predictions_session_id", "ai_predictions", ["session_id"], unique=False)

    op.create_table(
        "asset_vibe_metrics",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("social_volume", sa.Integer(), nullable=False),
        sa.Column("hype_score", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "date", name="uq_asset_vibe_metrics_asset_date"),
    )

    op.create_table(
        "asset_analyst_ratings",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("strong_buy", sa.Integer(), nullable=False),
        sa.Column("buy", sa.Integer(), nullable=False),
        sa.Column("hold", sa.Integer(), nullable=False),
        sa.Column("sell", sa.Integer(), nullable=False),
        sa.Column("strong_sell", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "period", name="uq_asset_analyst_ratings_asset_period"),
    )

    op.create_table(
        "ai_lessons",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.UUID(), nullable=True),
        sa.Column("asset_class", sa.String(length=40), nullable=True),
        sa.Column("lesson_text", sa.Text(), nullable=False),
        # Wymiar 768 = `text-embedding-004` (Gemini) — patrz nagłówek
        # `app/modules/ai_fund/models.py`. Kolumna zostaje `NULL` w Etapie AI-1.
        sa.Column("embedding", pgvector.sqlalchemy.Vector(768), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_lessons_asset_id_created_at",
        "ai_lessons",
        ["asset_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_ai_lessons_asset_class_created_at",
        "ai_lessons",
        ["asset_class", sa.literal_column("created_at DESC")],
        unique=False,
    )

    for table, column, parent in _OWNED_VIA_PARENT:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_owner ON {table} "
            f"USING ({column} IN (SELECT id FROM {parent})) "
            f"WITH CHECK ({column} IN (SELECT id FROM {parent}))"
        )


def downgrade() -> None:
    for table, _column, _parent in _OWNED_VIA_PARENT:
        op.execute(f"DROP POLICY IF EXISTS {table}_owner ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_ai_lessons_asset_class_created_at", table_name="ai_lessons")
    op.drop_index("ix_ai_lessons_asset_id_created_at", table_name="ai_lessons")
    op.drop_table("ai_lessons")

    op.drop_table("asset_analyst_ratings")
    op.drop_table("asset_vibe_metrics")

    op.drop_index("ix_ai_predictions_session_id", table_name="ai_predictions")
    op.drop_index("ix_ai_predictions_expiration_date", table_name="ai_predictions")
    op.drop_table("ai_predictions")

    op.drop_index("ix_ai_agent_logs_session_id", table_name="ai_agent_logs")
    op.drop_table("ai_agent_logs")

    op.drop_index("ix_ai_fund_sessions_portfolio_id", table_name="ai_fund_sessions")
    op.drop_table("ai_fund_sessions")

    sa.Enum(name="ai_agent_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="ai_fund_session_status").drop(op.get_bind(), checkfirst=True)

    # Bezpieczne wyłącznie dlatego, że to jedyne miejsce w projekcie
    # używające `pgvector` (sprawdzone przy planowaniu tej migracji) — gdyby
    # w przyszłości pojawiła się druga tabela z kolumną `Vector`, ten
    # `DROP EXTENSION` trzeba będzie usunąć stąd.
    op.execute("DROP EXTENSION IF EXISTS vector")
