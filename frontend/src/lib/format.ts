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

/** 0.9999 → ".9999"; 0.6631 → ".6631"; 0.85 → ".85".
 *
 * The default precision adapts to the value's saturation. The
 * detection ensemble (Transformer + AutoEncoder) was trained on
 * OpenStack and saturates near 1.0 on cross-domain inputs (BGL,
 * Thunderbird), and the confidence MLP saturates near 0.66 on those
 * same inputs. With a flat 2-decimal display, 1500+ anomalies all
 * read as "1.00 / .66" even though the underlying floats vary in
 * the third and fourth decimal — looks broken.
 *
 * So: when a score lands in a saturated band (close to 0, 1, or the
 * confidence saturation point near 2/3), render four decimals; the
 * mid-range stays at two for readability.
 */
export function formatScoreDecimal(score: number, digits?: number): string {
  let effective = digits ?? 2;
  if (digits === undefined) {
    const saturated =
      score >= 0.95 || score <= 0.05 ||
      (score >= 0.6 && score <= 0.7);   // confidence MLP saturation band
    if (saturated) effective = 4;
  }
  return score.toFixed(effective).replace(/^0/, "");
}
