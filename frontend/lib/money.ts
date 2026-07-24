/**
 * Formatowanie kwot i procentów przychodzących z API.
 *
 * Backend zwraca kwoty i ilości jako stringi dziesiętne (nigdy `float`,
 * patrz CLAUDE.md sekcja 3.1 i docs/konwencje.md). `Number()` w tym module
 * służy WYŁĄCZNIE do wyświetlenia — żadnych obliczeń finansowych na froncie.
 */

const plnFormatter = new Intl.NumberFormat("pl-PL", {
  style: "currency",
  currency: "PLN",
});

const pctFormatter = new Intl.NumberFormat("pl-PL", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

/**
 * Formatuje kwotę w PLN. Przyjmuje string dziesiętny z API, np. "128450.32".
 */
export function pln(value: string): string {
  return plnFormatter.format(Number(value));
}

/**
 * Formatuje udział/zmianę procentową. Przyjmuje string dziesiętny z API
 * jako ułamek, np. "0.0765" -> "7,7%".
 */
export function pct(value: string): string {
  return pctFormatter.format(Number(value));
}
