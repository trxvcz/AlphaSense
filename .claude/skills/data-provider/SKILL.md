---
name: data-provider
description: Wzorzec integracji z darmowymi źródłami danych rynkowych w AlphaSense — NBP, Stooq, yfinance, Finnhub, CoinGecko — wraz z RateLimiter, CircuitBreaker, FallbackChain i mapowaniem symboli. Użyj gdy dodajesz nowego dostawcę danych, pobierasz ceny lub kursy walut, obsługujesz błędy 429 i awarie źródeł, albo gdy notowania nie zgadzają się z rzeczywistością.
---

# Warstwa danych rynkowych

## Kontrakt dostawcy

```python
class DataProvider(Protocol):
    name: str
    supports: set[Capability]      # OHLCV, FX, METADATA, SEARCH
    async def get_ohlcv(self, symbol: str, start: date, end: date) -> list[PriceBar]: ...
    async def get_fx(self, currency: str, start: date, end: date) -> list[FxRate]: ...
    async def get_metadata(self, symbol: str) -> AssetMetadata | None: ...
```

Dostawca nie zna bazy danych, nie zna aktywów, zna tylko symbol swojego API. Tłumaczeniem zajmuje się warstwa ingestii z użyciem `asset_source_map`.

## Kompozycja

```
FallbackChain([
    Guarded(StooqProvider(),   limiter=RateLimiter(60/min), breaker=CircuitBreaker(5, 10*60)),
    Guarded(YFinanceProvider(), limiter=RateLimiter(30/min), breaker=CircuitBreaker(5, 10*60)),
    Guarded(FinnhubProvider(),  limiter=RateLimiter(60/min), breaker=CircuitBreaker(5, 10*60)),
])
```

- **RateLimiter** — token bucket, limit z konfiguracji per dostawca. 429 → backoff wykładniczy z jitterem, maksymalnie N prób.
- **CircuitBreaker** — po `failure_threshold` błędach pod rząd otwiera się na `reset_timeout`; potem jedno zapytanie próbne. Stan w Redisie (przeżywa restart workera).
- **FallbackChain** — kolejność z `asset_source_map.priority`; pierwszy sukces wygrywa; w `ingestion_runs` zapisz, który dostawca odpowiedział.

## Specyfika źródeł

| Źródło | Zakres | Uwagi |
|---|---|---|
| NBP | kursy walut (tabela A), złoto | jedyne źródło FX; brak notowania w D → `max(date) <= D`; weekendy i święta |
| Stooq | GPW, indeksy PL | CSV, symbole typu `cdr`, `wig20`; brak `close_adj` → przyjmij `close` i odnotuj |
| yfinance | rynki zagraniczne, metadane | nieoficjalne API, potrafi milczeć; sektor/kraj tylko dla akcji, dla ETF przybliżenie |
| Finnhub | fallback dla zagranicy, dywidendy | klucz API, limit darmowy |
| CoinGecko | krypto | identyfikatory nie są tickerami (`bitcoin`, nie `BTC`) |

## Reguły twarde

1. Symbol zewnętrzny **wyłącznie** z `asset_source_map`. Zero sklejania w kodzie.
2. Wycena zawsze na `close_adj`.
3. Zapis idempotentny: `INSERT ... ON CONFLICT (asset_id, date) DO UPDATE`.
4. Godziny jobów EOD z tabeli `markets`, nie z kodu.
5. Każdy przebieg → `ingestion_runs`. Bez tego nie wiadomo, czy dane są świeże — a `/meta/freshness` to publiczny kontrakt aplikacji.
6. Dzień bez notowania (święto) to nie błąd. Brak notowania przez trzy dni robocze pod rząd — alert.

## Testy

Nagrane odpowiedzi w `tests/fixtures/providers/<dostawca>/*.json|csv`. Testy jednostkowe parsowania + testy zachowania limitera i breakera na sztucznym zegarze. Realne API tylko pod markerem `network`, poza CI.

## Gdy dane wyglądają źle

Kolejność diagnozy: `ingestion_runs` (czy job się wykonał) → `prices` (czy jest wiersz na dzień D) → `asset_source_map` (czy symbol poprawny) → kurs w `fx_rates` (czy nie brakuje dnia) → dopiero potem logika wyceny.
