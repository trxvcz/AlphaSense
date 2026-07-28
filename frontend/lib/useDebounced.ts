"use client";

import { useEffect, useState } from "react";

/**
 * Zwraca `value` opóźnione o `delayMs` od ostatniej zmiany.
 *
 * Używane przez autouzupełnianie tickera (`HoldingForm`, plan krok 35) —
 * bez tego każde naciśnięcie klawisza to jedno `GET /assets/search`, a ten
 * endpoint przy braku metadanych aktywa zleca w tle odpytanie yfinance.
 */
export function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
