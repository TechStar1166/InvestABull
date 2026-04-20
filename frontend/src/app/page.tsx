"use client";

import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  Loader2,
  Sparkles,
  Terminal,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import {
  ApiError,
  streamResearch,
  type TraceEventPayload,
} from "../lib/api";

type HealthState = "checking" | "online" | "offline";
type StepKey = "price" | "news" | "macro" | "filings" | "coordinator";
type StepStatus = "pending" | "active" | "done";

const STEP_ORDER: { key: StepKey; label: string }[] = [
  { key: "price", label: "Price" },
  { key: "news", label: "News" },
  { key: "macro", label: "Macro" },
  { key: "filings", label: "Filings" },
  { key: "coordinator", label: "Coordinator" },
];

function isTraceEvent(data: unknown): data is TraceEventPayload {
  return (
    typeof data === "object" &&
    data !== null &&
    "status" in data &&
    typeof (data as TraceEventPayload).status === "string"
  );
}

function specialistKeyFromEvent(e: TraceEventPayload): StepKey | null {
  const spec = e.meta?.specialist;
  if (spec === "Price") return "price";
  if (spec === "News") return "news";
  if (spec === "Macro") return "macro";
  if (spec === "Filings") return "filings";
  const agent = e.agent ?? "";
  if (agent.includes("Price")) return "price";
  if (agent.includes("News")) return "news";
  if (agent.includes("Macro")) return "macro";
  if (agent.includes("Filings")) return "filings";
  if (agent.includes("Coordinator")) return "coordinator";
  return null;
}

function deriveStepStatuses(events: TraceEventPayload[], isStreaming: boolean): Record<StepKey, StepStatus> {
  const done = new Set<StepKey>();
  let fanout = false;

  for (const e of events) {
    const st = e.status ?? "";
    if (st.includes("Fanning out")) fanout = true;
    const sk = specialistKeyFromEvent(e);
    if (sk && st.includes("Complete")) done.add(sk);
    if (st === "Memo Ready") {
      for (const { key } of STEP_ORDER) done.add(key);
    }
  }

  const result: Record<StepKey, StepStatus> = {
    price: "pending",
    news: "pending",
    macro: "pending",
    filings: "pending",
    coordinator: "pending",
  };

  const order: StepKey[] = ["price", "news", "macro", "filings", "coordinator"];
  for (const k of order) {
    if (done.has(k)) result[k] = "done";
  }

  if (isStreaming && fanout) {
    const firstPending = order.find((k) => !done.has(k));
    if (firstPending) result[firstPending] = "active";
  }

  return result;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) return "Ticker Not Found. Please check the symbol and try again.";
    if (error.status === 408) return "Research request timed out. Please retry in a moment.";
    if (error.status === 500 || error.status === 502 || error.status === 503) {
      return "Research Pipeline Interrupted. Please retry after a short wait.";
    }
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Research Pipeline Interrupted. Please retry.";
}

export default function Home() {
  const [ticker, setTicker] = useState("AAPL");
  const [traceEvents, setTraceEvents] = useState<TraceEventPayload[]>([]);
  const [memo, setMemo] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [health, setHealth] = useState<HealthState>(() =>
    process.env.NEXT_PUBLIC_API_URL ? "checking" : "offline"
  );
  const [errorMessage, setErrorMessage] = useState("");
  const [showRawTrace, setShowRawTrace] = useState(false);

  const stepStatuses = useMemo(
    () => deriveStepStatuses(traceEvents, isStreaming),
    [traceEvents, isStreaming]
  );

  async function checkApiHealth(manual = false) {
    const baseUrl = process.env.NEXT_PUBLIC_API_URL;
    if (!baseUrl) {
      setHealth("offline");
      return;
    }

    if (manual) setHealth("checking");
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 4500);

    try {
      const response = await fetch(`${baseUrl.replace(/\/$/, "")}/openapi.json`, {
        method: "GET",
        cache: "no-store",
        signal: controller.signal,
      });
      setHealth(response.ok ? "online" : "offline");
    } catch {
      setHealth("offline");
    } finally {
      window.clearTimeout(timer);
    }
  }

  useEffect(() => {
    const id = window.setTimeout(() => {
      void checkApiHealth(false);
    }, 0);
    return () => window.clearTimeout(id);
  }, []);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setIsStreaming(true);
    setErrorMessage("");
    setMemo("");
    setTraceEvents([]);

    await streamResearch(
      ticker,
      (data) => {
        if (!isTraceEvent(data)) return;
        setTraceEvents((prev) => [...prev, data]);
        if (data.status === "Memo Ready" && data.meta && typeof data.meta.memo === "string") {
          setMemo(data.meta.memo);
        }
      },
      () => {
        setIsStreaming(false);
      },
      (err) => {
        setIsStreaming(false);
        setErrorMessage(getErrorMessage(err));
      }
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto flex min-h-screen max-w-[1600px] flex-col px-4 py-8 md:px-8 md:py-10">
        <header className="mb-6 shrink-0 border-b border-slate-800 pb-6">
          <p className="mb-1 text-xs uppercase tracking-[0.26em] text-slate-500">
            InvestABull Research Terminal
          </p>
          <h1 className="text-2xl font-semibold tracking-tight text-white md:text-3xl">
            Live streaming equity research
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-400">
            Specialists stream over SSE; the coordinator memo renders as it completes.
          </p>
          <div className="mt-4 inline-flex items-center gap-2 rounded-full border border-slate-800 bg-slate-900/90 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            <span
              className={clsx("inline-block h-2 w-2 rounded-full", {
                "bg-amber-400": health === "checking",
                "bg-emerald-400": health === "online",
                "bg-rose-400": health === "offline",
              })}
            />
            {health === "checking" && "API: Checking"}
            {health === "online" && "API: Connected"}
            {health === "offline" && "API: Unreachable"}
            <button
              type="button"
              onClick={() => void checkApiHealth(true)}
              className="ml-1 rounded-full border border-slate-700 px-2 py-0.5 text-[10px] tracking-[0.12em] text-slate-300 hover:border-slate-500 hover:text-white"
            >
              Retry
            </button>
          </div>
        </header>

        <form
          className="mb-6 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center"
          onSubmit={(e) => void onSubmit(e)}
        >
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="Ticker (e.g. AAPL)"
            disabled={isStreaming}
            className="h-11 w-full rounded-lg border border-slate-800 bg-slate-900 px-4 text-sm font-medium tracking-wide text-white outline-none ring-emerald-500/0 transition focus:border-emerald-500/50 focus:ring-2 focus:ring-emerald-500/30 disabled:opacity-50 sm:max-w-xs"
          />
          <button
            type="submit"
            disabled={isStreaming}
            className={clsx(
              "inline-flex h-11 items-center justify-center gap-2 rounded-lg px-6 text-sm font-semibold transition",
              isStreaming
                ? "cursor-not-allowed bg-slate-800 text-slate-500"
                : "bg-emerald-500 text-slate-950 hover:bg-emerald-400"
            )}
          >
            {isStreaming ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Generating…
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                Generate Research
              </>
            )}
          </button>
        </form>

        {errorMessage && (
          <div className="mb-6 rounded-xl border border-amber-900/50 bg-amber-950/30 px-4 py-3 text-sm text-amber-100">
            <p className="flex items-center gap-2 font-medium">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              {errorMessage}
            </p>
          </div>
        )}

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[minmax(260px,320px)_1fr] lg:gap-8">
          <aside className="flex flex-col rounded-xl border border-slate-800 bg-slate-900/50 lg:min-h-[480px]">
            <div className="border-b border-slate-800 px-4 py-3">
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
                <Activity className="h-3.5 w-3.5" />
                Trace
              </p>
            </div>
            <div className="flex flex-1 flex-col gap-1 p-3">
              {STEP_ORDER.map(({ key, label }) => {
                const s = stepStatuses[key];
                return (
                  <div
                    key={key}
                    className="flex items-center gap-3 rounded-lg border border-slate-800/80 bg-slate-950/60 px-3 py-2.5"
                  >
                    {s === "done" && (
                      <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-400" aria-hidden />
                    )}
                    {s === "active" && (
                      <Loader2 className="h-5 w-5 shrink-0 animate-spin text-emerald-400" aria-hidden />
                    )}
                    {s === "pending" && (
                      <Circle className="h-5 w-5 shrink-0 text-slate-600" aria-hidden />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-slate-200">{label}</p>
                      <p className="truncate text-xs text-slate-500">
                        {s === "done" && "Complete"}
                        {s === "active" && "In progress…"}
                        {s === "pending" && "Waiting"}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="border-t border-slate-800 p-3">
              <button
                type="button"
                onClick={() => setShowRawTrace((v) => !v)}
                className="flex w-full items-center justify-between text-left text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 hover:text-slate-400"
              >
                <span className="flex items-center gap-2">
                  <Terminal className="h-3.5 w-3.5" />
                  Raw events
                </span>
                {showRawTrace ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </button>
              {showRawTrace && (
                <ul className="mt-2 max-h-48 space-y-2 overflow-y-auto text-[11px] text-slate-500">
                  {traceEvents.length === 0 ? (
                    <li className="text-slate-600">No events yet.</li>
                  ) : (
                    traceEvents.map((e, i) => (
                      <li key={`${e.id ?? i}-${i}`} className="rounded border border-slate-800/80 bg-slate-950/80 p-2">
                        <span className="text-slate-400">{e.agent}</span> · {e.status}
                      </li>
                    ))
                  )}
                </ul>
              )}
            </div>
          </aside>

          <section className="flex min-h-[420px] flex-col rounded-xl border border-slate-800 bg-slate-900/40">
            <div className="border-b border-slate-800 px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
                Investment memo
              </p>
            </div>
            <div className="relative flex-1 overflow-y-auto p-4 md:p-6">
              {!memo && isStreaming && (
                <div className="space-y-4 animate-pulse">
                  <div className="h-4 w-2/3 rounded bg-slate-800" />
                  <div className="h-4 w-full rounded bg-slate-800/80" />
                  <div className="h-4 w-5/6 rounded bg-slate-800/60" />
                  <div className="h-32 w-full rounded-lg bg-slate-800/40" />
                </div>
              )}
              {!memo && !isStreaming && !errorMessage && (
                <div className="flex h-full min-h-[280px] flex-col items-center justify-center text-center text-slate-500">
                  <Sparkles className="mb-3 h-10 w-10 text-slate-700" />
                  <p className="text-sm font-medium text-slate-400">Ready to stream</p>
                  <p className="mt-1 max-w-sm text-xs text-slate-600">
                    Enter a ticker and run Generate Research to see the live pipeline and memo.
                  </p>
                </div>
              )}
              {memo && (
                <article className="memo-dark max-w-none">
                  <ReactMarkdown>{memo}</ReactMarkdown>
                </article>
              )}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
