import { Logo } from "../Logo";
import { BrandStats } from "./BrandStats";

/**
 * Marketing left-pane shared between /login and /signup. Top: brand.
 * Middle (centered): eyebrow + headline + subhead. Bottom: BrandStats
 * + footer copyright.
 */
export function AuthLeftPane() {
  return (
    <div className="flex h-full min-h-screen flex-col px-[56px] py-[60px]">
      {/* Brand */}
      <div className="flex items-center gap-2 text-iris">
        <Logo size={24} />
        <span className="text-[15px] font-medium tracking-tight text-primary">
          LogGuard
        </span>
      </div>

      {/* Middle */}
      <div className="flex flex-1 flex-col justify-center">
        <div className="text-[11px] uppercase tracking-[0.08em] text-tertiary">
          Anomaly intelligence
        </div>
        <h1 className="mt-3 font-display text-[36px] font-medium leading-[1.2] tracking-[-0.02em] text-primary">
          AI that finds
          <br />
          what your alerts miss.
        </h1>
        <p className="mt-5 max-w-[380px] text-[14px] leading-[1.6] text-secondary">
          Real-time log anomaly detection with explainable AI. Catches the
          failures threshold-based monitoring can't, and tells you why in
          plain English.
        </p>
      </div>

      {/* Stats + footer */}
      <div className="space-y-5">
        <BrandStats />
        <div className="font-mono text-[11px] text-muted">
          © 2026 · Privacy-first AIOps
        </div>
      </div>
    </div>
  );
}
