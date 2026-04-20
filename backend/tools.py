"""Custom CrewAI tools for market data and news."""

from __future__ import annotations

import os
from typing import Any

import yfinance as yf
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from tavily import TavilyClient


class YFinanceInput(BaseModel):
    ticker: str = Field(..., description="US equity ticker symbol, e.g. AAPL")


class YFinanceTool(BaseTool):
    name: str = "YFinanceTool"
    description: str = (
        "Loads live Yahoo Finance data for a single ticker: last price, key valuation "
        "metrics when available, and a short company description. Pass the ticker as uppercase "
        "or mixed case (e.g. AAPL)."
    )
    args_schema: type[BaseModel] = YFinanceInput

    def _run(self, ticker: str) -> str:
        symbol = (ticker or "").strip().upper()
        if not symbol:
            return "Error: empty ticker."

        try:
            t = yf.Ticker(symbol)
            fast: dict[str, Any] = dict(getattr(t, "fast_info", {}) or {})
            info: dict[str, Any] = dict(getattr(t, "info", {}) or {})

            last_price = fast.get("last_price") or fast.get("lastPrice") or info.get(
                "currentPrice"
            )
            prev_close = fast.get("previous_close") or info.get("previousClose")
            market_cap = fast.get("market_cap") or info.get("marketCap")
            pe_ttm = info.get("trailingPE")
            pe_fwd = info.get("forwardPE")
            pb = info.get("priceToBook")
            ev_ebitda = info.get("enterpriseToEbitda")
            week_52_low = info.get("fiftyTwoWeekLow")
            week_52_high = info.get("fiftyTwoWeekHigh")
            summary = (
                info.get("longBusinessSummary")
                or info.get("shortName")
                or "No business summary available."
            )

            lines = [
                f"Ticker: {symbol}",
                f"Last price: {last_price}",
                f"Previous close: {prev_close}",
                f"Market cap: {market_cap}",
                f"52-week range: {week_52_low} – {week_52_high}",
                f"Trailing P/E: {pe_ttm}",
                f"Forward P/E: {pe_fwd}",
                f"Price / book: {pb}",
                f"EV / EBITDA: {ev_ebitda}",
                "Summary:",
                str(summary)[:2000],
            ]
            return "\n".join(str(x) for x in lines)
        except Exception as exc:  # noqa: BLE001
            return f"YFinanceTool error for {symbol}: {exc!s}"


class TavilyNewsInput(BaseModel):
    query: str = Field(
        ...,
        description="Web search query for recent financial or company news, e.g. 'MSFT earnings headline'.",
    )


class TavilyNewsTool(BaseTool):
    name: str = "TavilyNewsTool"
    description: str = (
        "Searches the web for recent financial news headlines and snippets using Tavily. "
        "Provide a focused natural-language query (include ticker and topic)."
    )
    args_schema: type[BaseModel] = TavilyNewsInput

    def _run(self, query: str) -> str:
        q = (query or "").strip()
        if not q:
            return "Error: empty search query."

        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return "Error: TAVILY_API_KEY is not set in the environment."

        try:
            client = TavilyClient(api_key=api_key)
            resp = client.search(
                query=q,
                topic="news",
                search_depth="advanced",
                max_results=6,
                include_answer=False,
            )
        except Exception as exc:  # noqa: BLE001
            return f"TavilyNewsTool error: {exc!s}"

        results = resp.get("results") if isinstance(resp, dict) else None
        if not results:
            return "No news results returned for this query."

        blocks: list[str] = []
        for i, item in enumerate(results, start=1):
            title = item.get("title") or "Untitled"
            url = item.get("url") or ""
            published = item.get("published_date") or item.get("publishedDate") or ""
            snippet = (item.get("content") or "")[:500]
            blocks.append(
                f"{i}. {title}\n   URL: {url}\n   Date: {published}\n   Snippet: {snippet}"
            )
        return "\n\n".join(blocks)
