/**
 * Tiny formatting helpers — kept dependency-light. `date-fns` is the only
 * external dep, used for relative-time strings ("5m ago", "12h ago").
 */
import { formatDistanceToNowStrict } from "date-fns";

export function formatRelativeTime(iso: string): string {
  // Strict variant gives "5m" instead of "about 5 minutes" — feeds need terse.
  return formatDistanceToNowStrict(new Date(iso), { addSuffix: true });
}

/** 0.926 → "93%" (or "92.6%" with digits=1). */
export function formatScore(score: number, digits = 0): string {
  return `${(score * 100).toFixed(digits)}%`;
}

/** 1234 → "1,234". */
export function formatNumber(n: number): string {
  return n.toLocaleString();
}

/** 0.926 → ".926" — for ensemble scores when we want to avoid the % sign. */
export function formatScoreDecimal(score: number, digits = 2): string {
  return score.toFixed(digits).replace(/^0/, "");
}
