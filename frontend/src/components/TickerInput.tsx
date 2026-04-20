import clsx from "clsx";
import { Loader2, Sparkles } from "lucide-react";

type TickerInputProps = {
  ticker: string;
  isStreaming: boolean;
  onTickerChange: (value: string) => void;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
};

export default function TickerInput({
  ticker,
  isStreaming,
  onTickerChange,
  onSubmit,
}: TickerInputProps) {
  return (
    <form
      className="mb-6 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center"
      onSubmit={onSubmit}
    >
      <input
        value={ticker}
        onChange={(e) => onTickerChange(e.target.value.toUpperCase())}
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
  );
}