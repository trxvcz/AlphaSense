import type { ReactNode } from "react";
import { AuthGuard } from "@/components/auth/AuthGuard";

/**
 * Wszystko pod `/portfolios/**` wymaga zalogowania. Server Component —
 * samo owinięcie w `AuthGuard` (Client Component, tam żyje logika).
 */
export default function PortfoliosLayout({ children }: { children: ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
