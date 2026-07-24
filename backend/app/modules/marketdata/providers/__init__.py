"""Warstwa integracji z darmowymi źródłami danych rynkowych (plan krok 20-22,
etap 4).

Ten pakiet trzyma **fundament** (`base.py` — kontrakt `DataProvider` i DTO,
`rate_limiter.py`, `circuit_breaker.py`, `guarded.py`, `fallback_chain.py`)
oraz konkretnych dostawców (krok 21: NBP; krok 22: Stooq, yfinance, Finnhub,
Binance — zastępuje CoinGecko, patrz `binance.py`) jako osobne moduły w tym
samym pakiecie. `http_client.py` to wspólny helper (retry na HTTP 429,
parsowanie `Decimal`) dla dostawców opartych o surowe REST/CSV.

Świadomie brak re-eksportów na poziomie pakietu: dostawcy konkretni będą
importowani jawnie z ich modułów (`from app.modules.marketdata.providers.nbp
import NbpProvider`), żeby import samego pakietu (np. przy budowaniu
`FallbackChain` w `service.py`) nie ciągnął za sobą wszystkich zależności
(httpx klientów, kluczy API) na raz.
"""

from __future__ import annotations
