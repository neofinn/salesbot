import math

import httpx
import pytest

from salesbot.research import data, screener as scan_mod
from salesbot.research.technicals import Bars, rsi, sma, technicals
from salesbot.tools import CATALOG


def uptrend_with_base(n=300):
    """A steady climb, then a tight 20-day base just under the high."""
    close = [50 * math.exp(0.004 * i) for i in range(n - 20)]
    top = close[-1]
    close += [top * (0.97 + 0.02 * ((i % 4) / 3)) for i in range(20)]
    high = [c * 1.01 for c in close]
    low = [c * 0.99 for c in close]
    volume = [1_000_000] * (n - 10) + [700_000] * 10
    return Bars(close, high, low, volume)


def test_indicators():
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert sma([1, 2], 3) is None
    assert rsi(list(range(1, 40))) == 100.0
    falling = list(range(40, 1, -1))
    assert rsi(falling) < 5


def test_uptrend_base_is_near_breakout():
    b = uptrend_with_base()
    spy = [100 + 0.01 * i for i in range(300)]
    t = technicals(b, spy)
    assert all(t["trend_template"].values())
    assert 0 <= t["pct_below_pivot"] <= 5
    assert t["setup"]["near_breakout"] and t["setup"]["score"] >= 60
    assert t["setup"]["stop_idea"] < t["price"]
    assert t["rs_6m_vs_spy_pct"] > 0


def test_downtrend_is_not_a_setup():
    close = [100 * math.exp(-0.003 * i) for i in range(300)]
    b = Bars(close, [c * 1.01 for c in close], [c * 0.99 for c in close], [1e6] * 300)
    t = technicals(b)
    assert not t["setup"]["near_breakout"] and not t["trend_template"]["above_50_150_200"]


def facts(frames_rev, frames_ni, frames_eps):
    def unit(d):
        return [{"frame": f, "val": v} for f, v in d.items()]

    return {"facts": {"us-gaap": {
        # An old revenue tag that stopped in 2018 must not win over the current one.
        "Revenues": {"units": {"USD": unit({f"CY2017Q{q}": 5 for q in range(1, 5)} | {"CY2018Q1": 6})}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": unit(frames_rev)}},
        "NetIncomeLoss": {"units": {"USD": unit(frames_ni)}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": unit(frames_eps)}},
    }}}


async def test_fundamentals_use_latest_tag_and_growth(monkeypatch):
    rev = {"CY2025Q1": 100, "CY2025Q2": 100, "CY2025Q3": 110, "CY2026Q1": 120, "CY2026Q2": 130}
    ni = {"CY2025Q1": 10, "CY2025Q2": 10, "CY2025Q3": 11, "CY2026Q1": 12, "CY2026Q2": 20}
    eps = {"CY2025Q1": 1, "CY2025Q2": 1.0, "CY2025Q3": 1.1, "CY2026Q1": 1.2, "CY2026Q2": 2.0}

    async def fake_get(self, url, params=None, headers=None):
        return httpx.Response(200, json=facts(rev, ni, eps))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    async with data.client() as c:
        f = await data.fundamentals(c, 1)
    assert f["latest_quarter"] == "CY2026Q2"
    assert f["revenue_growth_yoy_pct"] == 30.0 and f["eps_growth_yoy_pct"] == 100.0
    assert f["revenue_growth_prior_quarter_pct"] == 20.0 and f["net_margin_pct"] == 15.4
    score, notes = scan_mod.fundamental_score(f)
    assert score == 100 and any("accelerating" in n for n in notes)


async def test_scan_ranks_and_tools_registered(monkeypatch):
    good = uptrend_with_base()

    async def fake_history(client, symbol, rng="2y"):
        if symbol == "BAD":
            raise data.DataError("BAD: no price data")
        return good

    async def fake_universe(client, top):
        return [{"ticker": "GOOD", "cik": 1, "name": "Good Co"}, {"ticker": "BAD", "cik": 2, "name": "Bad Co"}]

    async def fake_fund(client, cik):
        return {"latest_quarter": "CY2026Q2", "revenue_growth_yoy_pct": 30.0, "eps_growth_yoy_pct": 40.0, "net_margin_pct": 10.0}

    monkeypatch.setattr(data, "history", fake_history)
    monkeypatch.setattr(data, "universe", fake_universe)
    monkeypatch.setattr(data, "fundamentals", fake_fund)
    report = await scan_mod.scan(top=2)
    assert report["failed"] == ["BAD"] and report["scanned"] == 1
    top = report["breakout_candidates"][0]
    assert top["ticker"] == "GOOD" and top["fundamental"]["score"] == 85 and top["score"] > 0
    text = scan_mod.summary(report)
    assert "GOOD Good Co" in text and "not financial advice" in text
    assert {"stock_analyze", "stock_screen"} <= set(CATALOG)
    doc = scan_mod.report_doc(report)
    assert doc["kind"] == "stock_scan" and doc["items"][0]["ticker"] == "GOOD" and doc["items"][0]["fundamental"]


@pytest.mark.parametrize("status", [404, 500])
async def test_history_errors(monkeypatch, status):
    async def fake_get(self, url, params=None, headers=None):
        return httpx.Response(status, text="no")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    async with data.client() as c:
        with pytest.raises(data.DataError):
            await data.history(c, "XYZ")
