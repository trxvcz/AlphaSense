import type { ReactNode } from "react";
import { AuthGuard } from "@/components/auth/AuthGuard";

/**
 * `/obserwowane` wymaga zalogowania — lista obserwowanych należy do
 * użytkownika (ten sam wzorzec co `app/struktura/layout.tsx`).
 */
export default function ObserwowaneLayout({ children }: { children: ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
