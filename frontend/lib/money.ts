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

const decimalFormatter = new Intl.NumberFormat("pl-PL", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
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

/**
 * Formatuje kwotę w nieznanej/instrumentowej walucie (np. `price_change_1d.abs`,
 * gdzie API nie zwraca waluty aktywa) — bez symbolu waluty, tylko liczba.
 * Wołający dokleja walutę jako osobny tekst, jeśli ją zna.
 */
export function decimal(value: string): string {
  return decimalFormatter.format(Number(value));
}
