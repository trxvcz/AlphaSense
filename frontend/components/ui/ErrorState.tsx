type ErrorStateProps = {
  message: string;
  onRetry?: () => void;
};

/** Stan błędu z akcją ponowienia — CLAUDE.md #5 / next-widok. */
export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
    >
      <p>{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md border border-red-300 px-3 py-1.5 text-sm font-medium text-red-800 outline-offset-2 hover:bg-red-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-600 dark:border-red-800 dark:text-red-100 dark:hover:bg-red-900"
        >
          Spróbuj ponownie
        </button>
      )}
    </div>
  );
}
