"""Modele ORM modułu `ai_fund`: system agentowy AI Fund / Vibe-Trading.

**Kontekst i granice — ADR-104.** To rozszerzenie poza mapą Etapów 0–23
(`docs/adr/ADR-104-modul-ai-fund.md`), zaakceptowane jawnie przez użytkownika
2026-09-06. Numeracja etapów tego modułu jest własna (AI-1…AI-5), niezależna
od kroków 1–50. Ten plik realizuje wyłącznie Etap AI-1: modele danych i
migrację. **Silnik agentów, endpointy i joby workera są poza zakresem tego
pliku** — dodane w kolejnych etapach AI-2/AI-3.

**Czego te tabele świadomie NIE robią (CLAUDE.md #13, #3.12, `ai_fund_gemini_plan.md` §1):**

- LLM (Gemini) nigdy nie jest źródłem prawdy o cenie ani wyniku symulacji.
  `AIPrediction.target_price` to **prognoza modelu**, jawnie oznaczona jako
  taka i z terminem ważności (`expiration_date`) — nie wycena z `prices`.
  Wycena portfela nadal płynie wyłącznie przez istniejący przepływ
  `holdings → wycena → snapshot → analityka`.
- Żadna z tych tabel nie jest rejestrem transakcji. Nie ma tu FIFO,
  zrealizowanego P/L ani żadnej kolumny, którą dałoby się pomylić z
  rozliczeniem podatkowym (Etap 21 pozostaje odroczony, CLAUDE.md #3.12).
  Krok "Zatwierdź strategię (Paper Trading)" opisany w planie nie wykonuje
  żadnych zleceń — `AIFundSession.status` najwyżej dochodzi do `approved`.
- `AgentBacktest` (kolejny etap) ma być deterministycznym kodem Pythona na
  `prices.close_adj`, nie kodem generowanym przez LLM — tu przygotowujemy
  tylko miejsce (`AIAgentLog.parsed_data`) na ustrukturyzowany JSON, który
  ten kod będzie wykonywał.

**Własność danych i izolacja (CLAUDE.md #3.2, ADR-002/RLS).**
`AIFundSession` należy do portfela (a przez portfel — do użytkownika),
dokładnie jak `holdings`/`portfolio_valuations`: FK z `ondelete="CASCADE"`
do `portfolios.id`, kaskada dalej z `users` przez `Portfolio.user_id`
(CLAUDE.md #3.5 — cała ścieżka od `users` w dół). `AIAgentLog` i
`AIPrediction` należą do sesji, więc kaskadują z `ai_fund_sessions`.
Migracja włącza dla tych trzech tabel te same polityki RLS co dla
`holdings`/`portfolio_valuations` (`_OWNED_VIA_PARENT` w
`20260826_rls_policies.py`) — rola `portfel_app` bez `app.user_id` nie
zobaczy żadnego wiersza żadnego użytkownika.

`AssetVibeMetric`, `AssetAnalystRating` i `AILesson` są danymi **rynkowymi/
domenowymi, nie danymi użytkownika** — tak jak `dividend_events` czy `prices`
w `marketdata`: jeden wskaźnik hype'u albo jedna ocena analityków dla AAPL
dotyczy każdego użytkownika, który AAPL trzyma. FK do `assets.id`
(`ondelete="CASCADE"` — usunięcie aktywa kasuje jego metryki wtórne, inaczej
niż `Holding.asset_id`, które świadomie nie kaskaduje, bo pozycja użytkownika
nie ginie z aktywem), brak `user_id`, brak polityk RLS — izolacja i tak
zachodzi przy odczycie przez `get_owned_portfolio` (jak w `dividend_events`).

**Źródło i świeżość (CLAUDE.md #23).** `AssetAnalystRating` niesie `source`
i `fetched_at` z tego samego powodu co `DividendEvent`: pusty wynik dla GPW
musi dać się odróżnić od "nikt tego rynku nie pokrywa" (Finnhub nie pokrywa
GPW — `ai_fund_gemini_plan.md` ETAP 1 pkt 3).

**`agent_type` i `status` jako natywny Postgresowy ENUM, świadomie inaczej
niż `PushNotification.kind` (`String(40)`).** Tam zbiór wartości miał rosnąć
bez migracji typu (komentarz w `push/models.py`). Tu zbiór sześciu agentów
(`research/vibe/debate/backtest/risk/review`) wynika wprost z architektury
pipeline'u opisanej w planie — dodanie siódmego agenta to zmiana architektury,
nie parametr konfiguracyjny, więc `ENUM` w bazie jest tu ochroną przed literówką,
nie sztywnym gorsetem. Analogicznie `AIFundSession.status` to skończony automat
stanów (Etap AI-2 będzie egzekwował przejścia) — ENUM czyni nielegalne stany
niewyrażalnymi już na poziomie bazy.

**Wymiar wektora — 768.** `AILesson.embedding` to fundament pod RAG (Etap
AI-3), na razie zawsze `NULL`. 768 to wymiar `text-embedding-004` (Gemini) —
tego samego dostawcy LLM co reszta modułu (ADR-104: `google-genai`, nie
LiteLLM), więc nie trzeba w Etapie AI-3 przeliczać ani zmieniać wymiaru
kolumny. Rozszerzenie `pgvector` instaluje ta sama migracja
(`CREATE EXTENSION IF NOT EXISTS vector`) — jedyne miejsce w projekcie, które
go używa; downgrade może bezpiecznie je usunąć.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date as date_
from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

# Wymiar embeddingu Gemini `text-embedding-004` — patrz nagłówek modułu.
LESSON_EMBEDDING_DIM = 768


class AIFundSessionStatus(enum.StrEnum):
    """Skończony automat stanów jednego przebiegu 6-agentowego pipeline'u.

    `pending` → `running` → `awaiting_approval` → `approved`/`rejected`
    to główna ścieżka; `completed` oznacza sesję informacyjną bez kroku
    zatwierdzania (np. samo Review bez propozycji zmiany), `failed` — błąd
    pipeline'u (np. Gemini nie zwróciło poprawnego JSON-a). Egzekwowanie
    przejść należy do orkiestratora (Etap AI-2), nie do tego modelu.
    """

    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"


class AIAgentType(enum.StrEnum):
    """Sześciu agentów pipeline'u, w kolejności wykonania (plan ETAP 2)."""

    RESEARCH = "research"
    VIBE = "vibe"
    DEBATE = "debate"
    BACKTEST = "backtest"
    RISK = "risk"
    REVIEW = "review"


class AIFundSession(Base):
    """Jeden przebieg pipeline'u AI Fund dla jednego portfela.

    `config` (JSONB) niesie parametry uruchomienia — m.in. `memory_ttl_days`
    (Etap AI-3: ile dni wstecz sięgać po `AILesson` przy wstrzykiwaniu
    pamięci), limit straty i max ryzyko z formularza Control Room (plan
    ETAP 5). Trzymane jako JSONB, nie osobne kolumny, bo zestaw parametrów
    jest częścią logiki agentów (Etap AI-2), nie schematu — dodanie nowego
    pola konfiguracji nie powinno wymagać migracji.
    """

    __tablename__ = "ai_fund_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[AIFundSessionStatus] = mapped_column(
        Enum(
            AIFundSessionStatus,
            name="ai_fund_session_status",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        server_default=AIFundSessionStatus.PENDING.value,
    )
    config: Mapped[dict[str, object]] = mapped_column(JSONB(), server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AIAgentLog(Base):
    """Ślad jednego kroku pipeline'u — co dany agent zwrócił.

    `parsed_data` to WYŁĄCZNIE ustrukturyzowany JSON wymuszony przez
    `response_mime_type="application/json"` (plan §1 "Złote Reguły") —
    nigdy surowy tekst odpowiedzi modelu. Jeden wiersz na jedno wywołanie
    agenta w ramach sesji; kolejność w czasie (`created_at`) odtwarza
    przebieg pipeline'u co do kroku.
    """

    __tablename__ = "ai_agent_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_fund_sessions.id", ondelete="CASCADE"),
    )
    agent_type: Mapped[AIAgentType] = mapped_column(
        Enum(
            AIAgentType,
            name="ai_agent_type",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
    )
    parsed_data: Mapped[dict[str, object]] = mapped_column(JSONB())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssetVibeMetric(Base):
    """Dzienny wskaźnik "hype'u" wokół aktywa (Vibe Agent, plan ETAP 2 pkt 2).

    Dane rynkowe/agregowane, nie dane użytkownika — patrz nagłówek modułu.
    Klucz naturalny `(asset_id, date)`, wzorem `dividend_events`: jeden
    wskaźnik na aktywo na dzień, nadpisywany przy ponownym przeliczeniu
    (`ON CONFLICT DO UPDATE`), nie dopisywany.
    """

    __tablename__ = "asset_vibe_metrics"
    __table_args__ = (
        UniqueConstraint("asset_id", "date", name="uq_asset_vibe_metrics_asset_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
    )
    date: Mapped[date_] = mapped_column(Date())
    social_volume: Mapped[int] = mapped_column(Integer())
    # Skala hype'u 1-5 z planu (ETAP 2 pkt 2) — NUMERIC, nie Integer, bo Vibe
    # Agent może zwrócić wynik pośredni (np. 3.5) z uśrednienia kilku źródeł;
    # CLAUDE.md #3.1 każe NUMERIC(20,8) dla wszystkich wartości liczbowych
    # tego typu, niezależnie od spodziewanego zakresu.
    hype_score: Mapped[Decimal] = mapped_column(Numeric(20, 8))


class AssetAnalystRating(Base):
    """Zagregowane oceny analityków za dany okres (Finnhub, plan ETAP 4 pkt 2).

    Klucz naturalny `(asset_id, period)` — jeden wiersz na miesiąc/kwartał
    pokrycia danego aktywa, tak jak `dividend_events` ma jeden wiersz na
    ex-datę. `source`/`fetched_at` obowiązkowe (CLAUDE.md #23) — Finnhub
    świadomie NIE pokrywa GPW (`ai_fund_gemini_plan.md` ETAP 1 pkt 3), więc
    brak wiersza dla polskiej spółki musi dać się odróżnić od "sprawdziliśmy,
    nikt nie ocenia" wobec "jeszcze nie sprawdziliśmy".
    """

    __tablename__ = "asset_analyst_ratings"
    __table_args__ = (
        UniqueConstraint("asset_id", "period", name="uq_asset_analyst_ratings_asset_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
    )
    period: Mapped[date_] = mapped_column(Date())
    strong_buy: Mapped[int] = mapped_column(Integer())
    buy: Mapped[int] = mapped_column(Integer())
    hold: Mapped[int] = mapped_column(Integer())
    sell: Mapped[int] = mapped_column(Integer())
    strong_sell: Mapped[int] = mapped_column(Integer())
    source: Mapped[str] = mapped_column(String())
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIPrediction(Base):
    """Prognoza wygenerowana przez agenta Review z terminem ważności.

    **To jest prognoza modelu językowego, nie wycena** (CLAUDE.md #13) —
    `target_price`/`expected_drawdown` nigdy nie zasilają `prices` ani
    żadnej wyceny portfela. `expiration_date` jest wymagane: Etap AI-3
    (Agent Ewaluator) wyszukuje wygasłe prognozy, konfrontuje je z realnym
    `close_adj` z tego okresu i na tej podstawie generuje `AILesson`.
    """

    __tablename__ = "ai_predictions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_fund_sessions.id", ondelete="CASCADE"),
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
    )
    # Kierunek trendu jako zwykły `String`, nie `Enum` — świadomie inaczej
    # niż `agent_type`/`status`: to pole LLM (Gemini) wypełnia swobodnym
    # tekstem wymuszonym tylko schematem JSON po stronie promptu, nie
    # zbiorem zamkniętym z architektury pipeline'u. Sztywny ENUM bazy
    # odrzuciłby cały wiersz przy najmniejszej odmianie słownictwa modelu.
    predicted_trend: Mapped[str] = mapped_column(String(40))
    target_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    expected_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), default=None)
    expiration_date: Mapped[date_] = mapped_column(Date())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AILesson(Base):
    """Jednozdaniowa autokrytyka po nietrafionej prognozie (Etap AI-3).

    `asset_id` jest **nullable**: lekcja może dotyczyć konkretnego aktywa
    albo całej klasy (`asset_class`, np. "krypto") — dokładnie jedno z tych
    dwóch pól powinno być wypełnione, ale to reguła logiki agenta
    Ewaluatora (Etap AI-3), nie `CHECK` w bazie: dopuszczamy też lekcję
    ogólną (oba `NULL`), np. o niezawodności samego pipeline'u.

    `embedding` — patrz nagłówek modułu. Nullable i na razie zawsze puste;
    Etap AI-3 dopiero zacznie je wypełniać przy zapisie, Etap AI-3+ (RAG)
    zacznie z nich czytać przy wstrzykiwaniu pamięci.
    """

    __tablename__ = "ai_lessons"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        default=None,
    )
    asset_class: Mapped[str | None] = mapped_column(String(40), default=None)
    lesson_text: Mapped[str] = mapped_column(Text())
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(LESSON_EMBEDDING_DIM), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Poza klasami, tak jak `ix_prices_asset_id_date_desc` — wspierają
# konkretne zapytania z planu, nie ogólną "każda FK dostaje indeks".
Index("ix_ai_agent_logs_session_id", AIAgentLog.session_id)
Index("ix_ai_predictions_session_id", AIPrediction.session_id)
# Etap AI-3 (Agent Ewaluator): "znajdź wygasłe prognozy" chodzi codziennie
# po całej tabeli filtrując po dacie — bez indeksu to pełny skan rosnący
# z każdą sesją.
Index("ix_ai_predictions_expiration_date", AIPrediction.expiration_date)
# Etap AI-3 (wstrzykiwanie pamięci): `WHERE asset_id = ... AND created_at >=
# NOW() - INTERVAL '{memory_ttl_days} days'` — jak `ix_news_assets_asset_id_published_at`.
Index("ix_ai_lessons_asset_id_created_at", AILesson.asset_id, AILesson.created_at.desc())
# Ten sam zapytań wzorzec, ale dla lekcji przypiętych do klasy aktywów
# zamiast konkretnego tickera (np. "krypto" ogólnie).
Index("ix_ai_lessons_asset_class_created_at", AILesson.asset_class, AILesson.created_at.desc())
