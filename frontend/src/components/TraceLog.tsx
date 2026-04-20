import { useEffect, useRef } from "react";
import { ChevronDown, ChevronUp, Terminal } from "lucide-react";
import type { TraceEventPayload } from "../lib/api";

type TraceLogProps = {
  showRawTrace: boolean;
  traceEvents: TraceEventPayload[];
  onToggle: () => void;
};

export default function TraceLog({
  showRawTrace,
  traceEvents,
  onToggle,
}: TraceLogProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [traceEvents]);

  return (
    <div className="border-t border-slate-800 p-3">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between text-left text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 hover:text-slate-400"
      >
        <span className="flex items-center gap-2">
          <Terminal className="h-3.5 w-3.5" />
          Raw events
        </span>
        {showRawTrace ? (
          <ChevronUp className="h-4 w-4" />
        ) : (
          <ChevronDown className="h-4 w-4" />
        )}
      </button>

      {showRawTrace && (
        <ul className="mt-2 max-h-64 space-y-2 overflow-y-auto rounded-lg border border-slate-800/80 bg-slate-950/60 p-2 text-[11px] text-slate-500">
          {traceEvents.length === 0 ? (
            <li className="rounded border border-slate-800/80 bg-black/40 p-2 text-slate-600">
              No events yet.
            </li>
          ) : (
            traceEvents.map((event, index) => {
              const agent = event.agent?.toUpperCase() ?? "SYSTEM";

              const color = agent.includes("PRICE")
                ? "text-blue-400"
                : agent.includes("NEWS")
                  ? "text-yellow-400"
                  : agent.includes("MACRO")
                    ? "text-purple-400"
                    : agent.includes("FILINGS")
                      ? "text-pink-400"
                      : agent.includes("COORDINATOR")
                        ? "text-emerald-400"
                        : "text-slate-400";

              const time = new Date().toLocaleTimeString();

              return (
                <li
                  key={`${event.id ?? index}-${index}`}
                  className="rounded border border-slate-800/80 bg-black/80 p-2 font-mono text-[11px]"
                >
                  <span className="mr-2 text-slate-500">{time}</span>
                  <span className={color}>[{agent}]</span>{" "}
                  <span className="text-slate-300">{event.status}</span>
                </li>
              );
            })
          )}
          <div ref={bottomRef} />
        </ul>
      )}
    </div>
  );
}