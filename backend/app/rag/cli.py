"""Batch pre-ingestion CLI for SEC 10-K filings.

Typical production flow:

    # Ingest once per trading day from a cron / systemd timer / GH Action:
    python -m app.rag.cli ingest AAPL MSFT NVDA --force

    # Inspect what's currently cached in Chroma:
    python -m app.rag.cli status AAPL MSFT

With ``FILINGS_READ_ONLY=true`` set in the server process, ``/research`` will
then never touch EDGAR in the hot path - it just queries Chroma.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Sequence

from app.config import get_settings
from app.rag.chroma_store import ChromaStore
from app.rag.ingestion import ingest_latest_10k_if_missing
from app.tools.base import InvalidInputError, ToolError, validate_ticker

logger = logging.getLogger(__name__)


def _build_store() -> ChromaStore:
    settings = get_settings()
    return ChromaStore(
        persist_dir=settings.chroma_persist_dir,
        embedding_model=settings.embedding_model,
    )


def _cmd_ingest(tickers: Sequence[str], *, force: bool) -> int:
    store = _build_store()
    exit_code = 0
    for raw in tickers:
        try:
            symbol = validate_ticker(raw)
        except InvalidInputError as e:
            print(f"[skip] {raw!r}: {e}", file=sys.stderr)
            exit_code = 1
            continue
        try:
            result = ingest_latest_10k_if_missing(symbol, store, force=force)
        except ToolError as e:
            print(f"[fail] {symbol}: {e}", file=sys.stderr)
            exit_code = 1
            continue
        if result.skipped:
            print(f"[skip] {symbol}: already in store (use --force to refresh)")
        else:
            print(
                f"[ok]   {symbol}: {result.chunks_ingested} chunks across "
                f"{len(result.sections)} sections ({result.accession_number})"
            )
    return exit_code


def _cmd_status(tickers: Sequence[str]) -> int:
    store = _build_store()
    for raw in tickers:
        try:
            symbol = validate_ticker(raw)
        except InvalidInputError as e:
            print(f"[skip] {raw!r}: {e}", file=sys.stderr)
            continue
        n = store.ticker_chunk_count(symbol)
        marker = "yes" if n > 0 else "no "
        print(f"[{marker}] {symbol}: {n} chunks")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.rag.cli",
        description="Pre-ingest SEC 10-K filings into ChromaDB.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ing = sub.add_parser("ingest", help="Ingest latest 10-K for one or more tickers.")
    ing.add_argument("tickers", nargs="+", help="Ticker symbols (e.g. AAPL MSFT).")
    ing.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest even when the ticker is already present in Chroma.",
    )

    st = sub.add_parser("status", help="Report how many chunks each ticker has.")
    st.add_argument("tickers", nargs="+", help="Ticker symbols to look up.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_parser().parse_args(argv)

    if args.command == "ingest":
        return _cmd_ingest(args.tickers, force=args.force)
    if args.command == "status":
        return _cmd_status(args.tickers)
    return 2


if __name__ == "__main__":  # pragma: no cover - thin entrypoint
    raise SystemExit(main())
