import { Moon, Sun } from "lucide-react";
import { useTheme } from "../hooks/useTheme";

/**
 * Bottom-right of the sidebar. Icon-only button — sun when in dark mode
 * (clicking goes to light), moon when in light mode (clicking goes to dark).
 */
export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const Icon = theme === "dark" ? Sun : Moon;
  const next = theme === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-secondary transition-colors hover:bg-hover hover:text-primary"
    >
      <Icon size={14} strokeWidth={1.5} />
    </button>
  );
}
