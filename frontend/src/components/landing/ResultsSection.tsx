import { motion } from "framer-motion";
import CountUp from "react-countup";
import { useInView } from "react-intersection-observer";
import { AnimatedSection, containerVariants, itemVariants } from "./AnimatedSection";

interface Kpi {
  value: number;
  decimals: number;
  suffix: string;
  prefix?: string;
  title: string;
  subtitle: string;
}

const KPIS: Kpi[] = [
  {
    value: 0.91,
    decimals: 2,
    suffix: "",
    title: "F1 score",
    subtitle: "held-out OpenStack test",
  },
  {
    value: 12,
    decimals: 0,
    suffix: "m",
    title: "avg early warning",
    subtitle: "before predicted failure",
  },
  {
    value: 87,
    decimals: 0,
    suffix: "%",
    title: "cache hit rate",
    subtitle: "on LLaMA explanations",
  },
  {
    value: 100,
    decimals: 0,
    suffix: "%",
    title: "on-prem inference",
    subtitle: "no third-party calls",
  },
];

const CROSS_DATASET: { left: string; right: string }[] = [
  { left: "OpenStack (held-out)", right: "0.91" },
  { left: "HDFS (held-out)", right: "0.89" },
  { left: "Apache (fully unseen)", right: "0.83" },
];

const BASELINES: { left: string; right: string; bold?: boolean }[] = [
  { left: "TF-IDF + Isolation Forest", right: "0.81" },
  { left: "DeepLog (reproduced)", right: "0.89" },
  { left: "LogGuard (ours)", right: "0.91", bold: true },
];

export function ResultsSection() {
  const { ref: triggerRef, inView } = useInView({
    threshold: 0.25,
    triggerOnce: true,
  });

  return (
    <AnimatedSection
      id="results"
      direction="right"
      className="px-[56px] py-[96px]"
    >
      <div className="mx-auto max-w-[1100px]" ref={triggerRef}>
        <div className="text-[11px] uppercase tracking-[0.08em] text-tertiary">
          Results
        </div>
        <h2 className="mt-3 max-w-[800px] font-display text-[40px] font-medium leading-[1.15] tracking-[-0.02em] text-primary">
          Numbers from a real evaluation.
        </h2>
        <p className="mt-5 max-w-[680px] text-[15px] leading-[1.65] text-secondary">
          Trained on OpenStack, evaluated on held-out OpenStack, HDFS, and a
          fully unseen Apache distribution. Reproducible on any machine with
          16GB RAM.
        </p>

        {/* KPI strip — hairline above + below */}
        <div className="mt-12 grid grid-cols-2 gap-x-9 gap-y-9 border-y-[0.5px] border-border-subtle py-9 md:grid-cols-4">
          {KPIS.map((k, i) => (
            <div key={k.title}>
              <div className="font-display text-[56px] font-medium leading-none tracking-[-0.03em] text-iris tabular-nums">
                {inView ? (
                  <CountUp
                    end={k.value}
                    decimals={k.decimals}
                    duration={1.5}
                    delay={i * 0.1}
                  />
                ) : (
                  (0).toFixed(k.decimals)
                )}
                {k.suffix && (
                  <span className="ml-0.5 text-[28px]">{k.suffix}</span>
                )}
              </div>
              <div className="mt-2 text-[12px] font-medium text-primary">
                {k.title}
              </div>
              <div className="mt-0.5 text-[11px] text-tertiary">
                {k.subtitle}
              </div>
            </div>
          ))}
        </div>

        {/* Comparison cards */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, amount: 0.15 }}
          className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-xl bg-border-subtle md:grid-cols-2"
        >
          <motion.div variants={itemVariants} className="bg-card p-7">
            <h3 className="text-[14px] font-medium text-primary">
              Cross-dataset generalization
            </h3>
            <div className="mt-5 divide-y-[0.5px] divide-border-subtle">
              {CROSS_DATASET.map((row) => (
                <div
                  key={row.left}
                  className="flex items-center justify-between py-2.5"
                >
                  <span className="text-[13px] text-tertiary">{row.left}</span>
                  <span className="font-mono text-[13px] text-iris tabular-nums">
                    {row.right}
                  </span>
                </div>
              ))}
            </div>
          </motion.div>

          <motion.div variants={itemVariants} className="bg-card p-7">
            <h3 className="text-[14px] font-medium text-primary">
              Beats prior baselines
            </h3>
            <div className="mt-5 divide-y-[0.5px] divide-border-subtle">
              {BASELINES.map((row) => (
                <div
                  key={row.left}
                  className="flex items-center justify-between py-2.5"
                >
                  <span
                    className={
                      row.bold
                        ? "text-[13px] font-medium text-iris"
                        : "text-[13px] text-tertiary"
                    }
                  >
                    {row.left}
                  </span>
                  <span
                    className={
                      row.bold
                        ? "font-mono text-[13px] font-medium text-iris tabular-nums"
                        : "font-mono text-[13px] text-tertiary tabular-nums"
                    }
                  >
                    {row.right}
                  </span>
                </div>
              ))}
            </div>
          </motion.div>
        </motion.div>
      </div>
    </AnimatedSection>
  );
}
