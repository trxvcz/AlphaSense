---
name: job-eod
description: Procedura pisania jobów harmonogramu w workerze Portfela v2 — APScheduler, blokady doradcze Postgresa, ingestia cen per rynek, snapshoty portfeli, idempotencja i zapis do ingestion_runs. Użyj gdy dodajesz zadanie cykliczne, zmieniasz harmonogram pobierania danych, debugujesz brakujące notowania lub snapshoty, albo gdy job wykonał się dwa razy.
---

# Joby EOD w workerze

## Zasady

1. Worker to osobny kontener, ten sam obraz co API, entrypoint `worker/scheduler.py`. Zero jobów w procesie API.
2. **Harmonogram czytany ze słownika `markets`** przy starcie workera (kod, strefa czasowa, `eod_time`). Dodanie rynku = wpis w tabeli, nie zmiana kodu.
3. Każdy job na starcie bierze **blokadę doradczą Postgresa**:

```python
async with advisory_lock(db, key=f"eod:{market_code}:{run_date}") as acquired:
    if not acquired:
        log.info("job już działa gdzie indziej, pomijam")
        return
```

4. Idempotencja: ponowne uruchomienie za ten sam dzień nadpisuje wiersze (`ON CONFLICT DO UPDATE`), nigdy nie duplikuje.
5. Każdy przebieg zapisuje `ingestion_runs`: rynek, `started_at`, `finished_at`, liczba aktywów, liczba sukcesów i porażek, dostawca, status, komunikat błędu.
6. Job nie przerywa się na pierwszym błędzie aktywa — zbiera błędy, kończy resztę, na końcu raportuje. Niepowodzenie całości = alert (Sentry).

## Kolejność dobowa

```
12:35  NBP        kursy walut + złoto        ← musi być przed wycenami
18:30  GPW        ceny + WIG20
23:15  US         ceny + ^SPX, ^NDX
00:30  CRYPTO     ceny + BTC
po każdym EOD →  snapshot portfeli (wycena → portfolio_valuations)
```

Snapshot uruchamiany po ingestii, nie równolegle. Jeśli kursów NBP brakuje — snapshot i tak powstaje, na ostatnim znanym kursie (`max(date) <= D`), a w logu ląduje ostrzeżenie.

## Snapshot portfeli

```python
for portfolio in all_portfolios:
    value = await valuation_service.current_value(portfolio, on_date=D)
    await upsert_valuation(portfolio.id, D, value,
                           composition_change=has_holdings_change(portfolio, D))
```

`composition_change` ustawiasz, gdy tego dnia zmieniono skład portfela (dodanie, usunięcie lub zmiana ilości pozycji). Ten znacznik jest później podstawą wyłączania dnia z serii zwrotów (ADR-101) i znacznika na wykresie.

## Uzupełnianie braków

Job startowy (`backfill`) przy dodaniu nowego aktywa pobiera historię wstecz (domyślnie 2 lata) — jednorazowo, z tym samym limiterem, w tle, z niższym priorytetem niż joby dzienne.

## Diagnostyka

```bash
make logs s=worker
docker compose exec api python -m app.cli ingestion-status --days 7
```

Kolejność sprawdzania przy braku danych: czy job wystartował (`ingestion_runs`) → czy breaker nie jest otwarty (Redis) → czy symbol jest w `asset_source_map` → czy dostawca zwrócił pusto (święto?) → dopiero potem kod.
