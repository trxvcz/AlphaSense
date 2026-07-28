import type { ReactNode } from "react";
import { AuthGuard } from "@/components/auth/AuthGuard";

/**
 * `/rynki` wymaga zalogowania — ranking rynków dotyczy zawsze czyjegoś
 * portfela. Server Component, samo owinięcie w `AuthGuard` (ten sam wzorzec
 * co `app/struktura/layout.tsx`).
 */
export default function RynkiLayout({ children }: { children: ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
