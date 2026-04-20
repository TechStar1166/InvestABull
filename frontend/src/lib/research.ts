import { ApiError, type TraceEventPayload } from "./api";

export type HealthState = "checking" | "online" | "offline";
export type StepKey = "price" | "news" | "macro" | "filings" | "coordinator";
export type StepStatus = "pending" | "active" | "done";

export const STEP_ORDER: { key: StepKey; label: string }[] = [
  { key: "price", label: "Price" },
  { key: "news", label: "News" },
  { key: "macro", label: "Macro" },
  { key: "filings", label: "Filings" },
  { key: "coordinator", label: "Coordinator" },
];

export function isTraceEvent(data: unknown): data is TraceEventPayload {
  return (
    typeof data === "object" &&
    data !== null &&
    "status" in data &&
    typeof (data as TraceEventPayload).status === "string"
  );
}

export function specialistKeyFromEvent(e: TraceEventPayload): StepKey | null {
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

export function deriveStepStatuses(
  events: TraceEventPayload[],
  isStreaming: boolean
): Record<StepKey, StepStatus> {
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

  for (const key of order) {
    if (done.has(key)) result[key] = "done";
  }

  if (isStreaming && fanout) {
    const firstPending = order.find((key) => !done.has(key));
    if (firstPending) result[firstPending] = "active";
  }

  return result;
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) {
      return "Ticker Not Found. Please check the symbol and try again.";
    }
    if (error.status === 408) {
      return "Research request timed out. Please retry in a moment.";
    }
    if (
      error.status === 500 ||
      error.status === 502 ||
      error.status === 503
    ) {
      return "Research Pipeline Interrupted. Please retry after a short wait.";
    }
    return error.message;
  }

  if (error instanceof Error) return error.message;

  return "Research Pipeline Interrupted. Please retry.";
}