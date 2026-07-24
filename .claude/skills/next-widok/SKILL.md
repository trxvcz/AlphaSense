---
name: next-widok
description: Konwencje budowy widoków i wykresów we frontendzie Next.js projektu AlphaSense — struktura tras, TanStack Query, formatowanie kwot, ECharts, stany puste, mobile first. Użyj gdy tworzysz lub zmieniasz ekran aplikacji, dodajesz wykres, formularz pozycji, panel „Twoje rynki" albo integrujesz nowy endpoint z interfejsem.
---

# Widok frontendowy

## Struktura

```
frontend/
  app/
    (auth)/logowanie/, rejestracja/
    (app)/
      dashboard/page.tsx
      portfel/[id]/page.tsx
      struktura/page.tsx
      rynki/page.tsx
      pozycje/nowa/page.tsx
  components/
    ui/          przyciski, karty, skeletony
    charts/      ValueChart, AllocationDonut, Treemap, MarketSparkline
    forms/       HoldingForm
  lib/
    api.ts       klient z obsługą refresh tokenu
    queryKeys.ts jedno miejsce z kluczami zapytań
    money.ts     formatowanie kwot i procentów
```

## Pobieranie danych

```ts
// lib/queryKeys.ts
export const qk = {
  summary:    (pid: string) => ["summary", pid] as const,
  allocation: (pid: string, by: Dimension) => ["allocation", pid, by] as const,
  markets:    (pid: string) => ["markets", pid] as const,
};
```

Server Component pobiera dane początkowe, Client Component odświeża przez TanStack Query. Mutacje (dodanie/edycja pozycji) unieważniają `summary`, `allocation` i `markets` dla danego portfela.

## Kwoty

```ts
// lib/money.ts
export const pln = (v: string) =>
  new Intl.NumberFormat("pl-PL", { style: "currency", currency: "PLN" }).format(Number(v));
export const pct = (v: string) =>
  new Intl.NumberFormat("pl-PL", { style: "percent", minimumFractionDigits: 1 }).format(Number(v));
```

`Number()` wyłącznie do **wyświetlenia**. Żadnych obliczeń finansowych na froncie — od tego jest backend.

## Wykresy (ECharts)

```tsx
const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });
```

- Wykres wartości: zakresy 1M / 3M / 1R / YTD / max, pionowe znaczniki w dniach `composition_change` z tooltipem „zmiana składu portfela".
- Donut klas aktywów, treemap pozycji i walut, słupki sektor/geografia.
- Kolory z tokenów Tailwind (CSS variables), działa w dark i light. Nie hardkoduj hexów w komponencie wykresu.
- Wykres ma alternatywę: tabela pod spodem albo etykiety liczbowe na serii.

## Stany

Każdy widok obsługuje trzy:

```tsx
if (isLoading) return <CardSkeleton />;
if (error)     return <ErrorState onRetry={refetch} />;
if (isEmpty)   return <EmptyState cta="Dodaj pierwszą pozycję" href="/pozycje/nowa" />;
```

Stan pusty to nie błąd — to najważniejszy ekran dla nowego użytkownika. Ma prowadzić do dodania pozycji jednym kliknięciem.

## Mobile first

Projektujesz na 375 px. Dolna nawigacja (Dashboard / Struktura / Rynki / Dodaj), boczna od `md:`. Formularz dodawania pozycji: autouzupełnianie tickera z `/assets/search` z debounce 300 ms, klawiatura numeryczna dla ilości (`inputMode="decimal"`), cena nabycia jako pole opcjonalne, wyraźnie oznaczone.

## Świeżość danych

Dane pochodzą z EOD. Każdy widok wartości pokazuje dyskretny znacznik „dane z {data}" na podstawie `/meta/freshness`. Gdy dane są starsze niż dwa dni robocze — ostrzeżenie, nie ciche pokazywanie starych liczb.
