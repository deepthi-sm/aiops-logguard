import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";

/**
 * Application shell — sidebar on the left, page content (Outlet) on the right.
 *
 * Padding: 22px top, 26px sides per spec. The sidebar is `position: fixed`
 * with width 220px, so the main pane carries an equal left margin.
 */
export function Layout() {
  return (
    <div className="min-h-screen bg-page text-primary">
      <Sidebar />
      <main className="ml-[220px] px-[26px] pt-[22px]">
        <Outlet />
      </main>
    </div>
  );
}
