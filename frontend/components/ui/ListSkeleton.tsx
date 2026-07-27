type ListSkeletonProps = {
  rows?: number;
};

/** Skeleton listy — stan ładowania (CLAUDE.md #5). */
export function ListSkeleton({ rows = 3 }: ListSkeletonProps) {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Ładowanie">
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          className="h-16 w-full animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
        />
      ))}
    </div>
  );
}
