"""Market data: daily prices from Yahoo Finance's chart API and financials from SEC EDGAR."""

from __future__ import annotations

import asyncio
import csv
import io
import os
import re
import time
from typing import Any

import httpx

from .technicals import Bars

YAHOO = "https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
YAHOO_SPARK = "https://{host}.finance.yahoo.com/v7/finance/spark"
NSE_EQUITIES = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_NIFTY500 = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
# SEC asks automated clients to identify themselves with a contact.
SEC_UA = os.environ.get("SEC_USER_AGENT", "MyOps stock research contact@example.com")


class DataError(Exception):
    pass


async def history(client: httpx.AsyncClient, symbol: str, rng: str = "2y") -> Bars:
    # Yahoo rate-limits bursts (429): back off and alternate between its two API hosts.
    for attempt in range(4):
        resp = await client.get(
            YAHOO.format(host=("query1", "query2")[attempt % 2], symbol=symbol),
            params={"range": rng, "interval": "1d"},
            headers={"User-Agent": SEC_UA},
        )
        if resp.status_code != 429:
            break
        await asyncio.sleep(1.5 * (attempt + 1))
    if resp.status_code != 200:
        raise DataError(f"{symbol}: price data unavailable ({resp.status_code})")
    try:
        res = resp.json()["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise DataError(f"{symbol}: no price data") from exc
    rows = [
        (c, h, lo, v)
        for c, h, lo, v in zip(q.get("close", []), q.get("high", []), q.get("low", []), q.get("volume", []))
        if None not in (c, h, lo, v)
    ]
    if len(rows) < 60:
        raise DataError(f"{symbol}: not enough price history")
    c, h, lo, v = map(list, zip(*rows))
    return Bars(close=c, high=h, low=lo, volume=v)


async def universe(client: httpx.AsyncClient, top: int) -> list[dict[str, Any]]:
    """The largest US-listed companies, in SEC's order (roughly by market value)."""
    resp = await client.get(SEC_TICKERS, headers={"User-Agent": SEC_UA})
    if resp.status_code != 200:
        raise DataError(f"SEC ticker list unavailable ({resp.status_code})")
    seen, out = set(), []
    for row in resp.json().values():
        t = str(row.get("ticker", "")).upper()
        # One line per company; skip warrants/units/preferreds (5-letter W/U/P suffixes etc.).
        if row["cik_str"] in seen or not re.fullmatch(r"[A-Z]{1,5}(-[A-Z])?", t) or (len(t) == 5 and t[-1] in "WUPRZ"):
            continue
        seen.add(row["cik_str"])
        out.append({"ticker": t, "cik": int(row["cik_str"]), "name": row.get("title", "")})
        if len(out) >= top:
            break
    return out


async def _text(client: httpx.AsyncClient, url: str, what: str) -> str:
    resp = await client.get(url, headers={"User-Agent": SEC_UA})
    if resp.status_code != 200:
        raise DataError(f"{what} unavailable ({resp.status_code})")
    return resp.text


async def nse_universe(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Every equity listed on India's NSE (EQ and BE series), with the Nifty 500 industry where known.
    Tickers are Yahoo symbols (RELIANCE.NS)."""
    sectors: dict[str, str] = {}
    try:
        for row in csv.DictReader(io.StringIO(await _text(client, NSE_NIFTY500, "Nifty 500 list"))):
            sectors[row["Symbol"].strip()] = row["Industry"].strip()
    except DataError:
        pass  # sectors are a bonus; the equity list is what matters
    out = []
    for row in csv.DictReader(io.StringIO(await _text(client, NSE_EQUITIES, "NSE equity list"))):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        if row.get("SERIES") not in ("EQ", "BE"):
            continue
        sym = row["SYMBOL"]
        out.append({"ticker": f"{sym}.NS", "name": row.get("NAME OF COMPANY", ""), "sector": sectors.get(sym, "")})
    return out


SKIP_NAMES = re.compile(r"\b(warrants?|units?|rights?|preferred|depositary shares? representing|notes due|debentures?|%)\b", re.I)


async def us_listed(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Common stocks listed on US exchanges (Nasdaq, NYSE, NYSE American, Cboe), no ETFs or test issues."""
    out, seen = [], set()
    for url, sym_col, name_col in ((NASDAQ_LISTED, "Symbol", "Security Name"), (OTHER_LISTED, "ACT Symbol", "Security Name")):
        lines = (await _text(client, url, "US symbol directory")).splitlines()
        for row in csv.DictReader(lines[:-1], delimiter="|"):  # the last line is a file timestamp
            sym = (row.get(sym_col) or "").strip()
            if (row.get("ETF") == "Y" or row.get("Test Issue") == "Y" or not re.fullmatch(r"[A-Z]{1,5}", sym)
                    or SKIP_NAMES.search(row.get(name_col) or "") or sym in seen):
                continue
            seen.add(sym)
            out.append({"ticker": sym, "name": (row.get(name_col) or "").split(" - ")[0].replace(" Common Stock", "").strip(), "sector": ""})
    return out


async def quotes(client: httpx.AsyncClient, symbols: list[str]) -> dict[str, tuple[float, float]]:
    """Last price and volume for many symbols at once (Yahoo spark, 20 symbols per call)."""
    async def batch(chunk: list[str]) -> dict[str, tuple[float, float]]:
        for attempt in range(4):
            resp = await client.get(YAHOO_SPARK.format(host=("query1", "query2")[attempt % 2]),
                                    params={"symbols": ",".join(chunk), "range": "1d", "interval": "1d"},
                                    headers={"User-Agent": SEC_UA})
            if resp.status_code != 429:
                break
            await asyncio.sleep(1.5 * (attempt + 1))
        if resp.status_code != 200:
            raise DataError(f"quotes unavailable ({resp.status_code})")
        out = {}
        for r in (resp.json().get("spark") or {}).get("result") or []:
            try:
                meta = r["response"][0]["meta"]
                out[r["symbol"]] = (float(meta["regularMarketPrice"]), float(meta.get("regularMarketVolume") or 0))
            except (KeyError, IndexError, TypeError, ValueError):
                continue
        return out

    found: dict[str, tuple[float, float]] = {}
    for res in await gather_limited([batch(symbols[i:i + 20]) for i in range(0, len(symbols), 20)]):
        if isinstance(res, dict):
            found.update(res)
    return found


async def cik_for(client: httpx.AsyncClient, ticker: str) -> tuple[int, str] | None:
    resp = await client.get(SEC_TICKERS, headers={"User-Agent": SEC_UA})
    if resp.status_code != 200:
        return None
    for row in resp.json().values():
        if str(row.get("ticker", "")).upper() == ticker.upper():
            return int(row["cik_str"]), row.get("title", "")
    return None


REVENUE = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"]


async def fundamentals(client: httpx.AsyncClient, cik: int) -> dict[str, Any]:
    """Latest-quarter growth and margins from the company's own XBRL filings."""
    resp = await client.get(SEC_FACTS.format(cik=cik), headers={"User-Agent": SEC_UA})
    if resp.status_code != 200:
        raise DataError(f"SEC financials unavailable ({resp.status_code})")
    facts = resp.json().get("facts", {}).get("us-gaap", {})

    def key(frame: str) -> tuple[int, int]:
        return int(frame[2:6]), int(frame[-1])

    def quarters(*names: str, unit: str = "USD") -> dict[str, float]:
        """Quarterly values of whichever concept the company reports most recently
        (companies switch revenue tags over the years, so the first match can be stale)."""
        best: dict[str, float] = {}
        for name in names:
            vals = facts.get(name, {}).get("units", {}).get(unit, [])
            q = {x["frame"]: x["val"] for x in vals if re.fullmatch(r"CY\d{4}Q\d", str(x.get("frame", "")))}
            if len(q) >= 5 and (not best or key(max(q, key=key)) > key(max(best, key=key))):
                best = q
        return best

    def yoy(q: dict[str, float]) -> tuple[str | None, float | None, float | None]:
        if not q:
            return None, None, None
        last = max(q, key=key)
        prev = f"CY{int(last[2:6]) - 1}Q{last[-1]}"
        growth = (q[last] / q[prev] - 1) * 100 if prev in q and q[prev] else None
        return last, q[last], growth

    rev_q = quarters(*REVENUE)
    ni_q = quarters("NetIncomeLoss")
    eps_q = quarters("EarningsPerShareDiluted", "EarningsPerShareBasic", unit="USD/shares")
    gp_q = quarters("GrossProfit")
    period, rev, rev_g = yoy(rev_q)
    ni_period, ni, ni_g = yoy(ni_q)
    if ni_period != period:
        ni = ni_g = None
    _, eps, eps_g = yoy(eps_q)
    # Growth on a negative base is meaningless; report it only when last year's number was positive.
    if eps_q and period and eps_q.get(f"CY{int(period[2:6]) - 1}Q{period[-1]}", 0) <= 0:
        eps_g = None
    out = {
        "latest_quarter": period,
        "revenue": rev, "revenue_growth_yoy_pct": _r(rev_g),
        "net_income": ni, "net_income_growth_yoy_pct": _r(ni_g),
        "eps_diluted": eps, "eps_growth_yoy_pct": _r(eps_g),
        "net_margin_pct": _r(ni / rev * 100 if ni is not None and rev else None),
        "gross_margin_pct": _r(gp_q.get(period) / rev * 100 if period and gp_q.get(period) and rev else None),
    }
    # XBRL quarterly frames lag or stop for some filers; flag anything older than ~18 months.
    if period:
        y, q = key(period)
        now = time.gmtime()
        age_q = (now.tm_year - y) * 4 + ((now.tm_mon - 1) // 3 + 1) - q
        out["stale"] = age_q > 6
    # Revenue acceleration: is growth this quarter faster than the quarter before?
    if rev_q and period:
        q = int(period[-1]); y = int(period[2:6])
        prior = f"CY{y if q > 1 else y - 1}Q{q - 1 if q > 1 else 4}"
        prior_ly = f"CY{int(prior[2:6]) - 1}Q{prior[-1]}"
        if prior in rev_q and prior_ly in rev_q and rev_q[prior_ly]:
            out["revenue_growth_prior_quarter_pct"] = _r((rev_q[prior] / rev_q[prior_ly] - 1) * 100)
    return out


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 1)


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=25, follow_redirects=True, limits=httpx.Limits(max_connections=6))


async def gather_limited(coros: list, limit: int = 6) -> list:
    sem = asyncio.Semaphore(limit)

    async def run(c):
        async with sem:
            try:
                return await c
            except Exception as exc:  # one bad symbol must not stop the scan
                return exc

    return await asyncio.gather(*(run(c) for c in coros))
