import type { Config } from "tailwindcss";

// All colors and text colors are CSS variables defined in src/index.css.
// Switching `<html data-theme="dark">` ↔ `<html data-theme="light">` swaps
// every variable atomically — no component-level branching needed.
export default {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
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
