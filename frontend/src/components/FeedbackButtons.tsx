import { useFeedback } from "../hooks/queries";
import { classes } from "../lib/format";

export function FeedbackButtons({ anomalyId }: { anomalyId: string }) {
  const fb = useFeedback(anomalyId);

  if (fb.isSuccess) {
    return (
      <div className="rounded border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-400">
        Thanks — feedback recorded.
      </div>
    );
  }
  if (fb.isError) {
    return (
      <div className="rounded border border-critical-500/40 bg-critical-500/10 px-3 py-2 text-xs text-critical-500">
        Feedback failed: {(fb.error as Error).message}
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-slate-400">Was this a real anomaly?</span>
      <Button
        onClick={() => fb.mutate({ feedback: "true_positive" })}
        disabled={fb.isPending}
        intent="positive"
      >
        Yes, real
      </Button>
      <Button
        onClick={() => fb.mutate({ feedback: "false_positive" })}
        disabled={fb.isPending}
        intent="negative"
      >
        No, false positive
      </Button>
    </div>
  );
}

function Button(props: {
  onClick: () => void;
  disabled?: boolean;
  intent: "positive" | "negative";
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={props.onClick}
      disabled={props.disabled}
      className={classes(
        "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50",
        props.intent === "positive"
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20"
          : "border-slate-700 bg-slate-800/50 text-slate-300 hover:bg-slate-700",
      )}
    >
      {props.children}
    </button>
  );
}
