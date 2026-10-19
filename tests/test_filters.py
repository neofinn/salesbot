import json

from salesbot.research import filters
from salesbot.research.technicals import Bars
from salesbot.store import AgentSpec
from salesbot.tools import CATALOG

ROWS = [
    {"ticker": "AAA", "name": "A", "price": 10, "rsi": 25, "off_high": 30, "score": 20, "ret_6m": -10, "rs_6m": -15,
     "above_50": False, "above_200": False, "near_breakout": False, "vol_ratio": 1.0},
    {"ticker": "BBB", "name": "B", "price": 50, "rsi": 62, "off_high": 1.5, "score": 90, "ret_6m": 40, "rs_6m": 25,
     "above_50": True, "above_200": True, "near_breakout": True, "vol_ratio": 2.5},
    {"ticker": "CCC", "name": "C", "price": 80, "rsi": 70, "off_high": 4, "score": 75, "ret_6m": 22, "rs_6m": 12,
     "above_50": True, "above_200": True, "near_breakout": True, "vol_ratio": None},
]


def test_validate_drops_unknown_and_bad_values():
    c = filters.validate({"min": {"rsi": "40", "bogus": 1, "price": "abc"}, "is": {"golden": "yes", "above_50": True},
                          "sort": "name", "limit": 999, "tickers": [" nvda ", ""]})
    assert c["min"] == {"rsi": 40.0} and c["is"] == {"above_50": True}
    assert c["sort"] == "score" and c["limit"] == 100 and c["tickers"] == ["NVDA"]


def test_apply_presets_and_bounds():
    assert [r["ticker"] for r in filters.apply(ROWS, filters.PRESETS["Near breakout"])] == ["BBB", "CCC"]
    assert [r["ticker"] for r in filters.apply(ROWS, filters.PRESETS["Oversold"])] == ["AAA"]
    assert [r["ticker"] for r in filters.apply(ROWS, filters.PRESETS["Strong momentum"])] == ["BBB", "CCC"]
    # rows missing the sort field go last; missing a bounded field excludes the row
    assert [r["ticker"] for r in filters.apply(ROWS, {"sort": "vol_ratio"})] == ["BBB", "AAA", "CCC"]
    assert [r["ticker"] for r in filters.apply(ROWS, {"min": {"vol_ratio": 0}})] == ["BBB", "AAA"]
    assert [r["ticker"] for r in filters.apply(ROWS, {"tickers": ["ccc"], "limit": 1})] == ["CCC"]


def test_row_from_bars_and_artifact_docs():
    n = 260
    close = [50 + i * 0.2 for i in range(n)]
    b = Bars(close=close, high=[c * 1.01 for c in close], low=[c * 0.99 for c in close], volume=[1_000_000] * n)
    r = filters.row("UP", "Up Co", b, close)
    assert r["above_50"] and r["above_200"] and r["golden"] and r["trend"] == 4
    assert set(r) == set(filters.FIELDS)
    docs = filters.artifact_docs({"generated_at": "now", "universe": "u", "count": 3, "disclaimer": "d", "rows": ROWS}, chunk=2)
    assert [d["id"] for d in docs] == ["meta", "c0", "c1"] and docs[0]["data"]["chunks"] == 2
    assert docs[2]["data"]["rows"] == [ROWS[2]]


async def test_stock_filter_tool_uses_cached_snapshot(team, fake):
    filters.save_cached(team.settings.data_dir, {"generated_at": "2026-10-19", "universe": "test", "disclaimer": "d", "rows": ROWS})
    await team.store.add_agent(AgentSpec("analyst", "Analyst", "You screen stocks.", "fake:test", ["stock_filter"]))
    fake.script("You screen stocks", ("", [("stock_filter", {"preset": "Near breakout", "max": {"rsi": 65}})]), ("BBB.", []))
    assert await team.delegate("analyst", "stocks about to break out that aren't overbought") == "BBB."
    call = [c for c in fake.calls if "You screen stocks" in c[0]][-1]
    assert "Understand it first" in call[0]  # every hired bot gets the understand-first guidance
    out = json.loads(call[1][-1].tool_results[0].content)
    assert [s["ticker"] for s in out["stocks"]] == ["BBB"] and out["data_as_of"] == "2026-10-19"
    assert "stock_filter" in CATALOG
