import { Check, Loader2, X } from "lucide-react";
import type { ReactNode } from "react";
import { useFeedback } from "../api/queries";
import { cn } from "../lib/cn";
import type { Feedback } from "../types";

/**
 * Two outline buttons in the AnomalyDetail header:
 *   ┌─ true positive ─┐   ┌─ false positive ─┐
 *
 * On click: POSTs `/api/v1/anomalies/{id}/feedback`, the clicked button
 * shows an inline spinner. After success we replace BOTH buttons with a
 * "Saved" confirmation — feedback is one-shot per page load (the user can
 * refresh to change their answer).
 */
export function FeedbackButtons({ anomalyId }: { anomalyId: string }) {
  const fb = useFeedback(anomalyId);

  if (fb.isSuccess) {
    return (
      <div className="inline-flex items-center gap-1.5 text-[12px] text-success">
        <Check size={14} strokeWidth={1.5} />
        Saved
      </div>
    );
  }
  if (fb.isError) {
    return (
      <div className="text-[12px] text-critical">
        Save failed — please try again.
      </div>
    );
  }

  const handle = (verdict: Feedback) => fb.mutate({ feedback: verdict });
  const pendingVerdict = fb.isPending ? fb.variables?.feedback : undefined;

  return (
    <div className="flex items-center gap-2">
      <OutlineButton
        onClick={() => handle("true_positive")}
        disabled={fb.isPending}
        intent="positive"
        loading={pendingVerdict === "true_positive"}
        icon={<Check size={12} strokeWidth={1.5} />}
      >
        true positive
      </OutlineButton>
      <OutlineButton
        onClick={() => handle("false_positive")}
        disabled={fb.isPending}
        intent="negative"
        loading={pendingVerdict === "false_positive"}
        icon={<X size={12} strokeWidth={1.5} />}
      >
        false positive
      </OutlineButton>
    </div>
  );
}

function OutlineButton({
  onClick,
  disabled,
  intent,
  loading,
  icon,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  intent: "positive" | "negative";
  loading: boolean;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border-[0.5px] px-3 py-1.5 text-[12px] transition-colors disabled:opacity-50",
        intent === "positive"
          ? "border-success/40 text-success hover:bg-success/10"
          : "border-anomaly/40 text-anomaly hover:bg-anomaly/10",
      )}
    >
      <span className="inline-flex items-center justify-center w-3 h-3">
        {loading ? (
          <Loader2 size={12} strokeWidth={1.5} className="animate-spin" />
        ) : (
          icon
        )}
      </span>
      {children}
    </button>
  );
}
