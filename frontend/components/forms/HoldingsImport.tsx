"use client";

/**
 * Import listy pozycji z CSV (plan krok 48, etap 9) — mobile first, 375 px.
 *
 * Przepływ jest dwukrokowy z założenia: **podgląd, potem zapis**. Import
 * scala się z tym, co już jest w portfelu (dodaje ilość do istniejącej
 * pozycji), a tego nie da się cofnąć jednym przyciskiem — więc plik najpierw
 * leci z `dry_run=true` i użytkownik widzi dokładnie ten sam raport, który
 * dostanie po zapisie.
 *
 * Plik czytamy w przeglądarce (`File.text()`) i wysyłamy jako tekst; parser
 * jest wyłącznie po stronie backendu, żeby nie mieć dwóch definicji formatu.
 *
 * Dostępność: status wiersza niesie SŁOWO („dodano", „scalono", „pominięto"),
 * a kolor jest tylko wzmocnieniem — kolor nigdy nie jest jedynym kanałem
 * informacji (CLAUDE.md §21).
 */
import { useId, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import {
  MAX_CSV_CHARS,
  importHoldings,
  summarizeReport,
  type ImportReport,
  type ImportRowStatus,
} from "@/lib/holdingsImport";
import { qk } from "@/lib/queryKeys";

type HoldingsImportProps = {
  portfolioId: string;
  onImported?: () => void;
  onCancel?: () => void;
};

const STATUS_LABEL: Record<ImportRowStatus, string> = {
  created: "dodano",
  merged: "scalono",
  skipped: "pominięto",
};

const STATUS_CLASS: Record<ImportRowStatus, string> = {
  created: "text-emerald-700 dark:text-emerald-400",
  merged: "text-blue-700 dark:text-blue-400",
  skipped: "text-amber-700 dark:text-amber-400",
};

export function HoldingsImport({ portfolioId, onImported, onCancel }: HoldingsImportProps) {
  const fieldId = useId();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [content, setContent] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportReport | null>(null);
  const [saved, setSaved] = useState<ImportReport | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: ({ dryRun }: { dryRun: boolean }) =>
      importHoldings(portfolioId, content, dryRun),
    onSuccess: (report) => {
      setFormError(null);
      if (report.dry_run) {
        setPreview(report);
        return;
      }
      setSaved(report);
      setPreview(null);
      // Import zmienia skład portfela, więc unieważnia nie tylko listę
      // pozycji, ale i wszystko, co się z niej liczy (wycena, struktura).
      void queryClient.invalidateQueries({ queryKey: qk.holdings(portfolioId) });
      void queryClient.invalidateQueries({ queryKey: qk.summary(portfolioId) });
      onImported?.();
    },
    onError: (error) => {
      setFormError(
        error instanceof ApiError
          ? error.message
          : "Nie udało się wysłać pliku. Spróbuj ponownie.",
      );
    },
  });

  async function handleFile(file: File | null) {
    setSaved(null);
    setPreview(null);
    if (file === null) {
      setContent("");
      setFileName(null);
      return;
    }
    const text = await file.text();
    if (text.length > MAX_CSV_CHARS) {
      // Sprawdzamy tu tylko po to, żeby nie wysyłać megabajta na pewne 422 —
      // ostatecznym sędzią rozmiaru jest backend.
      setFormError(`Plik jest za duży (limit ${MAX_CSV_CHARS} znaków).`);
      setContent("");
      setFileName(null);
      return;
    }
    setFormError(null);
    setContent(text);
    setFileName(file.name);
  }

  const report = saved ?? preview;

  return (
    <section
      aria-labelledby={`${fieldId}-title`}
      className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
    >
      <div>
        <h3 id={`${fieldId}-title`} className="text-base font-medium">
          Import pozycji z pliku CSV
        </h3>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Jedna pozycja w linii, format <code>symbol;ilość;cena_nabycia</code>. Cena nabycia
          jest opcjonalna. Nagłówek kolumn możesz zostawić.
        </p>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Jeśli symbol jest już w portfelu, <strong>ilość zostanie dodana</strong> do
          istniejącej pozycji, a cena nabycia przeliczona na średnią ważoną.
        </p>
      </div>

      <div>
        <label htmlFor={`${fieldId}-file`} className="block text-sm font-medium">
          Plik CSV
        </label>
        <input
          ref={fileInputRef}
          id={`${fieldId}-file`}
          type="file"
          accept=".csv,text/csv,text/plain"
          onChange={(event) => void handleFile(event.target.files?.[0] ?? null)}
          className="mt-1 block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-zinc-100 file:px-3 file:py-2 file:text-sm dark:file:bg-zinc-800"
        />
        {fileName !== null && (
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">Wybrano: {fileName}</p>
        )}
      </div>

      {formError !== null && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-400">
          {formError}
        </p>
      )}

      {report !== null && (
        <div className="space-y-2">
          <p role="status" className="text-sm font-medium">
            {summarizeReport(report)}
          </p>
          <ul className="max-h-64 space-y-1 overflow-y-auto text-sm">
            {report.rows.map((row) => (
              <li key={row.line} className="flex flex-wrap gap-x-2">
                <span className="text-zinc-500 dark:text-zinc-500">linia {row.line}</span>
                <span className="font-medium">{row.symbol || "—"}</span>
                <span className={STATUS_CLASS[row.status]}>{STATUS_LABEL[row.status]}</span>
                {row.message !== null && (
                  <span className="text-zinc-600 dark:text-zinc-400">{row.message}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {saved === null && (
          <button
            type="button"
            disabled={content === "" || mutation.isPending}
            onClick={() => mutation.mutate({ dryRun: preview === null })}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-offset-2 hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 disabled:opacity-50"
          >
            {preview === null ? "Sprawdź plik" : "Zapisz do portfela"}
          </button>
        )}
        <button
          type="button"
          onClick={() => onCancel?.()}
          className="rounded-md border border-zinc-300 px-4 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600 dark:border-zinc-700"
        >
          {saved === null ? "Anuluj" : "Zamknij"}
        </button>
      </div>
    </section>
  );
}
