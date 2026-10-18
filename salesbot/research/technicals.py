"""Technical indicators and the breakout setup, on plain lists of daily bars (oldest first)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Bars:
    close: list[float]
    high: list[float]
    low: list[float]
    volume: list[float]


def sma(values: list[float], n: int, end: int | None = None) -> float | None:
    end = len(values) if end is None else end
    if end < n:
        return None
    return sum(values[end - n : end]) / n


def rsi(close: list[float], n: int = 14) -> float | None:
    """Wilder's RSI."""
    if len(close) <= n:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = close[i] - close[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_g, avg_l = gains / n, losses / n
    for i in range(n + 1, len(close)):
        d = close[i] - close[i - 1]
        avg_g = (avg_g * (n - 1) + max(d, 0)) / n
        avg_l = (avg_l * (n - 1) + max(-d, 0)) / n
    if avg_l == 0:
        return 100.0
    return 100 - 100 / (1 + avg_g / avg_l)


def atr(b: Bars, n: int = 14) -> float | None:
    if len(b.close) <= n:
        return None
    trs = [
        max(b.high[i] - b.low[i], abs(b.high[i] - b.close[i - 1]), abs(b.low[i] - b.close[i - 1]))
        for i in range(len(b.close) - n, len(b.close))
    ]
    return sum(trs) / n


def pct_change(close: list[float], days: int) -> float | None:
    if len(close) <= days or close[-1 - days] <= 0:
        return None
    return close[-1] / close[-1 - days] - 1


def technicals(b: Bars, benchmark: list[float] | None = None) -> dict[str, Any]:
    """Indicators plus a breakout read. Needs about a year of bars (more for a rising 200-day line)."""
    c, h, lo, v = b.close, b.high, b.low, b.volume
    price = c[-1]
    year = min(252, len(c))
    high52, low52 = max(h[-year:]), min(lo[-year:])
    s50, s150, s200 = sma(c, 50), sma(c, 150), sma(c, 200)
    s200_month_ago = sma(c, 200, len(c) - 21)
    # The base: the last 20 sessions before today; its high is the breakout pivot.
    pivot = max(h[-21:-1]) if len(h) > 21 else max(h)
    base_low = min(lo[-21:-1]) if len(lo) > 21 else min(lo)
    tight = max(h[-15:]) / min(lo[-15:]) - 1 if len(h) >= 15 else None
    vol50, vol10 = sma(v, 50), sma(v, 10)
    out: dict[str, Any] = {
        "price": round(price, 2),
        "sma50": _r(s50), "sma150": _r(s150), "sma200": _r(s200),
        "high_52w": round(high52, 2), "low_52w": round(low52, 2),
        "pct_below_52w_high": round((high52 - price) / high52 * 100, 1),
        "pct_above_52w_low": round((price / low52 - 1) * 100, 1),
        "pivot": round(pivot, 2),
        "pct_below_pivot": round((pivot - price) / pivot * 100, 1),
        "base_depth_pct": round((pivot - base_low) / pivot * 100, 1),
        "tightness_15d_pct": _r(tight * 100 if tight is not None else None, 1),
        "rsi14": _r(rsi(c), 1),
        "atr14_pct": _r((atr(b) or 0) / price * 100, 2),
        "volume_10d_vs_50d": _r(vol10 / vol50 if vol10 and vol50 else None, 2),
        "volume_today_vs_50d": _r(v[-1] / vol50 if vol50 else None, 2),
        "return_3m_pct": _r(_pct(pct_change(c, 63))),
        "return_6m_pct": _r(_pct(pct_change(c, 126))),
    }
    if benchmark and len(benchmark) > 126 and len(c) > 126:
        out["rs_6m_vs_spy_pct"] = _r(_pct((pct_change(c, 126) or 0) - (pct_change(benchmark, 126) or 0)))
    trend = {
        "above_50_150_200": bool(s50 and s150 and s200 and price > s50 > s150 > s200),
        "sma200_rising": bool(s200 and s200_month_ago and s200 > s200_month_ago),
        "30pct_above_52w_low": price >= low52 * 1.3,
        "within_25pct_of_52w_high": price >= high52 * 0.75,
    }
    out["trend_template"] = trend
    out["setup"] = _setup(out, trend)
    return out


def _setup(t: dict[str, Any], trend: dict[str, bool]) -> dict[str, Any]:
    """Stage-2 uptrend + tight base just under a pivot that is at or near 52-week highs."""
    reasons: list[str] = []
    score = 0
    passed = sum(trend.values())
    score += passed * 10
    if passed == 4:
        reasons.append("stage-2 uptrend (price > 50 > 150 > 200-day, 200-day rising)")
    below = t["pct_below_pivot"]
    breaking_out = below < 0 and (t["volume_today_vs_50d"] or 0) >= 1.4
    if breaking_out:
        score += 25
        reasons.append(f"closed above the {t['pivot']} pivot on {t['volume_today_vs_50d']}x average volume")
    elif 0 <= below <= 5:
        score += 25 - int(below * 3)
        reasons.append(f"{below}% below the {t['pivot']} pivot")
    if t["pct_below_52w_high"] <= 5:
        score += 10
        reasons.append("pivot at/near 52-week high")
    tight = t["tightness_15d_pct"]
    if tight is not None and tight <= 10:
        score += 10
        reasons.append(f"tight base ({tight}% range over 15 days)")
    if (t["volume_10d_vs_50d"] or 9) < 0.9:
        score += 5
        reasons.append("volume drying up in the base")
    if (t.get("rs_6m_vs_spy_pct") or 0) > 0:
        score += 10
        reasons.append(f"outperforming SPY by {t['rs_6m_vs_spy_pct']}% over 6 months")
    rsi_v = t["rsi14"] or 50
    if rsi_v > 80:
        score -= 10
        reasons.append(f"overbought (RSI {rsi_v})")
    near = passed == 4 and (breaking_out or 0 <= below <= 5) and t["pct_below_52w_high"] <= 8
    return {
        "score": max(0, min(100, score)),
        "near_breakout": near,
        "breaking_out": breaking_out and passed == 4,
        "reasons": reasons,
        # A common risk line: just under the base low, or 1.5 ATR below the pivot if that is tighter.
        # Only meaningful near the pivot; far from it there is no defined entry yet.
        "stop_idea": round(max(t["pivot"] * (1 - t["base_depth_pct"] / 100) * 0.99, t["pivot"] * (1 - 1.5 * t["atr14_pct"] / 100)), 2)
        if -5 <= below <= 8 else None,
    }


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(x, nd)


def _pct(x: float | None) -> float | None:
    return None if x is None else x * 100
