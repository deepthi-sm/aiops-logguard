import { cn } from "../lib/cn";

export type ServiceStatus = "online" | "degraded" | "offline";

export interface ServiceCardProps {
  name: string;
  status: ServiceStatus;
  detail: string;
}

const STATUS_DOT: Record<ServiceStatus, string> = {
  online: "bg-success",
  degraded: "bg-warning",
  offline: "bg-critical",
};

const STATUS_TEXT: Record<ServiceStatus, string> = {
  online: "text-success",
  degraded: "text-warning",
  offline: "text-critical",
};

/**
 * One service tile in the System page services grid. Card with the service
 * name on the left, a coloured-dot status pill on the right, and a single
 * line of mono technical detail (host:port / version / etc.) underneath.
 */
export function ServiceCard({ name, status, detail }: ServiceCardProps) {
  return (
    <div className="rounded-lg border-[0.5px] border-border-subtle bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-medium text-primary">{name}</span>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 text-[11px]",
            STATUS_TEXT[status],
          )}
        >
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              STATUS_DOT[status],
              status === "online" && "animate-pulse",
            )}
          />
          {status}
        </span>
      </div>
      <div className="mt-1.5 font-mono text-[11px] text-tertiary">{detail}</div>
    </div>
  );
}
