import { Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";

type ReportViewerProps = {
  memo: string;
  isStreaming: boolean;
  errorMessage: string;
};

export default function ReportViewer({
  memo,
  isStreaming,
  errorMessage,
}: ReportViewerProps) {
  return (
    <section className="flex min-h-[420px] flex-col rounded-xl border border-slate-800 bg-slate-900/40">
      <div className="border-b border-slate-800 px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
          Investment memo
        </p>
      </div>

      <div className="relative flex-1 overflow-y-auto p-4 md:p-6">
        {!memo && isStreaming && (
          <div className="animate-pulse space-y-4">
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
  );
}