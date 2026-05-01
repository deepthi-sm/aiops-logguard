import { cn } from "../lib/cn";

/**
 * Subtle pulsing skeleton placeholder — pulses between bg-card and bg-hover.
 * Per spec: "Empty states never use a spinner — use a skeleton or a real
 * empty message." Match the shape of what's loading; pass classes for
 * width/height/radius.
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md bg-card",
        className,
      )}
      aria-hidden
    />
  );
}
