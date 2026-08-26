"""rls_policies

Domknięcie ADR-002, warstwa 3: Row Level Security w Postgresie (plan krok 44).

**RLS to obrona w głąb, nie zamiennik `get_owned_*`.** Warstwa aplikacyjna
zostaje bez zmian — ta migracja dokłada siatkę bezpieczeństwa pod nią, na
wypadek zapytania, które kiedyś ominie zależność autoryzacyjną.

**Rola aplikacji nie może być właścicielem tabel ani superużytkownikiem.**
Superużytkownik i właściciel tabeli omijają polityki milcząco (bez
`FORCE ROW LEVEL SECURITY`), więc RLS włączone przy połączeniu jako
`portfel` nie zrobiłoby nic — i to jest najgroźniejszy scenariusz tego
kroku: zielone testy przy wyłączonej ochronie. Stąd osobna rola
`portfel_app` (`NOSUPERUSER`, `NOBYPASSRLS`), którą tworzymy tutaj bez
hasła i bez `LOGIN`; hasło i prawo logowania nadaje `python -m app.cli
db-roles` z zmiennych środowiskowych, żeby sekret nie trafił do repo
(CLAUDE.md #3.9).

**Worker i migracje zostają na roli właściciela.** Job wyceny liczy
snapshoty wszystkich użytkowników i nie ma czyjegoś `app.user_id` —
`BYPASSRLS` jest tu funkcją, nie obejściem (ADR-002).

**Sesja bez `app.user_id` widzi zero wierszy.** `NULLIF(..., '')::uuid`
daje `NULL`, a porównanie z `NULL` nie przepuszcza żadnego wiersza —
zamiast błędu rzutowania pustego stringa albo, gorzej, przepuszczenia
wszystkiego. To jest test akceptacyjny tego kroku.

**`users` i `refresh_tokens` świadomie BEZ polityk.** Rejestracja, logowanie
i rotacja tokenu odbywają się, **zanim** istnieje `app.user_id` — polityka
na tych tabelach zablokowałaby własne uwierzytelnianie. Ochrona tych tabel
zostaje na warstwie aplikacyjnej. Słowniki globalne (`assets`, `prices`,
`markets`, `fx_rates`, `news`, `dividend_events`, `nbp_reference_rates`,
`ingestion_runs`) polityk nie dostają, bo nie mają właściciela-użytkownika.

Revision ID: 8d1f2a6c40b7
Revises: f76793e14dad
Create Date: 2026-08-26 12:40:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "8d1f2a6c40b7"
down_revision: str | None = "f76793e14dad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "portfel_app"

# `app.user_id` bieżącej sesji jako UUID albo NULL. `true` w
# `current_setting` = „nie wywalaj się, gdy zmiennej nie ustawiono".
_UID = "NULLIF(current_setting('app.user_id', true), '')::uuid"

# Tabele z bezpośrednią kolumną `user_id`.
_OWNED_DIRECTLY = ("portfolios", "tags", "watchlists")

# Tabele bez `user_id`, których właściciel wynika z rodzica. Podzapytanie
# samo podlega polityce rodzica, więc warunek jest spójny nawet gdyby
# polityka rodzica się zmieniła.
_OWNED_VIA_PARENT = (
    ("holdings", "portfolio_id", "portfolios"),
    ("portfolio_valuations", "portfolio_id", "portfolios"),
    ("asset_tags", "tag_id", "tags"),
    ("watchlist_items", "watchlist_id", "watchlists"),
)


def upgrade() -> None:
    # Rola bez `LOGIN` i bez hasła — sekret nadaje `app.cli db-roles`.
    # `DO $$` zamiast `CREATE ROLE IF NOT EXISTS`, bo Postgres takiej
    # składni nie ma dla ról.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    # Tabele powstałe PÓŹNIEJ (kolejne migracje) mają dostać te same prawa
    # automatycznie — inaczej pierwszy endpoint na nowej tabeli wywaliłby się
    # na `permission denied` dopiero na produkcji.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )

    for table in _OWNED_DIRECTLY:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_owner ON {table} "
            f"USING (user_id = {_UID}) WITH CHECK (user_id = {_UID})"
        )

    for table, column, parent in _OWNED_VIA_PARENT:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_owner ON {table} "
            f"USING ({column} IN (SELECT id FROM {parent})) "
            f"WITH CHECK ({column} IN (SELECT id FROM {parent}))"
        )


def downgrade() -> None:
    """Wycofanie zostawia rolę i nadania — usuwa wyłącznie polityki.

    `DROP ROLE` wymagałby wcześniejszego odebrania wszystkich nadań i padłby,
    gdyby rola miała jeszcze otwarte sesje; a rola bez polityk niczego nie
    psuje. Migracja wstecz ma **odblokować aplikację**, a nie posprzątać
    cluster — to jest jej jedyne zadanie na produkcji (plan etapu 8, ryzyko
    kroku 44).
    """
    for table, _column, _parent in _OWNED_VIA_PARENT:
        op.execute(f"DROP POLICY IF EXISTS {table}_owner ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    for table in _OWNED_DIRECTLY:
        op.execute(f"DROP POLICY IF EXISTS {table}_owner ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
