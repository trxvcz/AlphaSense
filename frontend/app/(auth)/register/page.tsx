import type { Metadata } from "next";
import { RegisterForm } from "@/components/auth/RegisterForm";

export const metadata: Metadata = {
  title: "Rejestracja — AlphaSense",
};

export default function RegisterPage() {
  return (
    <section className="flex w-full max-w-sm flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Załóż konto</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Zacznij monitorować skład i wycenę swojego portfela.
        </p>
      </div>
      <RegisterForm />
    </section>
  );
}
