/**
 * Paleta kategorialna i „chrome" wykresów struktury (plan krok 33).
 *
 * Dlaczego hexy, skoro `docs/konwencje.md` każe kolorować klasami Tailwind:
 * ECharts wymaga literalnych kolorów w obiekcie opcji — nie da się ostylować
 * kanwy klasami. To samo ustępstwo, co w `components/charts/ValueChart.tsx`
 * (krok 32); różnica jest taka, że tam był JEDEN kolor serii, a tu potrzebna
 * jest paleta kategorialna dzielona przez trzy wykresy, więc żyje w jednym
 * module zamiast być przepisywana w każdym z nich.
 *
 * Kolejność slotów jest mechanizmem bezpieczeństwa dla daltonistów, nie
 * kosmetyką — koszyk dostaje kolor wg swojej pozycji po posortowaniu malejąco
 * po wadze i nigdy nie zapętlamy palety (koszyki ponad limit trafiają do
 * „Pozostałe", patrz `toChartSlices` w `lib/allocationLabels.ts`).
 *
 * Zweryfikowane walidatorem palety (skill `dataviz`,
 * `scripts/validate_palette.js`) na POWIERZCHNIACH TEJ APLIKACJI
 * (`bg-white` = #ffffff, `dark:bg-zinc-950` = #09090b), sześć użytych slotów:
 *
 *   light: pasmo jasności PASS, chroma PASS, separacja CVD ΔE 9,1 PASS,
 *          widzenie normalne ΔE 19,6 PASS, kontrast WARN (aqua/żółty/magenta
 *          poniżej 3:1 wobec bieli)
 *   dark:  wszystkie sześć kontroli PASS
 *
 * Ostrzeżenie o kontraście w trybie jasnym jest świadomie przyjęte i pokryte
 * wymaganym „reliefem": każdy wykres ma widoczne etykiety wartości ORAZ
 * tabelaryczną alternatywę pod spodem (`AllocationTable`), więc kolor nigdy
 * nie jest jedynym nośnikiem informacji. Zmiana tych hexów wymaga ponownego
 * przebiegu walidatora — nie dobieraj kolorów „na oko".
 */

/** Sloty kategorialne w stałej kolejności — indeks = pozycja koszyka. */
const CATEGORICAL_LIGHT = [
  "#2a78d6", // niebieski
  "#eb6834", // pomarańczowy
  "#1baf7a", // morski
  "#eda100", // żółty
  "#e87ba4", // magenta
  "#008300", // zielony
] as const;

const CATEGORICAL_DARK = [
  "#3987e5",
  "#d95926",
  "#199e70",
  "#c98500",
  "#d55181",
  "#008300",
] as const;

/** Kolor koszyka zbiorczego „Pozostałe" — celowo neutralny, nie kolejna barwa. */
const OTHER_LIGHT = "#a1a1aa";
const OTHER_DARK = "#71717a";

/** Ile koszyków dostaje własny kolor, zanim reszta trafi do „Pozostałe". */
export const CATEGORICAL_SLOTS = CATEGORICAL_LIGHT.length;

/**
 * Kolory dla listy koszyków posortowanej malejąco po wadze. Ostatni koszyk
 * dostaje kolor neutralny, jeśli jest koszykiem zbiorczym.
 */
export function categoricalColors(count: number, isDark: boolean): string[] {
  const palette = isDark ? CATEGORICAL_DARK : CATEGORICAL_LIGHT;
  return Array.from({ length: count }, (_, index) => palette[index] ?? palette[palette.length - 1]!);
}

export function otherColor(isDark: boolean): string {
  return isDark ? OTHER_DARK : OTHER_LIGHT;
}

/** Kolor pojedynczej serii (słupki sektor/geografia — identyczność niesie etykieta osi, nie barwa). */
export function singleSeriesColor(isDark: boolean): string {
  return isDark ? CATEGORICAL_DARK[0] : CATEGORICAL_LIGHT[0];
}

/**
 * Kolory osi, siatki i tekstu na kanwie — te same wartości co w `ValueChart`
 * (zinc-400/zinc-600 i zinc-700/zinc-200), żeby wykresy z kroków 32 i 33
 * wyglądały jak jeden system.
 */
export function chartChrome(isDark: boolean) {
  return {
    axis: isDark ? "#a1a1aa" : "#52525b",
    splitLine: isDark ? "#3f3f46" : "#e4e4e7",
    label: isDark ? "#e4e4e7" : "#27272a",
    /** Tło „szczelin" między kafelkami treemapy i segmentami donuta. */
    surface: isDark ? "#09090b" : "#ffffff",
  };
}
