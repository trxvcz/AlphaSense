# Słownik rynków i indeksów referencyjnych (ADR-102)

Startowa zawartość tabeli `markets`. Zasilana seedem (krok 19). Godziny EOD są **jednocześnie** harmonogramem jobów workera — to jedno źródło prawdy.

| code | nazwa | indeks referencyjny | symbol indeksu | timezone | eod_time (lokalny CET) |
|---|---|---|---|---|---|
| GPW | Giełda Papierów Wartościowych | WIG20 | `wig20` (Stooq) | Europe/Warsaw | 18:30 |
| US | NYSE / NASDAQ | S&P 500 | `^GSPC` | America/New_York | 23:15 |
| US_TECH | NASDAQ (tech) | NASDAQ 100 | `^NDX` | America/New_York | 23:15 |
| XETRA | Deutsche Börse | DAX | `^GDAXI` | Europe/Berlin | 18:00 |
| LSE | London Stock Exchange | FTSE 100 | `^FTSE` | Europe/London | 18:15 |
| EURONEXT | Euronext (Paryż/Amsterdam) | CAC 40 | `^FCHI` | Europe/Paris | 18:00 |
| SIX | SIX Swiss Exchange | SMI | `^SSMI` | Europe/Zurich | 18:00 |
| TSE | Tokyo Stock Exchange | Nikkei 225 | `^N225` | Asia/Tokyo | 09:00 |
| HKEX | Hong Kong | Hang Seng | `^HSI` | Asia/Hong_Kong | 10:30 |
| CRYPTO | Rynek krypto (24/7) | Bitcoin | `bitcoin` (CoinGecko) | UTC | 00:30 |
| COMMODITY | Surowce | złoto (NBP) | `XAU` | Europe/Warsaw | 12:35 |
| FX | Waluty (NBP tabela A) | — | — | Europe/Warsaw | 12:35 |

## Zasady

- `market_code` aktywa nadawany automatycznie przy dodaniu (na podstawie giełdy z metadanych), z możliwością ręcznej korekty.
- Rynek bez indeksu referencyjnego (`FX`) pokazuje w rankingu samą wagę — bez pustego wykresu.
- Dodanie nowego rynku = wiersz w tabeli + wpis aktywa indeksu + mapowanie w `asset_source_map`. Zero zmian w kodzie.
- Godziny są celowo ustawione z zapasem po zamknięciu sesji — dostawcy publikują dane z opóźnieniem.
