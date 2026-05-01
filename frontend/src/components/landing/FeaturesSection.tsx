import { motion } from "framer-motion";
import {
  BookOpen,
  Filter,
  Lock,
  RefreshCw,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { Logo } from "../Logo";
import { AnimatedSection, containerVariants, itemVariants } from "./AnimatedSection";

interface Feature {
  title: string;
  body: string;
  Icon: LucideIcon | "logo";
}

const FEATURES: Feature[] = [
  {
    title: "Two-model ensemble",
    body: "Transformer for sequential patterns, AutoEncoder for distributional drift. They fail in different ways, together they cover both.",
    Icon: "logo",
  },
  {
    title: "Failure prediction",
    body: "The model doesn't just detect anomalies, it predicts how many minutes until impact. Time to act before things break.",
    Icon: Zap,
  },
  {
    title: "Confidence filtering",
    body: "A learned scorer suppresses borderline predictions. You only get pinged for signals the model is genuinely sure about.",
    Icon: Filter,
  },
  {
    title: "Explainable by design",
    body: "Every alert comes with attention-weighted log lines and a plain-English root cause. No more reverse-engineering opaque scores.",
    Icon: BookOpen,
  },
  {
    title: "100% on-premises",
    body: "Local LLaMA via Ollama. Your logs never leave your network. No third-party API calls, no compliance headaches.",
    Icon: Lock,
  },
  {
    title: "Human-in-the-loop",
    body: "Engineers mark alerts as true or false positives. Those labels feed the next retrain. The system gets sharper with use.",
    Icon: RefreshCw,
  },
];

export function FeaturesSection() {
  return (
    <AnimatedSection
      id="features"
      direction="left"
      className="px-[56px] py-[96px]"
    >
      <div className="mx-auto max-w-[1100px]">
        <div className="text-[11px] uppercase tracking-[0.08em] text-tertiary">
          Key features
        </div>
        <h2 className="mt-3 max-w-[800px] font-display text-[40px] font-medium leading-[1.15] tracking-[-0.02em] text-primary">
          Six things most AIOps tools don't do.
        </h2>

        <motion.div
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, amount: 0.15 }}
          className="mt-12 grid grid-cols-1 gap-px bg-border-subtle md:grid-cols-2 lg:grid-cols-3"
          style={{ borderRadius: 12, overflow: "hidden" }}
        >
          {FEATURES.map((f) => (
            <motion.div
              key={f.title}
              variants={itemVariants}
              className="px-[28px] py-[32px]"
              style={{ background: "#0d0d10" }}
            >
              <div className="text-iris">
                {f.Icon === "logo" ? (
                  <Logo size={20} />
                ) : (
                  <f.Icon size={20} strokeWidth={1.5} />
                )}
              </div>
              <h3 className="mt-4 text-[16px] font-medium text-primary">
                {f.title}
              </h3>
              <p className="mt-2 text-[13px] leading-[1.65] text-secondary">
                {f.body}
              </p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </AnimatedSection>
  );
}
