import clsx from "clsx";
import { Activity, CheckCircle2, Circle, Loader2 } from "lucide-react";
import { STEP_ORDER, type StepKey, type StepStatus } from "../lib/research";

type AgentProgressProps = {
  stepStatuses: Record<StepKey, StepStatus>;
};

export default function AgentProgress({ stepStatuses }: AgentProgressProps) {
  return (
    <div className="border-b border-slate-800">
      <div className="px-4 py-3">
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
          <Activity className="h-3.5 w-3.5" />
          Trace
        </p>
      </div>

      <div className="flex flex-1 flex-col p-3">
        {STEP_ORDER.map(({ key, label }, index) => {
          const status = stepStatuses[key];

          return (
            <div key={key}>
              <div
                className={clsx(
                  "flex items-center gap-3 rounded-lg border px-3 py-2.5 transition-all",
                  status === "done" &&
                    "border-emerald-500/30 bg-emerald-500/5",
                  status === "active" &&
                    "border-emerald-400 bg-emerald-500/10 shadow-[0_0_16px_rgba(16,185,129,0.35)] animate-pulse",
                  status === "pending" &&
                    "border-slate-800/80 bg-slate-950/60"
                )}
              >
                {status === "done" && (
                  <CheckCircle2
                    className="h-5 w-5 shrink-0 text-emerald-400"
                    aria-hidden
                  />
                )}

                {status === "active" && (
                  <Loader2
                    className="h-5 w-5 shrink-0 animate-spin text-emerald-400"
                    aria-hidden
                  />
                )}

                {status === "pending" && (
                  <Circle
                    className="h-5 w-5 shrink-0 text-slate-600"
                    aria-hidden
                  />
                )}

                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-200">{label}</p>
                  <p className="truncate text-xs text-slate-500">
                    {status === "done" && "Complete"}
                    {status === "active" && "In progress…"}
                    {status === "pending" && "Waiting"}
                  </p>
                </div>

                <span
                  className={clsx(
                    "ml-auto text-xs font-semibold tracking-wide",
                    status === "done" && "text-emerald-400",
                    status === "active" && "text-emerald-300",
                    status === "pending" && "text-slate-500"
                  )}
                >
                  {status.toUpperCase()}
                </span>
              </div>

              {index < STEP_ORDER.length - 1 && (
                <div className="ml-6 h-4 w-px bg-slate-700" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}