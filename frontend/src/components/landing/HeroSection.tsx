import { motion, useReducedMotion } from "framer-motion";
import { Link } from "react-router-dom";
import { Logo } from "../Logo";
import { EASE_OUT_CUBIC } from "./AnimatedSection";

/**
 * Hero section. Animated on initial page load (not scroll-triggered).
 * Restraint: 16px fade-up moves, staggered delays per element.
 */
export function HeroSection() {
  const reducedMotion = useReducedMotion();
  const fadeUp = (delay: number, distance = 16) =>
    reducedMotion
      ? { initial: { opacity: 1 }, animate: { opacity: 1 } }
      : {
          initial: { opacity: 0, y: distance },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.6, delay, ease: EASE_OUT_CUBIC },
        };

  return (
    <section
      id="overview"
      className="mx-auto max-w-[1100px] px-[56px] pb-[80px] pt-[100px]"
    >
      {/* Headline (now the topmost element — pill removed) */}
      <motion.h1
        {...fadeUp(0.1)}
        className="max-w-[850px] font-display text-[64px] font-medium leading-[1.05] tracking-[-0.03em] text-primary"
      >
        AI that finds <span className="text-iris">what your alerts</span> miss.
      </motion.h1>

      {/* Subhead */}
      <motion.p
        {...fadeUp(0.35)}
        className="mt-6 max-w-[620px] text-[17px] leading-[1.6] text-secondary"
      >
        Real-time log anomaly detection with explainable AI. Catches the
        failures threshold-based monitoring can't, predicts them 12 minutes
        early, and tells you why in plain English.
      </motion.p>

      {/* CTA */}
      <motion.div {...fadeUp(0.5, 12)} className="mt-8">
        <Link
          to="/signup"
          className="inline-flex items-center rounded-lg bg-iris px-5 py-3 text-[14px] font-medium text-page transition-colors hover:bg-iris-deep"
        >
          Get started, it's free
        </Link>
      </motion.div>

      {/* Dashboard preview */}
      <motion.div
        {...fadeUp(0.7, 24)}
        className="mt-[80px]"
      >
        <DashboardPreview />
      </motion.div>
    </section>
  );
}

// -- mini dashboard ------------------------------------------------------

function DashboardPreview() {
  return (
    <div
      className="rounded-xl p-[24px]"
      style={{
        background: "#0d0d10",
        border: "0.5px solid #1f1f1f",
        boxShadow: "0 0 80px rgba(167, 139, 250, 0.04)",
        minHeight: 480,
      }}
    >
      {/* mac-style window dots */}
      <div className="flex gap-1.5 pb-4">
        <span className="h-2.5 w-2.5 rounded-full bg-card" />
        <span className="h-2.5 w-2.5 rounded-full bg-card" />
        <span className="h-2.5 w-2.5 rounded-full bg-card" />
      </div>

      <div className="grid grid-cols-[220px_1fr] gap-5">
        {/* sidebar */}
        <div className="rounded-md border-[0.5px] border-border-subtle bg-sidebar p-4">
          <div className="mb-4 flex items-center gap-2 text-iris">
            <Logo size={14} />
            <span className="text-[12px] font-medium text-primary">
              LogGuard
            </span>
          </div>
          {["Dashboard", "Anomalies", "System", "Settings"].map((label, i) => (
            <div
              key={label}
              className={
                "rounded-sm px-2 py-1.5 text-[12px] " +
                (i === 0
                  ? "bg-card text-primary"
                  : "text-tertiary")
              }
            >
              {label}
            </div>
          ))}
        </div>

        {/* main */}
        <div className="space-y-4">
          {/* KPIs */}
          <div className="grid grid-cols-3 gap-3">
            {[
              { v: "142", l: "anomalies" },
              { v: "12", l: "critical" },
              { v: "0.91", l: "f1" },
            ].map((k) => (
              <div
                key={k.l}
                className="rounded-md border-[0.5px] border-border-subtle bg-card px-3 py-3"
              >
                <div className="text-[10px] uppercase tracking-wider text-tertiary">
                  {k.l}
                </div>
                <div className="mt-1 font-mono text-[28px] leading-none text-primary">
                  {k.v}
                </div>
              </div>
            ))}
          </div>

          {/* timeline chart — taller, more breathing room */}
          <div
            className="flex items-end gap-1 rounded-md border-[0.5px] border-border-subtle bg-card px-3 py-2"
            style={{ height: 90 }}
          >
            {[3, 6, 4, 8, 5, 9, 6, 7, 4, 6, 8, 5, 7, 9, 6, 4, 7, 5, 8, 6].map(
              (h, i) => (
                <span
                  key={i}
                  className="flex-1 rounded-sm"
                  style={{
                    height: `${h * 9}%`,
                    background:
                      i % 5 === 0
                        ? "var(--severity-critical)"
                        : i % 3 === 0
                        ? "var(--severity-warning)"
                        : "var(--severity-info)",
                  }}
                />
              ),
            )}
          </div>

          {/* feed rows */}
          <div className="divide-y-[0.5px] divide-border-subtle rounded-md border-[0.5px] border-border-subtle bg-card">
            {[
              {
                lvl: "critical",
                title: "ERROR keystone-api auth failed",
                meta: "nova-api-prod-3 · 2 min ago",
              },
              {
                lvl: "warning",
                title: "WARN rate limit exceeded 10.0.1.50",
                meta: "nova-api-prod-2 · 5 min ago",
              },
            ].map((r) => (
              <div
                key={r.title}
                className="flex items-start gap-3 px-3"
                style={{ paddingTop: 14, paddingBottom: 14 }}
              >
                <span
                  className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{
                    background:
                      r.lvl === "critical"
                        ? "var(--severity-critical)"
                        : "var(--severity-warning)",
                  }}
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-mono text-[13px] text-primary">
                    {r.title}
                  </div>
                  <div className="mt-0.5 truncate font-mono text-[11px] text-tertiary">
                    {r.meta}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
