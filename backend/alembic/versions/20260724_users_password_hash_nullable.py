"""users.password_hash nullable (konta OAuth-only)

Plan krok 13 (etap 2): logowanie Google. Konto utworzone przez
`/auth/google/callback` nie ma hasła — upsert po `email` (bez kolumny
`google_id`/`oauth_provider`, świadomie, patrz `app/modules/auth/models.py`
i raport kroku). Zmiana addytywna, nie-łamiąca: `NOT NULL` → `NULL`, sama
kolumna i tabela bez zmian. Bez migracji danych — istniejące konta hasłowe
mają `password_hash` ustawiony i nic się dla nich nie zmienia.

Revision ID: f4ae90c764c6
Revises: d1c1ef826b78
Create Date: 2026-07-24

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4ae90c764c6"
down_revision: str | None = "d1c1ef826b78"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """`users.password_hash`: `NOT NULL` → `NULL` (konta OAuth-only)."""
    op.alter_column("users", "password_hash", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    """Odtwarza `NOT NULL`.

    Rzuci błędem integralności, jeśli w międzyczasie powstało konto
    OAuth-only bez hasła — to zamierzone: downgrade nie zgaduje hasła za
    użytkownika, wymaga ręcznej decyzji operatora.
    """
    op.alter_column("users", "password_hash", existing_type=sa.String(), nullable=False)
