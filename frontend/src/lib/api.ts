export type TraceLog = {
  agent: string;
  status: string;
};

export type ResearchResponse = {
  memo: string;
  trace_logs: TraceLog[];
};

/** Matches backend `TraceEvent` SSE payloads. */
export type TraceEventPayload = {
  id?: string;
  timestamp?: string;
  stage?: string;
  agent?: string;
  status?: string;
  meta?: Record<string, unknown>;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function getApiBaseUrl(): string {
  const base = process.env.NEXT_PUBLIC_API_URL;
  if (!base) {
    throw new Error(
      "NEXT_PUBLIC_API_URL is not configured. Set it in frontend/.env.local."
    );
  }
  return base.replace(/\/$/, "");
}

function parseSseDataLines(segment: string): unknown[] {
  const out: unknown[] = [];
  const lines = segment.split("\n");
  for (const raw of lines) {
    const line = raw.replace(/\r$/, "").trim();
    if (!line.startsWith("data:")) continue;
    const payload = line.slice(5).trim();
    if (!payload || payload === "[DONE]") continue;
    try {
      out.push(JSON.parse(payload));
    } catch {
      /* ignore malformed line; next chunk may complete frame */
    }
  }
  return out;
}

/**
 * Consume POST /api/research/stream (SSE). Buffers chunks so `data: {...}` JSON
 * split across reads is only parsed after a frame delimiter (`\n\n` or `\n`).
 */
export async function streamResearch(
  ticker: string,
  onEvent: (data: unknown) => void,
  onComplete: () => void,
  onError: (err: unknown) => void
): Promise<void> {
  const trimmedTicker = ticker.trim().toUpperCase();
  if (!trimmedTicker) {
    onError(new ApiError(422, "Please enter a ticker symbol."));
    return;
  }

  let response: Response;
  try {
    response = await fetch(`${getApiBaseUrl()}/api/research/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker: trimmedTicker }),
      cache: "no-store",
    });
  } catch (e) {
    onError(e);
    return;
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const j = (await response.json()) as { detail?: string };
      if (typeof j?.detail === "string") detail = j.detail;
    } catch {
      try {
        const t = await response.text();
        if (t) detail = t.slice(0, 500);
      } catch {
        /* noop */
      }
    }
    onError(new ApiError(response.status, detail));
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    onError(new Error("No response body"));
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  const flushFrames = (): void => {
    let sep = buffer.indexOf("\n\n");
    while (sep !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      for (const obj of parseSseDataLines(frame)) {
        onEvent(obj);
      }
      sep = buffer.indexOf("\n\n");
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (value) {
        buffer += decoder.decode(value, { stream: true });
        flushFrames();
      }
      if (done) break;
    }

    buffer += decoder.decode();
    flushFrames();

    const tail = buffer.replace(/\r$/, "").trim();
    if (tail.startsWith("data:")) {
      const payload = tail.slice(5).trim();
      if (payload && payload !== "[DONE]") {
        try {
          onEvent(JSON.parse(payload));
        } catch {
          /* incomplete trailing frame */
        }
      }
    }

    onComplete();
  } catch (e) {
    onError(e);
  }
}

export async function fetchResearch(ticker: string): Promise<ResearchResponse> {
  const trimmedTicker = ticker.trim().toUpperCase();
  if (!trimmedTicker) {
    throw new ApiError(422, "Please enter a ticker symbol.");
  }

  const controller = new AbortController();
  const timeoutMs = 300_000;
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${getApiBaseUrl()}/api/research`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ticker: trimmedTicker }),
      signal: controller.signal,
      cache: "no-store",
      keepalive: false,
    });

    const payload = await response.json().catch(() => null);

    if (!response.ok) {
      const detail =
        typeof payload?.detail === "string" ? payload.detail : "Request failed.";
      throw new ApiError(response.status, detail);
    }

    return payload as ResearchResponse;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }

    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        408,
        "Research took longer than expected. Please try again with a shorter ticker or retry in a moment."
      );
    }

    throw new ApiError(500, "Unable to reach the research service.");
  } finally {
    clearTimeout(timeout);
  }
}
