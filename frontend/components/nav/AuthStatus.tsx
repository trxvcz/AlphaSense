"use client";

/**
 * Stan zalogowania w nawigacji — link „Zaloguj się" (niezalogowany) albo
 * przycisk „Wyloguj" (zalogowany). Jedyny fragment nawigacji wymagający
 * `"use client"` (CLAUDE.md #2: server components domyślnie, `use client`
 * tylko gdzie potrzebna interakcja) — `SideNav`/`BottomNav` zostają
 * Server Components i tylko go renderują.
 */
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth/AuthProvider";

const LINK_CLASSES =
  "block rounded-md px-3 py-2 text-sm font-medium text-zinc-600 outline-offset-2 hover:bg-zinc-100 hover:text-zinc-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-50";

const TAB_CLASSES =
  "flex h-full w-full flex-col items-center justify-center gap-1 text-xs font-medium text-zinc-600 outline-offset-2 hover:text-zinc-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-zinc-400 dark:hover:text-zinc-50";

type AuthStatusProps = {
  variant: "side" | "bottom";
};

export function AuthStatus({ variant }: AuthStatusProps) {
  const { isAuthenticated, isInitializing, logout } = useAuth();
  const router = useRouter();
  const className = variant === "side" ? LINK_CLASSES : TAB_CLASSES;

  if (isInitializing) return null;

  if (!isAuthenticated) {
    return (
      <Link href="/login" className={className}>
        Zaloguj się
      </Link>
    );
  }

  return (
    <button
      type="button"
      className={className}
      onClick={() => {
        void logout().then(() => router.push("/login"));
      }}
    >
      Wyloguj
    </button>
  );
}
