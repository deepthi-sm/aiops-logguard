import { Link } from "react-router-dom";
import { AnimatedSection } from "./AnimatedSection";

export function CtaSection() {
  return (
    <AnimatedSection direction="up" className="px-[56px] pb-[64px] pt-[96px]">
      <div className="mx-auto max-w-[1100px]">
        <div
          className="rounded-2xl px-[56px] py-[80px] text-center"
          style={{
            background:
              "linear-gradient(135deg, rgba(167, 139, 250, 0.08) 0%, rgba(251, 113, 133, 0.04) 100%)",
            border: "0.5px solid #2a2a2e",
          }}
        >
          <span
            className="inline-flex items-center gap-2 rounded-full px-3.5 py-1.5"
            style={{
              background: "rgba(167, 139, 250, 0.1)",
              border: "0.5px solid rgba(167, 139, 250, 0.3)",
            }}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-iris" />
            <span className="text-[11px] uppercase tracking-[0.08em] text-iris">
              Free for self-hosted
            </span>
          </span>

          <h2 className="mt-7 font-display text-[48px] font-medium leading-[1.1] tracking-[-0.02em] text-primary">
            Stop reading logs. Start reading insights.
          </h2>
          <p className="mx-auto mt-5 max-w-[640px] text-[16px] leading-[1.6] text-secondary">
            LogGuard is open and free to self-host. Get started in under five
            minutes, no credit card, no email confirmation, no waiting.
          </p>

          <Link
            to="/signup"
            className="mt-9 inline-flex items-center rounded-lg bg-iris px-7 py-3.5 text-[14px] font-medium text-page transition-colors hover:bg-iris-deep"
          >
            Get started, it's free
          </Link>
        </div>
      </div>
    </AnimatedSection>
  );
}
