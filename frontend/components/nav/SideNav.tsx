import Link from "next/link";
import { NAV_ITEMS } from "@/components/nav/navItems";

/**
 * Boczna nawigacja — widoczna od `md:` wzwyż. Server Component: same
 * linki, bez interakcji.
 */
export function SideNav() {
  return (
    <aside className="hidden w-56 shrink-0 border-r border-zinc-200 md:flex md:flex-col dark:border-zinc-800">
      <div className="px-4 py-5 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
        AlphaSense
      </div>
      <nav aria-label="Nawigacja główna">
        <ul className="flex flex-col gap-1 px-2">
          {NAV_ITEMS.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                className="block rounded-md px-3 py-2 text-sm font-medium text-zinc-600 outline-offset-2 hover:bg-zinc-100 hover:text-zinc-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-50"
              >
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
