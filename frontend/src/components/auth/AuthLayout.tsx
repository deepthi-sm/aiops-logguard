import type { ReactNode } from "react";
import { AuthLeftPane } from "./AuthLeftPane";

/**
 * Two-pane shell shared by /login and /signup. Left pane: marketing
 * copy + brand stats. Right pane: the form (children). Hairline divider
 * down the middle. Full-height single screen, no scroll on desktop.
 */
export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-screen w-full grid-cols-1 bg-page md:grid-cols-2">
      <div className="hidden border-r-[0.5px] border-border-subtle md:block">
        <AuthLeftPane />
      </div>
      <main className="flex items-center justify-center px-[56px] py-[60px]">
        {children}
      </main>
    </div>
  );
}
