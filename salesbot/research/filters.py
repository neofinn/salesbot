"""The stock screener: a snapshot of technical metrics for a whole universe, and filters over it.

A snapshot is one flat row per stock (see FIELDS). Criteria are plain JSON so a model can write them
from a request in the owner's words and the MyOps page can apply the same filters in the browser:

    {"min": {"rsi": 40}, "max": {"off_high": 5}, "is": {"above_200": true},
     "tickers": [], "sort": "score", "desc": true, "limit": 25}
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from . import data
from .screener import DISCLAIMER
from .technicals import Bars, pct_change, sma, technicals

MIN_DOLLAR_VOL_M = 2.0
# key: (label, kind, unit) - kind is "num", "bool" or "text".
FIELDS: dict[str, tuple[str, str, str]] = {
    "ticker": ("Ticker", "text", ""),
    "name": ("Company", "text", ""),
    "price": ("Price", "num", "$"),
    "chg_1d": ("Change today", "num", "%"),
    "ret_1m": ("1-month return", "num", "%"),
    "ret_3m": ("3-month return", "num", "%"),
    "ret_6m": ("6-month return", "num", "%"),
    "rs_6m": ("6-month return vs SPY", "num", "%"),
    "rsi": ("RSI (14)", "num", ""),
    "off_high": ("Below 52-week high", "num", "%"),
    "off_low": ("Above 52-week low", "num", "%"),
    "to_pivot": ("Below breakout pivot", "num", "%"),
    "tight": ("15-day price range", "num", "%"),
    "vol_ratio": ("Volume today vs 50-day avg", "num", "x"),
    "vol_trend": ("10-day vs 50-day volume", "num", "x"),
    "dollar_vol": ("Avg daily dollar volume", "num", "$M"),
    "atr": ("Daily range (ATR)", "num", "%"),
    "trend": ("Trend checks passed (0-4)", "num", ""),
    "score": ("Breakout setup score", "num", ""),
    "above_50": ("Above 50-day average", "bool", ""),
    "above_200": ("Above 200-day average", "bool", ""),
    "golden": ("50-day above 200-day (golden cross)", "bool", ""),
    "near_breakout": ("Near a breakout", "bool", ""),
    "breaking_out": ("Breaking out today", "bool", ""),
}

PRESETS: dict[str, dict[str, Any]] = {
    "Near breakout": {"is": {"near_breakout": True}, "sort": "score", "desc": True},
    "Breaking out today": {"is": {"breaking_out": True}, "sort": "vol_ratio", "desc": True},
    "At 52-week highs": {"max": {"off_high": 2}, "sort": "rs_6m", "desc": True},
    "Strong momentum": {"min": {"ret_6m": 20, "rs_6m": 10}, "is": {"above_50": True}, "sort": "rs_6m", "desc": True},
    "Pullback in uptrend": {"min": {"trend": 3}, "max": {"rsi": 45, "off_high": 15}, "is": {"above_200": True}, "sort": "score", "desc": True},
    "Volume surge": {"min": {"vol_ratio": 2}, "sort": "vol_ratio", "desc": True},
    "Oversold": {"max": {"rsi": 30}, "sort": "rsi", "desc": False},
    "Golden cross": {"is": {"golden": True, "above_200": True}, "max": {"off_high": 10}, "sort": "ret_3m", "desc": True},
}


def row(ticker: str, name: str, b: Bars, spy: list[float] | None) -> dict[str, Any]:
    t = technicals(b, spy)
    c, v = b.close, b.volume
    s50, s200 = t["sma50"], t["sma200"]
    vol50 = sma([ci * vi for ci, vi in zip(c, v)], 50)
    pct = lambda x: None if x is None else round(x * 100, 1)  # noqa: E731
    one = lambda x: None if x is None else round(x, 1)  # noqa: E731
    return {
        "ticker": ticker, "name": name[:60], "price": t["price"],
        "chg_1d": pct(pct_change(c, 1)), "ret_1m": pct(pct_change(c, 21)),
        "ret_3m": one(t["return_3m_pct"]), "ret_6m": one(t["return_6m_pct"]), "rs_6m": one(t.get("rs_6m_vs_spy_pct")),
        "rsi": t["rsi14"], "off_high": t["pct_below_52w_high"], "off_low": t["pct_above_52w_low"],
        "to_pivot": t["pct_below_pivot"], "tight": t["tightness_15d_pct"],
        "vol_ratio": t["volume_today_vs_50d"], "vol_trend": t["volume_10d_vs_50d"],
        "dollar_vol": round(vol50 / 1e6, 1) if vol50 else None, "atr": t["atr14_pct"],
        "trend": sum(t["trend_template"].values()), "score": t["setup"]["score"],
        "above_50": bool(s50 and t["price"] > s50), "above_200": bool(s200 and t["price"] > s200),
        "golden": bool(s50 and s200 and s50 > s200),
        "near_breakout": t["setup"]["near_breakout"], "breaking_out": t["setup"]["breaking_out"],
    }


async def snapshot(top: int = 600, tickers: list[str] | None = None) -> dict[str, Any]:
    """Metrics for the largest US companies (or the given tickers) from a year of daily prices."""
    started = time.time()
    async with data.client() as client:
        if tickers:
            uni = [{"ticker": t.upper().strip(), "name": ""} for t in tickers if t.strip()]
        else:
            uni = await data.universe(client, top)
        spy = await data.history(client, "SPY")
        bars = await data.gather_limited([data.history(client, u["ticker"]) for u in uni])
    rows, failed, thin = [], [], []
    for u, b in zip(uni, bars):
        if isinstance(b, Exception):
            failed.append(u["ticker"])
            continue
        r = row(u["ticker"], u["name"], b, spy.close)
        # Thinly traded listings (mostly foreign OTC lines) give meaningless signals.
        if (r["dollar_vol"] or 0) < MIN_DOLLAR_VOL_M and not tickers:
            thin.append(r["ticker"])
            continue
        rows.append(r)
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "universe": f"given tickers ({len(uni)})" if tickers else f"largest {len(uni)} US-listed companies (SEC list)",
        "count": len(rows), "failed": failed, "skipped_illiquid": thin, "seconds": round(time.time() - started, 1),
        "disclaimer": DISCLAIMER, "rows": rows,
    }


def validate(criteria: dict[str, Any]) -> dict[str, Any]:
    """Keep only known fields with the right types, so model-written criteria can't break a screen."""
    out: dict[str, Any] = {"min": {}, "max": {}, "is": {}}
    for bound in ("min", "max"):
        for k, v in (criteria.get(bound) or {}).items():
            if FIELDS.get(k, ("", ""))[1] == "num":
                try:
                    out[bound][k] = float(v)
                except (TypeError, ValueError):
                    pass
    for k, v in (criteria.get("is") or {}).items():
        if FIELDS.get(k, ("", ""))[1] == "bool" and isinstance(v, bool):
            out["is"][k] = v
    out["tickers"] = [str(t).upper().strip() for t in (criteria.get("tickers") or []) if str(t).strip()][:50]
    out["sort"] = criteria.get("sort") if FIELDS.get(criteria.get("sort") or "", ("", ""))[1] == "num" else "score"
    out["desc"] = bool(criteria.get("desc", True))
    try:
        out["limit"] = max(1, min(int(criteria.get("limit") or 25), 100))
    except (TypeError, ValueError):
        out["limit"] = 25
    return out


def apply(rows: list[dict[str, Any]], criteria: dict[str, Any]) -> list[dict[str, Any]]:
    c = validate(criteria)
    wanted = set(c["tickers"])

    def keep(r: dict[str, Any]) -> bool:
        if wanted and r["ticker"] not in wanted:
            return False
        for k, lo in c["min"].items():
            if r.get(k) is None or r[k] < lo:
                return False
        for k, hi in c["max"].items():
            if r.get(k) is None or r[k] > hi:
                return False
        return all(bool(r.get(k)) == v for k, v in c["is"].items())

    hits = [r for r in rows if keep(r)]
    missing = [r for r in hits if r.get(c["sort"]) is None]
    hits = sorted((r for r in hits if r.get(c["sort"]) is not None), key=lambda r: r[c["sort"]], reverse=c["desc"]) + missing
    return hits[: c["limit"]]


def describe_fields() -> str:
    """The field list for a prompt that turns a request into criteria."""
    return "; ".join(f"{k} ({label}{', ' + unit if unit else ''}, {kind})" for k, (label, kind, unit) in FIELDS.items())


def artifact_docs(snap: dict[str, Any], chunk: int = 120) -> list[dict[str, Any]]:
    """The snapshot as documents for the MyOps page's `screener` collection: a `meta` doc plus row chunks."""
    rows = snap["rows"]
    parts = [rows[i:i + chunk] for i in range(0, len(rows), chunk)] or [[]]
    meta = {k: snap[k] for k in ("generated_at", "universe", "count", "disclaimer")} | {
        "chunks": len(parts), "createdAt": int(time.time() * 1000), "fields": {k: list(v) for k, v in FIELDS.items()}}
    return [{"id": "meta", "data": meta}] + [{"id": f"c{i}", "data": {"rows": p}} for i, p in enumerate(parts)]


def cache_path(data_dir: str) -> str:
    return os.path.join(data_dir, "screener.json")


def load_cached(data_dir: str, max_age_hours: float = 20) -> dict[str, Any] | None:
    try:
        if time.time() - os.path.getmtime(cache_path(data_dir)) > max_age_hours * 3600:
            return None
        with open(cache_path(data_dir)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save_cached(data_dir: str, snap: dict[str, Any]) -> None:
    os.makedirs(data_dir, exist_ok=True)
    with open(cache_path(data_dir), "w") as fh:
        json.dump(snap, fh)
