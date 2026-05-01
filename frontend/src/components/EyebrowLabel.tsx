import type { ReactNode } from "react";

/**
 * Eyebrow label — the small uppercase text that introduces every section.
 *
 * Per spec: 11px, uppercase, letter-spaced, tertiary text, 14px margin
 * below. Sentence case for the content (e.g. "Anomaly intelligence" not
 * "ANOMALY INTELLIGENCE" — the uppercase comes from the CSS, not the data).
 */
export function EyebrowLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-[14px] text-[11px] uppercase tracking-[0.08em] text-tertiary">
      {children}
    </div>
  );
}
