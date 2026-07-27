/**
 * Kolor Tailwind dla zmiany wartości/ceny wg znaku (CLAUDE.md #7 dashboard,
 * krok 32) — konwencja ustalona tutaj (brak wcześniejszej w repo):
 * dodatnia zielona, ujemna czerwona, zero neutralna. Kontrast AA w obu
 * trybach (jasny/ciemny), patrz `konwencje.md` „dostępność".
 */
export function changeColorClass(pctValue: string): string {
  const n = Number(pctValue);
  if (n > 0) return "text-emerald-700 dark:text-emerald-400";
  if (n < 0) return "text-red-700 dark:text-red-400";
  return "text-zinc-600 dark:text-zinc-400";
}
