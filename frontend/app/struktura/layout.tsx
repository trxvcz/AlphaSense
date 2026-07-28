import type { ReactNode } from "react";
import { AuthGuard } from "@/components/auth/AuthGuard";

/**
 * `/struktura` wymaga zalogowania — struktura zawsze dotyczy czyjegoś
 * portfela. Server Component, samo owinięcie w `AuthGuard` (ten sam wzorzec
 * co `app/portfolios/layout.tsx`).
 */
export default function StrukturaLayout({ children }: { children: ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
