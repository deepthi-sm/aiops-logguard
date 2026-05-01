import type { Config } from "tailwindcss";

// All colors and text colors are CSS variables defined in src/index.css.
// Switching `<html data-theme="dark">` ↔ `<html data-theme="light">` swaps
// every variable atomically — no component-level branching needed.
export default {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  // Safelist severity classes — they're constructed at runtime from the
  // `severity` field of an anomaly, so Tailwind's content scanner needs
  // help to keep them in the bundle. Without this, `bg-info` / `text-info`
  // can get tree-shaken if no static reference exists.
  safelist: [
    "bg-critical", "bg-warning", "bg-info", "bg-success",
    "text-critical", "text-warning", "text-info", "text-success",
    "bg-critical/10", "bg-warning/10", "bg-info/10", "bg-success/10",
    "border-critical", "border-warning", "border-info", "border-success",
    "border-critical/30", "border-warning/30", "border-info/30",
    "border-critical/40", "border-warning/40", "border-info/40",
  ],
  theme: {
    extend: {
      colors: {
        iris: "var(--iris)",
        "iris-deep": "var(--iris-deep)",
        anomaly: "var(--anomaly)",
        "anomaly-deep": "var(--anomaly-deep)",
        critical: "var(--severity-critical)",
        warning: "var(--severity-warning)",
        info: "var(--severity-info)",
        success: "var(--severity-success)",
        page: "var(--bg-page)",
        sidebar: "var(--bg-sidebar)",
        card: "var(--bg-card)",
        hover: "var(--bg-hover)",
        "border-subtle": "var(--border-subtle)",
        "border-default": "var(--border-default)",
      },
      textColor: {
        primary: "var(--text-primary)",
        secondary: "var(--text-secondary)",
        tertiary: "var(--text-tertiary)",
        muted: "var(--text-muted)",
      },
      fontFamily: {
        // Inter Display falls back to Inter — Google Fonts doesn't host the
        // Display variant, so we ship Inter and the chain handles it.
        sans: ["Inter", "system-ui", "sans-serif"],
        display: ["Inter Display", "Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
