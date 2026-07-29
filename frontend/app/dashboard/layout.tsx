import type { ReactNode } from "react";
import { AuthGuard } from "@/components/auth/AuthGuard";

/**
 * `/dashboard` wymaga zalogowania — dashboard dotyczy zawsze czyjegoś
 * portfela. Server Component, samo owinięcie w `AuthGuard` (ten sam wzorzec
 * co `app/rynki/layout.tsx` i `app/struktura/layout.tsx`).
 */
export default function DashboardLayout({ children }: { children: ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
