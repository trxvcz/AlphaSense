---
name: analityka-struktury
description: Definicje i implementacja obliczeń analitycznych Portfela v2 — wycena w PLN, alokacja wg klasy/sektora/geografii/waluty/rynku, koncentracja i HHI, ranking rynków, zwroty ze snapshotów, zmienność, Sharpe, max drawdown, beta. Użyj gdy implementujesz lub weryfikujesz jakiekolwiek obliczenie portfelowe, gdy liczby na dashboardzie nie zgadzają się z oczekiwaniem, albo gdy piszesz testy metryk.
---

# Obliczenia portfela

To serce produktu. Wzory tu opisane są kontraktem — jeśli implementacja się różni, implementacja jest błędna.

## Wycena pozycji

```
value_pln(h) = quantity(h) × close_adj(asset, D) × fx_pln(currency(asset), D)
```

gdzie `D` = ostatni dostępny dzień EOD, `close_adj` = cena skorygowana, `fx_pln` = kurs NBP z `max(date) <= D`. Dla aktywów w PLN `fx_pln = 1`.

Wartość portfela: suma po pozycjach. Pozycja bez ceny (brak notowania) **nie jest liczona jako zero** — jest wyłączana z sumy i sygnalizowana w odpowiedzi jako `stale`, z datą ostatniej znanej ceny.

## Alokacja

```sql
SELECT bucket, SUM(value_pln) / SUM(SUM(value_pln)) OVER () AS weight
FROM valued_holdings GROUP BY bucket
```

Wymiary (`?by=`): `class`, `sector`, `geo`, `currency`, `market`.

Zasady:
- Suma wag = 1 zawsze (test obowiązkowy). Zaokrąglenia rozliczaj na największym koszyku.
- Brak atrybutu → koszyk `nieznane`, nigdy pominięcie pozycji.
- Sektor/geografia dla ETF to przybliżenie — odpowiedź zawiera `approximate: true`, UI pokazuje etykietę „przybliżone".
- Ręczny override metadanych użytkownika ma pierwszeństwo przed danymi dostawcy.

## Koncentracja

- `top5_share` = suma wag pięciu największych pozycji
- `count` = liczba pozycji
- `hhi` = Σ wᵢ² po wagach pozycji (nie po klasach)

Interpretacja opisowa (jedno miejsce w kodzie, nie rozsiane po UI):
`hhi < 0.15` niska · `0.15 – 0.25` średnia · `> 0.25` wysoka koncentracja.

Pojedyncza pozycja daje HHI = 1. Dziesięć równych pozycji daje 0.1. To dobre testy jednostkowe.

## Ranking rynków (ADR-102)

```
GROUP BY assets.market_code po wycenionych pozycjach
→ dla każdego rynku: waga %, indeks referencyjny (markets.index_asset_id),
  wartość indeksu, zmiana d/d, mini-seria 30 dni
→ sortowanie malejąco po wadze
```

Indeks referencyjny to zwykłe aktywo w `assets`, pobierane tymi samymi jobami EOD. Jeśli rynek nie ma indeksu — pokaż samą wagę, bez pustego wykresu.

## Zwroty (ADR-101)

```
r_t = V_t / V_{t-1} − 1
```

ze snapshotów `portfolio_valuations`. **Dni z `composition_change = true` są wyłączane z serii zwrotów** — dokupienie nie może udawać zysku. To jedyna subtelność silnika i najczęstsze źródło błędów; test na to jest obowiązkowy:

> portfel 1000 PLN → użytkownik dopisuje pozycję wartą 500 PLN → snapshot 1500 PLN → zwrot za ten dzień **nie istnieje** (nie 50%).

## Ryzyko (Faza 2)

| Metryka | Wzór |
|---|---|
| zmienność roczna | `stdev(r) × √252` |
| Sharpe | `(mean(r) × 252 − rf) / (stdev(r) × √252)`, `rf` = konfigurowalna stopa NBP |
| max drawdown | `min(V_t / cummax(V) − 1)`; wykres underwater = cała ta seria |
| beta | `cov(r_p, r_b) / var(r_b)` względem wybranego benchmarku |

Minimalna liczba obserwacji: poniżej 30 dni nie pokazuj zmienności ani Sharpe'a — pokaż komunikat „za krótka historia". Fałszywa precyzja jest gorsza niż brak liczby.

## P/L niezrealizowany (opcjonalny)

```
pl(h) = (cena_bieżąca_pln − avg_cost_pln) × quantity
```
tylko dla pozycji z podanym `avg_cost`. UI **wyraźnie oddziela** pozycje bez kosztu — nie sumuj ich jako zero i nie prezentuj sumy P/L jako sumy portfela.

## Testy metryk

Testy na znanych liczbach, bez bazy: seria `[100, 110, 99]` → zwroty `[0.1, -0.1]`, drawdown `-10%`. Każda metryka ma test przypadku brzegowego: jedna obserwacja, seria stała (zmienność 0, Sharpe nieokreślony — zwróć `null`, nie dziel przez zero), portfel pusty.
