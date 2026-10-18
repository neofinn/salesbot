"""Stock research tools: real technical + fundamental analysis and a breakout scan."""

from __future__ import annotations

import json
from typing import Any

from ..research import analyze, scan
from ..research.data import DataError
from ..research.screener import summary
from .base import Tool, ToolContext, ToolError, schema, string


async def _analyze(args: dict[str, Any], ctx: ToolContext) -> str:
    try:
        return json.dumps(await analyze(args["ticker"]), indent=1)
    except DataError as exc:
        raise ToolError(str(exc)) from exc


async def _scan(args: dict[str, Any], ctx: ToolContext) -> str:
    tickers = [t for t in str(args.get("tickers", "")).replace(" ", "").split(",") if t]
    try:
        top = max(20, min(int(args.get("top") or 300), 600))
    except (TypeError, ValueError):
        top = 300
    try:
        report = await scan(top=top, tickers=tickers or None, limit=12)
    except DataError as exc:
        raise ToolError(str(exc)) from exc
    return summary(report)


STOCK_ANALYZE = Tool(
    "stock_analyze",
    "Technical and fundamental analysis of one US stock from real data: trend (50/150/200-day averages), "
    "52-week range, base/pivot, RSI, ATR, volume, strength vs SPY, breakout setup and stop idea, plus latest-quarter "
    "revenue/EPS growth and margins from SEC filings.",
    schema({"ticker": string("Ticker symbol, e.g. NVDA")}, ["ticker"]),
    _analyze,
)

STOCK_SCREEN = Tool(
    "stock_screen",
    "Scan US stocks for setups near a breakout (stage-2 uptrend, tight base just under a pivot at 52-week highs), "
    "ranked by technical + fundamental score. Scans the largest companies unless tickers are given.",
    schema({
        "tickers": string("Optional comma-separated tickers to scan instead of the default universe"),
        "top": string("Optional: how many of the largest US companies to scan (20-600, default 300)"),
    }),
    _scan,
)
