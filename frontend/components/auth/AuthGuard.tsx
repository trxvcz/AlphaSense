"use client";

/**
 * Chroni trasy klienckie, którym token in-memory nie pozwala na SSR-auth
 * (CLAUDE.md — decyzja architektoniczna: access token nigdy nie trafia do
 * cookie/localStorage, więc middleware serwerowy nie ma czego sprawdzić).
 *
 * Podczas startowego silent-refresh (`isInitializing`) pokazujemy szkielet
 * zamiast przekierowywać na ślepo — inaczej zalogowany użytkownik po F5
 * widziałby na chwilę `/login`. Krótki „flash" treści-przed-przekierowaniem
 * dla niezalogowanego jest akceptowalny na tym etapie (brak SSR-auth).
 */
import { useEffect } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/AuthProvider";

export function AuthGuard({ children }: { children: ReactNode }) {
  const { isAuthenticated, isInitializing } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isInitializing && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isInitializing, isAuthenticated, router]);

  if (isInitializing) {
    return <GuardSkeleton />;
  }

  if (!isAuthenticated) {
    return null;
  }

  return <>{children}</>;
}

function GuardSkeleton() {
  return (
    <div
      role="status"
      aria-label="Sprawdzanie sesji"
      className="flex flex-col gap-4 px-4 py-8 sm:px-6 lg:px-8"
    >
      <div className="h-6 w-48 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
      <div className="h-24 w-full animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
    </div>
  );
}
