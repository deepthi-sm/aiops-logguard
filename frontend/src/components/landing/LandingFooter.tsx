import { Logo } from "../Logo";

export function LandingFooter() {
  return (
    <footer
      className="px-[56px]"
      style={{ background: "#0a0a0a" }}
    >
      <div
        className="mx-auto flex max-w-[1100px] items-center justify-between border-t-[0.5px] py-9"
        style={{ borderColor: "#1f1f1f" }}
      >
        <div className="flex items-center gap-2 text-iris">
          <Logo size={20} />
          <span className="text-[13px] text-secondary">LogGuard</span>
        </div>
        <nav className="flex items-center gap-5">
          {["Documentation", "GitHub", "Paper"].map((label) => (
            <a
              key={label}
              href="#"
              className="text-[12px] text-tertiary hover:text-secondary"
            >
              {label}
            </a>
          ))}
        </nav>
        <div className="font-mono text-[11px] text-muted">
          © 2026 · Research project
        </div>
      </div>
    </footer>
  );
}
