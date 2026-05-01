/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Severity palette — referenced by SeverityBadge and elsewhere.
        critical: { 50: "#fef2f2", 500: "#ef4444", 700: "#b91c1c" },
        warning: { 50: "#fffbeb", 500: "#f59e0b", 700: "#b45309" },
        info: { 50: "#eff6ff", 500: "#3b82f6", 700: "#1d4ed8" },
        slate: {
          // dark-mode background ramp
          950: "#020617",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
