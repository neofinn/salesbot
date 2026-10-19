"""Stock research tools: real technical + fundamental analysis and a breakout scan."""

from __future__ import annotations

import json
from typing import Any

from ..research import analyze, filters, scan
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


async def _filter(args: dict[str, Any], ctx: ToolContext) -> str:
    snap = filters.load_cached(ctx.settings.data_dir)
    if snap is None:
        try:
            snap = await filters.snapshot(600)
        except DataError as exc:
            raise ToolError(str(exc)) from exc
        filters.save_cached(ctx.settings.data_dir, snap)
    preset = str(args.get("preset") or "")
    criteria = dict(filters.PRESETS.get(preset, {}))
    for key in ("min", "max", "is", "tickers", "sort", "desc", "limit"):
        if args.get(key) not in (None, "", {}, []):
            criteria[key] = args[key]
    hits = filters.apply(snap["rows"], criteria)
    return json.dumps({"data_as_of": snap["generated_at"], "universe": snap["universe"], "criteria": filters.validate(criteria),
                       "matches": len(hits), "stocks": hits, "disclaimer": snap["disclaimer"]}, indent=1)


num_map = {"type": "object", "additionalProperties": {"type": "number"}}

STOCK_FILTER = Tool(
    "stock_filter",
    "Stock screener over about 600 large US stocks (daily data, refreshed every 20 hours). Turn the request into "
    "criteria: a preset and/or min/max bounds and true/false flags on these fields: " + filters.describe_fields()
    + ". Presets: " + ", ".join(filters.PRESETS) + ".",
    schema({
        "preset": {"type": "string", "enum": list(filters.PRESETS)},
        "min": num_map, "max": num_map,
        "is": {"type": "object", "additionalProperties": {"type": "boolean"}},
        "tickers": {"type": "array", "items": {"type": "string"}},
        "sort": string("Numeric field to sort by (default score)"),
        "desc": {"type": "boolean"}, "limit": {"type": "integer"},
    }),
    _filter,
)

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
