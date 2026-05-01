import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Logo } from "../Logo";

/**
 * Sticky header for the landing page. Backdrop-blur, hairline border
 * below. Scroll-spy keeps one nav link "active" depending on which
 * section the user is currently looking at, computed from
 * IntersectionObserver intersection ratios.
 */

const SECTIONS: { id: string; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "problem", label: "Problem" },
  { id: "how-it-works", label: "How it works" },
  { id: "features", label: "Features" },
  { id: "results", label: "Results" },
];

export function LandingHeader() {
  const [activeId, setActiveId] = useState<string>("overview");

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        // Pick the entry with the highest intersection ratio that's
        // currently visible. Falls through to the last picked id.
        let bestId = activeId;
        let bestRatio = 0;
        for (const e of entries) {
          if (e.isIntersecting && e.intersectionRatio > bestRatio) {
            bestRatio = e.intersectionRatio;
            bestId = e.target.id;
          }
        }
        if (bestRatio > 0) setActiveId(bestId);
      },
      // Sample at multiple thresholds so we catch the "current" section
      // even when two sections are partially in view simultaneously.
      { threshold: [0.15, 0.3, 0.5, 0.75] },
    );
    for (const s of SECTIONS) {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
    // We only want to set up once; activeId in deps would re-run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function scrollTo(id: string) {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <header
      className="fixed left-0 right-0 top-0 z-30 border-b-[0.5px] border-border-subtle px-[56px] py-4"
      style={{
        background: "rgba(10,10,10,0.85)",
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
      }}
    >
      <div className="mx-auto flex max-w-[1100px] items-center justify-between">
        <button
          type="button"
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
          className="flex items-center gap-2 text-iris"
        >
          <Logo size={22} />
          <span className="text-[14px] font-medium tracking-tight text-primary">
            LogGuard
          </span>
        </button>

        <nav className="hidden items-center gap-7 md:flex">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => scrollTo(s.id)}
              className={
                "text-[12px] transition-colors " +
                (activeId === s.id
                  ? "text-primary"
                  : "text-tertiary hover:text-secondary")
              }
            >
              {s.label}
            </button>
          ))}
        </nav>

        <div className="flex items-center gap-4">
          <Link
            to="/login"
            className="text-[12px] text-secondary hover:text-primary"
          >
            Sign in
          </Link>
          <Link
            to="/signup"
            className="rounded-md bg-iris px-4 py-1.5 text-[12px] font-medium text-page transition-colors hover:bg-iris-deep"
          >
            Get started
          </Link>
        </div>
      </div>
    </header>
  );
}
