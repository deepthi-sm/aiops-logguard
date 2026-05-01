import { motion } from "framer-motion";
import { AnimatedSection, containerVariants, itemVariants } from "./AnimatedSection";

const STEPS: { num: string; title: string; body: string; pills: string[] }[] = [
  {
    num: "01",
    title: "Ingest, parse, embed",
    body: "Logs flow into Redis Streams as a burst buffer. Drain3 extracts stable templates from messy log lines. SBERT embeddings turn each 20-event window into a dense vector, capturing meaning, not just keywords.",
    pills: ["Redis Streams", "Drain3", "Sentence-BERT"],
  },
  {
    num: "02",
    title: "Detect with a two-model ensemble",
    body: "A Transformer encoder learns sequential failure patterns and predicts how many minutes until impact. An AutoEncoder learns what normal looks like and flags reconstruction outliers. Their scores combine with a confidence filter, only signals the model is sure about become alerts.",
    pills: ["Transformer", "AutoEncoder", "PyTorch"],
  },
  {
    num: "03",
    title: "Explain with retrieval-augmented LLaMA",
    body: "A FAISS index of past incidents finds patterns similar to the new anomaly. Local LLaMA 3 8B, running on your hardware, reads the retrieved context and produces a root cause explanation plus a numbered fix, grounded in real prior incidents, not hallucinated.",
    pills: ["FAISS", "LLaMA 3", "Ollama"],
  },
  {
    num: "04",
    title: "Route, dedupe, learn",
    body: "Critical anomalies wake on-call via PagerDuty; warnings go to Slack; info-level events email the team. Engineer feedback feeds back into retraining, the system learns from the corrections it gets in production.",
    pills: ["PagerDuty", "Slack", "Drift detection"],
  },
];

export function HowItWorksSection() {
  return (
    <AnimatedSection
      id="how-it-works"
      direction="right"
      className="px-[56px] py-[96px]"
    >
      <div className="mx-auto max-w-[1100px]">
        <div className="text-[11px] uppercase tracking-[0.08em] text-tertiary">
          How it works
        </div>
        <h2 className="mt-3 max-w-[800px] font-display text-[40px] font-medium leading-[1.15] tracking-[-0.02em] text-primary">
          A pipeline that learns, predicts, and explains.
        </h2>

        <motion.ol
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, amount: 0.15 }}
          className="mt-12 space-y-14"
        >
          {STEPS.map((s) => (
            <motion.li
              key={s.num}
              variants={itemVariants}
              className="grid grid-cols-[60px_1fr] gap-7"
            >
              <div
                className="flex h-9 w-9 items-center justify-center rounded-lg font-display text-[14px] font-medium text-iris"
                style={{ border: "0.5px solid #2a2a2e" }}
              >
                {s.num}
              </div>
              <div>
                <h3 className="text-[18px] font-medium text-primary">
                  {s.title}
                </h3>
                <p className="mt-3 max-w-[600px] text-[14px] leading-[1.7] text-secondary">
                  {s.body}
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {s.pills.map((p) => (
                    <span
                      key={p}
                      className="rounded-full px-2.5 py-1 font-mono text-[11px] text-secondary"
                      style={{
                        background: "#16161a",
                        border: "0.5px solid #2a2a2e",
                      }}
                    >
                      {p}
                    </span>
                  ))}
                </div>
              </div>
            </motion.li>
          ))}
        </motion.ol>
      </div>
    </AnimatedSection>
  );
}
