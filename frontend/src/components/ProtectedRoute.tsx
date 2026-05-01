import { type ReactElement } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { Logo } from "./Logo";

/**
 * Wrap protected pages with this. While Firebase is determining the
 * initial auth state we show a centered logo spinner. If the user is
 * unauthenticated we redirect to /login, preserving the path they
 * tried to reach so post-login can send them back.
 */
export function ProtectedRoute({ children }: { children: ReactElement }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-page">
        <div className="flex flex-col items-center gap-3 text-iris">
          <span className="animate-pulse">
            <Logo size={28} />
          </span>
          <span className="text-[11px] uppercase tracking-[0.08em] text-tertiary">
            Loading
          </span>
        </div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return children;
}
