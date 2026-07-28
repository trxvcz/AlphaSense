/**
 * Etykiety i przygotowanie koszyków alokacji do wykresu (plan krok 33).
 *
 * Backend grupuje po SUROWYCH atrybutach aktywa (`asset_class`, `sector`,
 * `currency`, `country`/`region`) — `analytics/service.py::_bucket_key`.
 * Klasy i sektory są w bazie po angielsku (`equity`, `technology`), a UI ma
 * być po polsku (CLAUDE.md sekcja 9), więc tłumaczenie żyje tutaj — w jednym
 * miejscu, nie rozsiane po komponentach wykresów.
 *
 * Geografia i waluta NIE są tłumaczone: `country`/`region` są w seedzie już
 * po polsku („Polska", „Globalny"), a kody walut są międzynarodowe.
 */
import { CATEGORICAL_SLOTS } from "@/lib/chartPalette";
import type { AllocationBucket, AllocationDimension } from "@/lib/analytics";

/** Koszyk zbiorczy z backendu (`_UNKNOWN_BUCKET` w `analytics/service.py`). */
const UNKNOWN_KEY = "nieznane";

export const DIMENSION_LABELS: Record<AllocationDimension, string> = {
  class: "Klasa aktywów",
  sector: "Sektor",
  geo: "Geografia",
  currency: "Waluta",
  market: "Rynek",
};

const CLASS_LABELS: Record<string, string> = {
  equity: "Akcje",
  etf: "ETF",
  index: "Indeksy",
  crypto: "Kryptowaluty",
  commodity: "Surowce",
  bond: "Obligacje",
  cash: "Gotówka",
};

const SECTOR_LABELS: Record<string, string> = {
  technology: "Technologia",
  energy: "Energetyka",
  gaming: "Gaming",
  finance: "Finanse",
  healthcare: "Ochrona zdrowia",
  industrials: "Przemysł",
  materials: "Surowce i materiały",
  utilities: "Usługi komunalne",
  consumer: "Dobra konsumenckie",
  telecom: "Telekomunikacja",
  real_estate: "Nieruchomości",
};

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

/**
 * Etykieta koszyka do wyświetlenia. Nieznany klucz (nowy sektor w bazie,
 * klasa spoza mapy) NIE jest błędem — pokazujemy go w oryginale z wielkiej
 * litery, zamiast gubić koszyk albo pokazywać pustą etykietę.
 */
export function bucketLabel(by: AllocationDimension, key: string): string {
  if (key === UNKNOWN_KEY) return "Nieznane";
  if (by === "class") return CLASS_LABELS[key] ?? capitalize(key);
  if (by === "sector") return SECTOR_LABELS[key] ?? capitalize(key);
  return key;
}

/** Objaśnienie pod wykresem — to, czego sam wykres nie jest w stanie powiedzieć. */
export const DIMENSION_NOTES: Partial<Record<AllocationDimension, string>> = {
  geo: "Grupowanie po kraju aktywa; gdy kraj jest nieznany — po regionie (stąd koszyki w rodzaju „Globalny” dla kryptowalut i złota).",
  sector: "Sektor pochodzi ze słownika aktywów, nie z bieżącej klasyfikacji giełdowej.",
};

export type ChartSlice = {
  label: string;
  /**
   * Wartość w PLN jako `number` — WYŁĄCZNIE do narysowania geometrii wykresu
   * (ECharts nie przyjmuje stringów dziesiętnych). Dokładne kwoty z API
   * pokazuje tabela pod wykresem, która nigdy nie przechodzi przez `Number`
   * do niczego poza formatowaniem (`lib/money.ts`).
   */
  value: number;
  /** Udział jako ułamek — do etykiety na wykresie. */
  weight: number;
  /** Koszyk zbiorczy „Pozostałe" dostaje kolor neutralny, nie kolejną barwę. */
  isOther: boolean;
};

/**
 * Koszyki posortowane malejąco po wadze i przycięte do liczby slotów palety.
 *
 * Powód przycięcia (skill `dataviz`): palety kategorialnej nigdy się nie
 * zapętla — dziewiąta seria w cyklu dostałaby kolor drugiej i użytkownik
 * przeczytałby dwa różne koszyki jako jeden. Nadmiar składamy w jeden koszyk
 * „Pozostałe”. Sumowanie na `number` jest tu dopuszczalne, bo dotyczy
 * WYŁĄCZNIE geometrii i etykiety wykresu — pełna, dokładna lista koszyków ze
 * stringami z API jest zawsze widoczna w tabeli pod spodem.
 */
export function toChartSlices(
  buckets: AllocationBucket[],
  by: AllocationDimension,
  maxSlices: number = CATEGORICAL_SLOTS,
): ChartSlice[] {
  const sorted = [...buckets].sort((a, b) => Number(b.weight) - Number(a.weight));
  if (sorted.length <= maxSlices) {
    return sorted.map((bucket) => ({
      label: bucketLabel(by, bucket.key),
      value: Number(bucket.value_pln),
      weight: Number(bucket.weight),
      isOther: false,
    }));
  }

  const head = sorted.slice(0, maxSlices - 1);
  const tail = sorted.slice(maxSlices - 1);
  return [
    ...head.map((bucket) => ({
      label: bucketLabel(by, bucket.key),
      value: Number(bucket.value_pln),
      weight: Number(bucket.weight),
      isOther: false,
    })),
    {
      label: `Pozostałe (${tail.length})`,
      value: tail.reduce((sum, bucket) => sum + Number(bucket.value_pln), 0),
      weight: tail.reduce((sum, bucket) => sum + Number(bucket.weight), 0),
      isOther: true,
    },
  ];
}
