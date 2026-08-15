import type { ReactNode } from "react";
import { AuthGuard } from "@/components/auth/AuthGuard";

/**
 * `/newsy` wymaga zalogowania — feed jest wyznaczony przez pozycje
 * konkretnego portfela. Server Component, samo owinięcie w `AuthGuard`
 * (ten sam wzorzec co `app/rynki/layout.tsx`).
 */
export default function NewsyLayout({ children }: { children: ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
