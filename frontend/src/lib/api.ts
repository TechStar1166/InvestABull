export type TraceLog = {
  agent: string;
  status: string;
};

export type ResearchResponse = {
  memo: string;
  trace_logs: TraceLog[];
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
