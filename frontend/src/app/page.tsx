"use client";

import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { AlertTriangle, ChevronDown, ChevronUp, Loader2, Terminal } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { ApiError, fetchResearch, type TraceLog } from "../lib/api";

type UiState = "idle" | "loading" | "success" | "error";
type HealthState = "checking" | "online" | "offline";

const loadingStages = [
  "Analyzing Market Data...",
  "Gathering Relevant Headlines...",
  "Cross-Checking Financial Signals...",
  "Synthesizing Investment Thesis...",
  "Finalizing Institutional Memo...",
];

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) return "Ticker Not Found. Please check the symbol and try again.";
    if (error.status === 408) return "Research request timed out. Please retry in a moment.";
    if (error.status === 500 || error.status === 502 || error.status === 503) {
      return "Research Pipeline Interrupted. Please retry after a short wait.";
    }
    return error.message;
  }
  return "Research Pipeline Interrupted. Please retry.";
}

export default function Home() {
  const [ticker, setTicker] = useState("AAPL");
  const [memo, setMemo] = useState("");
  const [traceLogs, setTraceLogs] = useState<TraceLog[]>([]);
  const [status, setStatus] = useState<UiState>("idle");
  const [health, setHealth] = useState<HealthState>(() =>
    process.env.NEXT_PUBLIC_API_URL ? "checking" : "offline"
  );
  const [errorMessage, setErrorMessage] = useState("");
  const [showTrace, setShowTrace] = useState(false);
  const [stageIndex, setStageIndex] = useState(0);

  const stageLabel = useMemo(() => loadingStages[stageIndex] ?? loadingStages[0], [stageIndex]);

  async function checkApiHealth(manual = false) {
    const baseUrl = process.env.NEXT_PUBLIC_API_URL;
    if (!baseUrl) {
      setHealth("offline");
      return;
    }

    if (manual) {
      setHealth("checking");
    }
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
    return () => {
      window.clearTimeout(id);
    };
  }, []);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setStatus("loading");
    setErrorMessage("");
    setMemo("");
    setTraceLogs([]);
    setShowTrace(false);
    setStageIndex(0);

    const stageTicker = window.setInterval(() => {
      setStageIndex((prev) => (prev + 1) % loadingStages.length);
    }, 4500);

    try {
      const data = await fetchResearch(ticker);
      setMemo(data.memo || "");
      setTraceLogs(data.trace_logs || []);
      setStatus("success");
    } catch (error) {
      setStatus("error");
      setErrorMessage(getErrorMessage(error));
    } finally {
      window.clearInterval(stageTicker);
    }
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto w-full max-w-6xl px-6 py-10 md:px-10 md:py-14">
        <header className="mb-8 border-b border-slate-800 pb-6 md:mb-10">
          <p className="mb-2 text-xs uppercase tracking-[0.26em] text-slate-400">InvestABull Research Terminal</p>
          <h1 className="text-3xl font-semibold tracking-tight text-white md:text-4xl">Multi-Agent Equity Intelligence</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-300 md:text-base">
            Run institutional-style research with Gemini retrieval agents and Claude synthesis.
          </p>
          <div className="mt-4 inline-flex items-center gap-2 rounded-full border border-slate-700 bg-slate-900/80 px-3 py-1 text-xs font-semibold uppercase tracking-wide">
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
              onClick={() => {
                void checkApiHealth(true);
              }}
              className="ml-1 rounded-full border border-slate-600 px-2 py-0.5 text-[10px] font-semibold tracking-[0.14em] text-slate-300 transition hover:border-slate-400 hover:text-white"
            >
              Retry
            </button>
          </div>
        </header>

        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 shadow-2xl shadow-slate-950/40 md:p-6">
          <form className="flex flex-col gap-4 md:flex-row" onSubmit={onSubmit}>
            <input
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              placeholder="Enter ticker (e.g. AAPL)"
              className="h-12 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 text-base font-medium tracking-wide text-slate-100 outline-none transition focus:border-emerald-400"
            />
            <button
              type="submit"
              disabled={status === "loading"}
              className={clsx(
                "inline-flex h-12 min-w-[180px] items-center justify-center rounded-xl px-5 font-semibold transition",
                status === "loading"
                  ? "cursor-not-allowed bg-slate-700 text-slate-300"
                  : "bg-emerald-500 text-slate-950 hover:bg-emerald-400"
              )}
            >
              {status === "loading" ? (
                <span className="inline-flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Generating...
                </span>
              ) : (
                "Generate Memo"
              )}
            </button>
          </form>

          {status === "loading" && (
            <div className="mt-5 rounded-xl border border-emerald-900/40 bg-emerald-950/20 p-4">
              <div className="mb-3 inline-flex items-center gap-2 text-sm text-emerald-300">
                <Terminal className="h-4 w-4" />
                Live Orchestration Status
              </div>
              <p className="text-base font-medium text-emerald-100">{stageLabel}</p>
              <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-slate-800">
                <div className="loading-bar h-full w-1/3 rounded-full bg-emerald-400" />
              </div>
            </div>
          )}

          {status === "error" && (
            <div className="mt-5 rounded-xl border border-amber-700/40 bg-amber-950/20 p-4 text-amber-100">
              <p className="inline-flex items-center gap-2 font-medium">
                <AlertTriangle className="h-4 w-4" />
                {errorMessage}
              </p>
            </div>
          )}
        </section>

        {memo && (
          <section className="relative mt-8 overflow-hidden rounded-2xl border border-slate-800 bg-white text-slate-900 shadow-2xl shadow-black/30 md:mt-10">
            <div className="border-b border-slate-200 px-6 py-4">
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">Confidential</p>
              <p className="mt-1 text-sm text-slate-600">For educational research workflow validation only.</p>
            </div>
            <div className="pointer-events-none absolute right-[-10px] top-20 rotate-[-22deg] text-5xl font-black uppercase tracking-[0.28em] text-slate-200/50 md:text-7xl">
              Confidential
            </div>
            <article className="memo markdown-body relative z-10 px-6 py-8 md:px-10 md:py-10">
              <ReactMarkdown>{memo}</ReactMarkdown>
            </article>
          </section>
        )}

        <section className="mt-8 rounded-2xl border border-slate-800 bg-slate-900/60 p-5 md:mt-10 md:p-6">
          <button
            type="button"
            onClick={() => setShowTrace((prev) => !prev)}
            className="inline-flex w-full items-center justify-between text-left text-sm font-semibold uppercase tracking-[0.22em] text-slate-200"
          >
            Developer Trace
            {showTrace ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>

          {showTrace && (
            <div className="mt-4 space-y-2">
              {traceLogs.length === 0 ? (
                <p className="text-sm text-slate-400">No trace logs returned yet.</p>
              ) : (
                traceLogs.map((log, idx) => (
                  <div key={`${log.agent}-${idx}`} className="rounded-lg border border-slate-800 bg-slate-950/70 px-4 py-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{log.agent}</p>
                    <p className="mt-1 text-sm text-slate-200">{log.status}</p>
                  </div>
                ))
              )}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
