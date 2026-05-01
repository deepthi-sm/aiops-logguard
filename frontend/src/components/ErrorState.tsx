/**
 * Inline error-state placeholder — error message + Retry button. Used
 * when a section's query fails so the rest of the page still renders.
 */
export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-4 py-10 text-center">
      <div className="text-[13px] text-critical">{message}</div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-md border-[0.5px] border-border-default bg-card px-3 py-1 text-[11px] text-secondary transition-colors hover:bg-hover hover:text-primary"
        >
          Retry
        </button>
      )}
    </div>
  );
}
