import { type ReactElement } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { Logo } from "./Logo";

/**
 * Wrap pages that only make sense for signed-out visitors (e.g. /login,
 * /signup). Signed-in users get bounced to /dashboard.
 */
export function PublicOnlyRoute({ children }: { children: ReactElement }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-page">
        <div className="flex flex-col items-center gap-3 text-iris">
          <span className="animate-pulse">
            <Logo size={28} />
          </span>
        </div>
      </div>
    );
  }

  if (user) {
    return <Navigate to="/dashboard" replace />;
  }
  return children;
}
