/**
 * Step 1 deliverable per docs/architecture/frontend_design.md "Build order":
 *
 *   "Vite + React + TS + Tailwind + the design tokens in index.css.
 *    npm run dev works, page is blank but fonts load and the dark
 *    page-bg is visible."
 *
 * Intentionally minimal — no Layout, no Sidebar, no routes. Step 2 swaps
 * this for the real shell.
 */
export default function App() {
  return <div className="min-h-screen bg-page" />;
}
