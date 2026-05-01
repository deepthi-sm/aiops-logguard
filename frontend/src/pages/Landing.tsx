import { CtaSection } from "../components/landing/CtaSection";
import { FeaturesSection } from "../components/landing/FeaturesSection";
import { HeroSection } from "../components/landing/HeroSection";
import { HowItWorksSection } from "../components/landing/HowItWorksSection";
import { LandingFooter } from "../components/landing/LandingFooter";
import { LandingHeader } from "../components/landing/LandingHeader";
import { ProblemSection } from "../components/landing/ProblemSection";
import { ResultsSection } from "../components/landing/ResultsSection";

/**
 * Public marketing landing page at `/`. Standalone — does not use the
 * dashboard Layout / Sidebar. Six scrollable sections with restrained
 * scroll-triggered animations and a sticky scroll-spy header.
 */
export function Landing() {
  return (
    <div className="min-h-screen bg-page text-primary">
      <LandingHeader />

      {/* Section backgrounds alternate to give visual separation. The
          inner sections handle their own padding; we just stack them. */}
      <main className="pt-[64px]">
        <HeroSection />
        <div style={{ background: "#0a0a0a" }}>
          <ProblemSection />
        </div>
        <div style={{ background: "#050505" }}>
          <HowItWorksSection />
        </div>
        <div style={{ background: "#0a0a0a" }}>
          <FeaturesSection />
        </div>
        <div style={{ background: "#050505" }}>
          <ResultsSection />
        </div>
        <div style={{ background: "#0a0a0a" }}>
          <CtaSection />
          <LandingFooter />
        </div>
      </main>
    </div>
  );
}
