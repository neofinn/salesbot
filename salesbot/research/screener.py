"""Analyse one stock, or scan a universe for stocks near a breakout."""

from __future__ import annotations

import time
from typing import Any

from . import data
from .technicals import technicals

DISCLAIMER = "Research only, not financial advice. Data: Yahoo Finance (prices), SEC EDGAR (financials)."


def fundamental_score(f: dict[str, Any]) -> tuple[int, list[str]]:
    score, notes = 0, []
    if f.get("stale") or not f.get("latest_quarter"):
        return 0, [f"no recent quarterly data in SEC filings (latest {f.get('latest_quarter') or 'none'}); check the latest 10-Q"]
    rg, eg = f.get("revenue_growth_yoy_pct"), f.get("eps_growth_yoy_pct")
    if rg is not None:
        if rg >= 25:
            score += 35; notes.append(f"revenue +{rg}% y/y")
        elif rg >= 10:
            score += 20; notes.append(f"revenue +{rg}% y/y")
        elif rg < 0:
            notes.append(f"revenue {rg}% y/y")
    if eg is not None:
        if eg >= 25:
            score += 35; notes.append(f"EPS +{eg}% y/y")
        elif eg >= 10:
            score += 20; notes.append(f"EPS +{eg}% y/y")
        elif eg < 0:
            notes.append(f"EPS {eg}% y/y")
    prior = f.get("revenue_growth_prior_quarter_pct")
    if rg is not None and prior is not None and rg > prior:
        score += 15; notes.append(f"revenue growth accelerating ({prior}% -> {rg}%)")
    nm = f.get("net_margin_pct")
    if nm is not None and nm > 0:
        score += 15; notes.append(f"profitable ({nm}% net margin)")
    elif nm is not None:
        notes.append(f"unprofitable ({nm}% net margin)")
    return min(100, score), notes


async def analyze(ticker: str) -> dict[str, Any]:
    """Full technical + fundamental read on one ticker."""
    ticker = ticker.upper().strip()
    async with data.client() as client:
        bars, spy = await data.history(client, ticker), await data.history(client, "SPY")
        tech = technicals(bars, spy.close)
        out: dict[str, Any] = {"ticker": ticker, "technical": tech, "disclaimer": DISCLAIMER}
        found = await data.cik_for(client, ticker)
        if found:
            out["name"] = found[1]
            try:
                out["fundamental"] = await data.fundamentals(client, found[0])
                out["fundamental"]["score"], out["fundamental"]["notes"] = fundamental_score(out["fundamental"])
            except data.DataError as exc:
                out["fundamental"] = {"error": str(exc)}
    return out


async def scan(top: int = 300, tickers: list[str] | None = None, limit: int = 15) -> dict[str, Any]:
    """Screen the largest US companies (or the given tickers) for setups near a breakout,
    then add fundamentals for the best ones. Ranked by technical + fundamental score."""
    started = time.time()
    async with data.client() as client:
        names: dict[str, str] = {}
        ciks: dict[str, int] = {}
        if tickers:
            symbols = [t.upper().strip() for t in tickers if t.strip()]
        else:
            uni = await data.universe(client, top)
            symbols = [u["ticker"] for u in uni]
            names = {u["ticker"]: u["name"] for u in uni}
            ciks = {u["ticker"]: u["cik"] for u in uni}
        spy = await data.history(client, "SPY")
        bars = await data.gather_limited([data.history(client, s) for s in symbols])
        rows, failed = [], []
        for sym, b in zip(symbols, bars):
            if isinstance(b, Exception):
                failed.append(sym)
                continue
            t = technicals(b, spy.close)
            rows.append({"ticker": sym, "name": names.get(sym, ""), "technical": t})
        candidates = sorted((r for r in rows if r["technical"]["setup"]["near_breakout"]), key=lambda r: -r["technical"]["setup"]["score"])
        watch = sorted((r for r in rows if not r["technical"]["setup"]["near_breakout"]), key=lambda r: -r["technical"]["setup"]["score"])
        picks = candidates[: limit * 2]
        if tickers and not ciks:
            for p in picks:
                found = await data.cik_for(client, p["ticker"])
                if found:
                    ciks[p["ticker"]], p["name"] = found
        funds = await data.gather_limited([data.fundamentals(client, ciks[p["ticker"]]) for p in picks if p["ticker"] in ciks], limit=4)
        it = iter(funds)
        for p in picks:
            if p["ticker"] not in ciks:
                continue
            f = next(it)
            if isinstance(f, Exception):
                p["fundamental"] = {"error": str(f)}
                continue
            f["score"], f["notes"] = fundamental_score(f)
            p["fundamental"] = f
        for p in picks:
            p["score"] = round(0.6 * p["technical"]["setup"]["score"] + 0.4 * p.get("fundamental", {}).get("score", 0))
        picks.sort(key=lambda p: -p["score"])
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "universe": f"given tickers ({len(symbols)})" if tickers else f"largest {len(symbols)} US-listed companies (SEC list)",
        "scanned": len(rows), "failed": failed,
        "breakout_candidates": picks[:limit],
        "watchlist": [{"ticker": w["ticker"], "name": w["name"], "score": w["technical"]["setup"]["score"],
                       "pct_below_pivot": w["technical"]["pct_below_pivot"], "reasons": w["technical"]["setup"]["reasons"]} for w in watch[:10]],
        "method": ("Technical: stage-2 trend template (price > 50 > 150 > 200-day SMA, 200-day rising, 30%+ above the 52-week low, "
                   "within 25% of the high); near breakout = within 5% below the 20-day base high (pivot) or just through it on 1.4x+ volume, "
                   "with the pivot within 8% of the 52-week high; extra credit for a tight base, drying volume and 6-month strength vs SPY. "
                   "Fundamental: latest-quarter revenue and EPS growth y/y, revenue acceleration and profitability from SEC filings. "
                   "Overall score = 60% technical + 40% fundamental."),
        "seconds": round(time.time() - started, 1),
        "disclaimer": DISCLAIMER,
    }


def summary(report: dict[str, Any]) -> str:
    """Plain-text version of a scan for chat, Telegram or a bot's context."""
    lines = [f"Breakout scan {report['generated_at']} - {report['universe']}, {report['scanned']} scanned.", ""]
    for i, p in enumerate(report["breakout_candidates"], 1):
        t, s = p["technical"], p["technical"]["setup"]
        f = p.get("fundamental", {})
        tag = "BREAKING OUT" if s["breaking_out"] else f"{t['pct_below_pivot']}% below pivot {t['pivot']}"
        lines.append(f"{i}. {p['ticker']} {p.get('name', '')} - score {p['score']} - ${t['price']} ({tag})" + (f"; stop idea {s['stop_idea']}" if s["stop_idea"] else ""))
        lines.append(f"   Technical: {'; '.join(s['reasons'])}. RSI {t['rsi14']}.")
        if f.get("notes"):
            lines.append(f"   Fundamental ({f.get('latest_quarter')}): {'; '.join(f['notes'])}.")
    if not report["breakout_candidates"]:
        lines.append("No stock passed every breakout check today. Closest setups:")
        for w in report["watchlist"][:5]:
            lines.append(f"- {w['ticker']} {w['name']} (score {w['score']}): {'; '.join(w['reasons'])}")
    lines += ["", report["disclaimer"]]
    return "\n".join(lines)


def report_doc(report: dict[str, Any], title: str = "Stocks near a breakout") -> dict[str, Any]:
    """A scan shaped for the MyOps page's Reports tab (its `reports` collection)."""
    items = []
    for p in report["breakout_candidates"]:
        t, s = p["technical"], p["technical"]["setup"]
        f = p.get("fundamental", {})
        items.append({
            "ticker": p["ticker"], "name": p.get("name", ""), "score": p["score"],
            "price": t["price"], "pivot": t["pivot"], "pct_below_pivot": t["pct_below_pivot"],
            "breaking_out": s["breaking_out"], "stop": s["stop_idea"], "rsi": t["rsi14"],
            "technical": s["reasons"], "fundamental": f.get("notes", []), "quarter": f.get("latest_quarter"),
            "metrics": {k: t.get(k) for k in ("sma50", "sma150", "sma200", "high_52w", "low_52w", "tightness_15d_pct",
                                               "volume_10d_vs_50d", "atr14_pct", "return_3m_pct", "return_6m_pct", "rs_6m_vs_spy_pct")}
            | {k: f.get(k) for k in ("revenue_growth_yoy_pct", "eps_growth_yoy_pct", "net_margin_pct", "gross_margin_pct")},
        })
    return {
        "title": title, "kind": "stock_scan", "generated_at": report["generated_at"],
        "createdAt": int(time.time() * 1000), "universe": report["universe"], "scanned": report["scanned"],
        "items": items, "watchlist": report["watchlist"], "method": report["method"],
        "summary": summary(report), "disclaimer": report["disclaimer"],
    }
