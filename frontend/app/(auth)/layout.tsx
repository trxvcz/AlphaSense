/**
 * Layout wspólny dla `/login` i `/register` — wyśrodkowana karta, bez
 * dodatkowego chrome (nawigacja główna z `app/layout.tsx` i tak jest
 * widoczna dookoła, to tylko centrowanie treści). Server Component: brak
 * interakcji.
 */
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center px-4 py-8 md:min-h-screen">
      {children}
    </div>
  );
}
