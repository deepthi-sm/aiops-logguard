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
      {/* Pill */}
      <motion.div {...fadeUp(0.1, 8)}>
        <span
          className="inline-flex items-center gap-2 rounded-full px-3.5 py-1.5"
          style={{
            background: "rgba(167, 139, 250, 0.1)",
            border: "0.5px solid rgba(167, 139, 250, 0.3)",
          }}
        >
          <span className="h-1.5 w-1.5 rounded-full bg-iris" />
          <span className="text-[11px] uppercase tracking-[0.08em] text-iris">
            Research project · 2026
          </span>
        </span>
      </motion.div>

      {/* Headline */}
      <motion.h1
        {...fadeUp(0.2)}
        className="mt-6 max-w-[850px] font-display text-[64px] font-medium leading-[1.05] tracking-[-0.03em] text-primary"
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
      className="rounded-xl p-[18px]"
      style={{
        background: "#0d0d10",
        border: "0.5px solid #1f1f1f",
        boxShadow: "0 0 80px rgba(167, 139, 250, 0.04)",
      }}
    >
      {/* mac-style window dots */}
      <div className="flex gap-1.5 pb-3">
        <span className="h-2.5 w-2.5 rounded-full bg-card" />
        <span className="h-2.5 w-2.5 rounded-full bg-card" />
        <span className="h-2.5 w-2.5 rounded-full bg-card" />
      </div>

      <div className="grid grid-cols-[140px_1fr] gap-3">
        {/* sidebar */}
        <div className="rounded-md border-[0.5px] border-border-subtle bg-sidebar p-3">
          <div className="mb-3 flex items-center gap-1.5 text-iris">
            <Logo size={12} />
            <span className="text-[10px] font-medium text-primary">
              LogGuard
            </span>
          </div>
          {["Dashboard", "Anomalies", "System", "Settings"].map((label) => (
            <div
              key={label}
              className="px-1 py-1 text-[10px] text-tertiary"
            >
              {label}
            </div>
          ))}
        </div>

        {/* main */}
        <div className="space-y-3">
          {/* KPIs */}
          <div className="grid grid-cols-3 gap-3">
            {[
              { v: "142", l: "anomalies" },
              { v: "12", l: "critical" },
              { v: "0.91", l: "f1" },
            ].map((k) => (
              <div
                key={k.l}
                className="rounded-md border-[0.5px] border-border-subtle bg-card p-2"
              >
                <div className="font-mono text-[14px] text-primary">{k.v}</div>
                <div className="text-[9px] uppercase tracking-wider text-tertiary">
                  {k.l}
                </div>
              </div>
            ))}
          </div>

          {/* tiny chart */}
          <div className="flex h-12 items-end gap-1 rounded-md border-[0.5px] border-border-subtle bg-card px-2 py-1.5">
            {[3, 6, 4, 8, 5, 9, 6, 7, 4, 6, 8, 5, 7, 9, 6].map((h, i) => (
              <span
                key={i}
                className="flex-1 rounded-sm"
                style={{
                  height: `${h * 8}%`,
                  background:
                    i % 5 === 0
                      ? "var(--severity-critical)"
                      : i % 3 === 0
                      ? "var(--severity-warning)"
                      : "var(--severity-info)",
                }}
              />
            ))}
          </div>

          {/* feed rows */}
          <div className="space-y-1">
            {[
              { lvl: "critical", text: "ERROR keystone-api auth failed" },
              { lvl: "warning", text: "WARN rate limit exceeded 10.0.1.50" },
            ].map((r) => (
              <div
                key={r.text}
                className="flex items-center gap-2 rounded-md border-[0.5px] border-border-subtle bg-card px-2 py-1.5"
              >
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{
                    background:
                      r.lvl === "critical"
                        ? "var(--severity-critical)"
                        : "var(--severity-warning)",
                  }}
                />
                <span className="truncate font-mono text-[10px] text-secondary">
                  {r.text}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
