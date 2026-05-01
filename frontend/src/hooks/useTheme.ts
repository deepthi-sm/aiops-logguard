/**
 * Theme state — persisted to localStorage, applied to <html data-theme=...>.
 *
 * Per spec:
 *   - Toggles `data-theme="dark"` ↔ `data-theme="light"` on <html>
 *   - Persists choice to localStorage under `loguard-theme`
 *   - On first load, reads localStorage; if missing, defaults to dark
 */
import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";

const STORAGE_KEY = "loguard-theme";

function readInitialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "light" ? "light" : "dark";
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(readInitialTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // localStorage may be disabled (private browsing) — non-fatal.
    }
  }, [theme]);

  const toggle = useCallback(() => {
    setThemeState((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  return { theme, setTheme: setThemeState, toggle };
}
