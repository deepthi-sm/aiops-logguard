import {
  Activity,
  AlignLeft,
  Cpu,
  FileText,
  LayoutDashboard,
  Link2,
  LogOut,
  MessageSquare,
  Settings as SettingsIcon,
  Upload,
  type LucideIcon,
} from "lucide-react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { cn } from "../lib/cn";
import { Logo } from "./Logo";
import { ThemeToggle } from "./ThemeToggle";

/**
 * Fixed 220px sidebar per spec.
 *
 *   ┌─────────────────────────┐
 *   │  ⬢ LogGuard             │  ← Logo
 *   │                         │
 *   │  ▢ Dashboard            │
 *   │  ▢ Anomalies        [3] │  ← user-facing routes
 *   │  ▢ Feedback             │
 *   │  ▢ Settings             │
 *   │  ─────────────────────  │  ← hairline divider
 *   │  ADMIN                  │  ← eyebrow label
 *   │  ▢ System               │  ← admin routes
 *   │  ▢ Training             │
 *   │  ▢ Incidents            │
 *   │                         │
 *   │  ─────────────────────  │  ← hairline divider
 *   │  ● connected  0/s    ☀  │  ← live status + theme toggle
 *   └─────────────────────────┘
 *
 * The status pill is static for now (event rate "0/s", "connected"
 * label, animated dot via CSS). Step 9 wires it to the real WebSocket
 * connection state and rolling event rate.
 */

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

const USER_ITEMS: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/anomalies", label: "Anomalies", icon: AlignLeft },
  { to: "/upload", label: "Upload", icon: Upload },
  { to: "/connect", label: "Connect", icon: Link2 },
  { to: "/feedback", label: "Feedback", icon: MessageSquare },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

const ADMIN_ITEMS: NavItem[] = [
  { to: "/admin/system", label: "System", icon: Activity },
  { to: "/admin/training", label: "Training", icon: Cpu },
  { to: "/admin/incidents", label: "Incidents", icon: FileText },
];

function NavItemLink({ item }: { item: NavItem }) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 rounded-md px-2.5 py-2 text-[12px] transition-colors",
          isActive
            ? "bg-card text-primary [&_svg]:text-iris"
            : "text-secondary [&_svg]:text-tertiary hover:bg-hover hover:text-primary",
        )
      }
    >
      <Icon size={14} strokeWidth={1.5} />
      <span>{item.label}</span>
    </NavLink>
  );
}

export function Sidebar() {
  const { signOut, user } = useAuth();
  const navigate = useNavigate();

  async function handleSignOut() {
    await signOut();
    navigate("/login", { replace: true });
  }

  return (
    <aside className="fixed left-0 top-0 z-10 flex h-full w-[220px] flex-col border-r-[0.5px] border-border-subtle bg-sidebar">
      {/* Brand — clickable, routes to /dashboard */}
      <Link
        to="/dashboard"
        className="flex items-center gap-2 px-5 pb-8 pt-6 text-iris transition-colors hover:text-iris-deep focus:outline-none focus-visible:rounded-md focus-visible:ring-1 focus-visible:ring-iris/40"
        aria-label="Go to dashboard"
      >
        <Logo size={20} />
        <span className="text-[15px] font-medium tracking-tight text-primary">
          LogGuard
        </span>
      </Link>

      {/* Nav */}
      <nav className="flex-1 px-3">
        <div className="space-y-px">
          {USER_ITEMS.map((item) => (
            <NavItemLink key={item.to} item={item} />
          ))}
        </div>

        {/* Admin group */}
        <div className="mt-3 border-t-[0.5px] border-border-subtle">
          <div className="px-2.5 pb-1.5 pt-[14px] text-[11px] uppercase tracking-[0.08em] text-tertiary">
            Admin
          </div>
          <div className="space-y-px">
            {ADMIN_ITEMS.map((item) => (
              <NavItemLink key={item.to} item={item} />
            ))}
          </div>
        </div>
      </nav>

      {/* Bottom: signed-in user, live status, theme toggle, sign out */}
      <div className="border-t-[0.5px] border-border-subtle px-3 pb-4 pt-3">
        {user && (
          <div className="mb-2 truncate px-2.5 py-1 text-[11px] text-tertiary">
            {user.displayName || user.email}
          </div>
        )}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 px-2.5 py-1.5 text-[11px] text-secondary">
            <span className="relative inline-flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-50" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-success" />
            </span>
            <span>connected</span>
            <span className="font-mono text-tertiary">0/s</span>
          </div>
          <ThemeToggle />
        </div>
        <button
          type="button"
          onClick={handleSignOut}
          className="mt-2 flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-[11px] text-tertiary transition-colors hover:bg-hover hover:text-primary"
        >
          <LogOut size={12} strokeWidth={1.5} />
          <span>Sign out</span>
        </button>
      </div>
    </aside>
  );
}