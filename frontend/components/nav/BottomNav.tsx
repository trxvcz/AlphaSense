import Link from "next/link";
import { NAV_ITEMS } from "@/components/nav/navItems";
import { AuthStatus } from "@/components/nav/AuthStatus";

/**
 * Dolna nawigacja — widoczna tylko na mobile (do `md:`), zgodnie z zasadą
 * mobile first. Server Component: linki są statyczne, jedyny interaktywny
 * fragment (`AuthStatus`, stan zalogowania) jest wydzielony do osobnego
 * Client Component.
 */
export function BottomNav() {
  return (
    <nav
      aria-label="Nawigacja główna"
      className="fixed inset-x-0 bottom-0 z-10 flex h-16 border-t border-zinc-200 bg-white md:hidden dark:border-zinc-800 dark:bg-zinc-950"
    >
      <ul className="flex w-full">
        {NAV_ITEMS.map((item) => (
          <li key={item.href} className="flex-1">
            <Link
              href={item.href}
              className="flex h-full flex-col items-center justify-center gap-1 text-xs font-medium text-zinc-600 outline-offset-2 hover:text-zinc-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-zinc-400 dark:hover:text-zinc-50"
            >
              {item.label}
            </Link>
          </li>
        ))}
        <li className="flex-1">
          <AuthStatus variant="bottom" />
        </li>
      </ul>
    </nav>
  );
}
