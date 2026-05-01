import { motion } from "framer-motion";
import { AnimatedSection, containerVariants, itemVariants } from "./AnimatedSection";

const CARDS: { number: string; numberColor: string; title: string; body: string }[] = [
  {
    number: "73%",
    numberColor: "text-critical",
    title: "of alerts are false positives",
    body: "On-call engineers spend most of their pages chasing alerts that never required action.",
  },
  {
    number: "34min",
    numberColor: "text-warning",
    title: "average time to root cause",
    body: "Even after the alert fires, finding the cause means manually grepping logs across multiple services.",
  },
  {
    number: "0%",
    numberColor: "text-info",
    title: "of failures predicted in advance",
    body: "Threshold-based systems react. They can't tell you a failure is 12 minutes away, they only know once it's happening.",
  },
];

export function ProblemSection() {
  return (
    <AnimatedSection
      id="problem"
      direction="left"
      className="px-[56px] py-[96px]"
      // Background tint via inline style — section background is darker
      // than the page to set off the cards.
    >
      <div className="mx-auto max-w-[1100px]" style={{ background: "transparent" }}>
        <div className="text-[11px] uppercase tracking-[0.08em] text-tertiary">
          The problem
        </div>
        <h2 className="mt-3 max-w-[800px] font-display text-[40px] font-medium leading-[1.15] tracking-[-0.02em] text-primary">
          Most alerts are noise. The few that matter get buried.
        </h2>
        <p className="mt-5 max-w-[680px] text-[15px] leading-[1.65] text-secondary">
          Threshold-based monitoring fires thousands of false alarms while
          quietly missing the failures it wasn't told to look for. By the time
          something breaks, the warning signs were already in the logs, nobody
          read them.
        </p>

        <motion.div
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, amount: 0.2 }}
          className="mt-12 grid grid-cols-1 gap-px bg-border-subtle md:grid-cols-3"
        >
          {CARDS.map((c) => (
            <motion.div
              key={c.title}
              variants={itemVariants}
              className="bg-page p-8"
            >
              <div
                className={`font-display text-[48px] font-medium leading-none tracking-[-0.02em] ${c.numberColor}`}
              >
                {c.number}
              </div>
              <div className="mt-3 text-[13px] font-medium text-primary">
                {c.title}
              </div>
              <p className="mt-2 text-[12px] leading-[1.6] text-tertiary">
                {c.body}
              </p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </AnimatedSection>
  );
}
