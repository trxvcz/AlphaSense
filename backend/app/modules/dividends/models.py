"""Model ORM modułu `dividends`: `dividend_events` (plan krok 47, etap 9).

`docs/model-danych.md:32` rezerwował tę tabelę jako „Faza 3" bez kolumn —
schemat powstaje tutaj, razem z migracją.

Zdarzenia dywidendowe, tak jak `news` i `prices`, **nie są własnością
użytkownika**: jedna dywidenda AAPL dotyczy każdego, kto AAPL trzyma.
Przechowujemy ją raz, wiążemy z aktywem, a izolacja dzieje się przy
odczycie — endpoint zawęża do aktywów portfela przekazanego przez
`get_owned_portfolio` (CLAUDE.md #3.2). Stąd brak FK do `users`.

**To NIE jest wpis księgowy.** Tabela mówi „spółka zapowiedziała wypłatę
X na akcję z ex-datą D", a nie „użytkownik otrzymał X PLN". Zrealizowane
przepływy, podatek u źródła i PIT-38 należą do Etapu 21 i wymagają osobnej
decyzji o zmianie zakresu (CLAUDE.md §22) — dlatego nie ma tu ani
`user_id`, ani kwoty w PLN, ani niczego, co dałoby się pomylić
z rozliczeniem.

**Klucz naturalny: `(asset_id, ex_date)`.** Spółka ma jedną ex-datę na
zapowiedzianą wypłatę; dwa wiersze o tej samej parze to ten sam fakt
pobrany dwa razy. Stąd `UNIQUE` i zapis przez `ON CONFLICT DO UPDATE`
— **odwrotnie niż przy newsach**, gdzie wygrywa pierwsza wersja. Treść
opublikowanej depeszy się nie zmienia, a zapowiedziana dywidenda owszem:
między deklaracją a wypłatą bywa korygowana kwota i data płatności, więc
świeższa odpowiedź dostawcy jest bliższa prawdzie niż nasza kopia sprzed
tygodnia. Ta sama logika co przy cenach (`marketdata/repository.upsert_prices`).

**`amount` jest w walucie notowania aktywa i tak zostaje.** Przeliczenia
na PLN tutaj nie ma świadomie: kurs NBP właściwy dla wypłaty to kurs
z dnia poprzedzającego wypłatę (data w przyszłości), więc każda liczba
w PLN pokazana dziś byłaby prognozą udającą wycenę (CLAUDE.md #3.15).
Kalendarz pokazuje kwotę w walucie zdarzenia i mówi wprost, że jest brutto.
"""

from __future__ import annotations

import uuid
from datetime import date as date_
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DividendEvent(Base):
    """Pojedyncze zdarzenie dywidendowe zapowiedziane przez spółkę.

    Cztery daty, bo znaczą cztery różne rzeczy i dostawcy podają je
    niezależnie (bywa, że tylko część):

    - `ex_date` — **jedyna wymagana**. Od tego dnia kupujący nie ma już
      prawa do wypłaty; to ona decyduje, czy pozycja „załapie się", i to
      o niej jest ten kalendarz (i push z kroku 50).
    - `record_date` — dzień ustalenia praw, zwykle tuż po `ex_date`.
    - `pay_date` — dzień wypłaty, potrafi być odległy o tygodnie.
    - `declaration_date` — kiedy spółka ogłosiła; przydatna, żeby odróżnić
      zapowiedź świeżą od pobranej dawno i niepotwierdzonej.

    `source` i `fetched_at` są obowiązkowe (CLAUDE.md #23 — dla każdego
    źródła zachowujemy dostawcę i czas pobrania). Bez nich nie da się
    powiedzieć, czy pusty kalendarz oznacza „nie ma dywidend", czy
    „nikt tego rynku nie pokrywa".
    """

    __tablename__ = "dividend_events"
    __table_args__ = (UniqueConstraint("asset_id", "ex_date", name="uq_dividend_events_asset_ex"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
    )
    ex_date: Mapped[date_] = mapped_column(Date())
    record_date: Mapped[date_ | None] = mapped_column(Date(), default=None)
    pay_date: Mapped[date_ | None] = mapped_column(Date(), default=None)
    declaration_date: Mapped[date_ | None] = mapped_column(Date(), default=None)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String())
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# Poza klasą, tak jak `ix_prices_asset_id_date_desc` — `mapped_column` nie
# przyjmuje kierunku sortowania. Kalendarz czyta „najbliższe ex-daty dla
# zbioru aktywów", czyli rosnąco od dziś w przód; kierunek rosnący jest tu
# świadomy i różni się od feedu newsów (tam liczy się to, co najnowsze,
# tu — to, co najbliższe).
Index("ix_dividend_events_asset_id_ex_date", DividendEvent.asset_id, DividendEvent.ex_date)
