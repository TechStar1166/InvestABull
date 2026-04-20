"use client";

import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { AlertTriangle } from "lucide-react";
import { streamResearch, type TraceEventPayload } from "../lib/api";
import {
  deriveStepStatuses,
  getErrorMessage,
  isTraceEvent,
  type HealthState,
} from "../lib/research";
import TickerInput from "../components/TickerInput";
import AgentProgress from "../components/AgentProgress";
import TraceLog from "../components/TraceLog";
import ReportViewer from "../components/ReportViewer";

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

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
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

        <TickerInput
          ticker={ticker}
          isStreaming={isStreaming}
          onTickerChange={setTicker}
          onSubmit={(event) => void onSubmit(event)}
        />

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
            <AgentProgress stepStatuses={stepStatuses} />
            <TraceLog
              showRawTrace={showRawTrace}
              traceEvents={traceEvents}
              onToggle={() => setShowRawTrace((value) => !value)}
            />
          </aside>

          <ReportViewer
            memo={memo}
            isStreaming={isStreaming}
            errorMessage={errorMessage}
          />
        </div>
      </div>
    </main>
  );
}