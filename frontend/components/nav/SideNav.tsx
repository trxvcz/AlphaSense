import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { NAV_ITEMS } from "@/components/nav/navItems";
import { AuthStatus } from "@/components/nav/AuthStatus";
import { ThemeToggle } from "@/components/ui/ThemeToggle";

/**
 * Boczna nawigacja — widoczna od `md:` wzwyż. Server Component: linki są
 * statyczne, jedyny interaktywny fragment (`AuthStatus`, stan zalogowania)
 * jest wydzielony do osobnego Client Component.
 */
export async function SideNav() {
  // Server Component, więc tłumaczenia bierzemy z `next-intl/server` —
  // `useTranslations` działa tylko po stronie klienta.
  const t = await getTranslations("nav");

  return (
    <aside className="hidden w-56 shrink-0 border-r border-zinc-200 md:flex md:flex-col dark:border-zinc-800">
      <div className="flex items-center justify-between px-4 py-5">
        <span className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
          AlphaSense
        </span>
        <ThemeToggle />
      </div>
      <nav aria-label={t("aria")} className="flex flex-1 flex-col justify-between">
        <ul className="flex flex-col gap-1 px-2">
          {NAV_ITEMS.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                className="block rounded-md px-3 py-2 text-sm font-medium text-zinc-600 outline-offset-2 hover:bg-zinc-100 hover:text-zinc-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-50"
              >
                {t(item.labelKey)}
              </Link>
            </li>
          ))}
        </ul>
        <div className="border-t border-zinc-200 px-2 py-2 dark:border-zinc-800">
          <AuthStatus variant="side" />
        </div>
      </nav>
    </aside>
  );
}
