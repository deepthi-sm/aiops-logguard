import { Outlet } from "react-router-dom";
import { useWebSocket } from "../hooks/useWebSocket";
import { Sidebar } from "./Sidebar";

/**
 * Application shell — sidebar on the left, page content (Outlet) on the right.
 *
 * Mounts the live WebSocket connection here (one place, one socket). The
 * hook returns connection status + rolling events/sec, which we pass to
 * the Sidebar so the bottom status pill reflects reality.
 *
 * Padding: 22 px top, 26 px sides per spec. The sidebar is `position: fixed`
 * with width 220 px, so the main pane carries an equal left margin.
 */
export function Layout() {
  const { status, eventsPerSecond } = useWebSocket();

  return (
    <div className="min-h-screen bg-page text-primary">
      <Sidebar wsStatus={status} eventsPerSecond={eventsPerSecond} />
      <main className="ml-[220px] px-[26px] pt-[22px]">
        <Outlet />
      </main>
    </div>
  );
}
