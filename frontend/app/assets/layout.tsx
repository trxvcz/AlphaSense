import type { ReactNode } from "react";
import { AuthGuard } from "@/components/auth/AuthGuard";

/**
 * `/assets/**` wymaga zalogowania, mimo że sam endpoint notowań jest
 * publiczny (`marketdata/routes.py`: aktywa i ceny to słownik globalny,
 * nie zasób użytkownika). Powód jest produktowy, nie bezpieczeństwa:
 * na ten ekran wchodzi się z portfela, watchlisty albo panelu rynków,
 * więc anonimowy wjazd prowadziłby donikąd.
 */
export default function AssetsLayout({ children }: { children: ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
