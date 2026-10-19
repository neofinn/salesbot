"""`python -m salesbot.research scan|analyze` - run the stock research engine from a shell."""

from __future__ import annotations

import argparse
import asyncio
import json

from . import filters
from .screener import analyze, report_doc, scan, summary


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m salesbot.research")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="scan for stocks near a breakout")
    s.add_argument("--top", type=int, default=300, help="how many of the largest US companies to scan")
    s.add_argument("--tickers", default="", help="comma-separated tickers instead of the default universe")
    s.add_argument("--limit", type=int, default=15)
    s.add_argument("--json", dest="json_out", default="", help="also write the full report to this file")
    s.add_argument("--report-doc", default="", help="also write the report shaped for the MyOps page's Reports tab")
    a = sub.add_parser("analyze", help="technical + fundamental read on one ticker")
    a.add_argument("ticker")
    n = sub.add_parser("snapshot", help="screener metrics for the whole universe")
    n.add_argument("--top", type=int, default=600)
    n.add_argument("--tickers", default="")
    n.add_argument("--out", default="", help="write the snapshot (JSON) here")
    n.add_argument("--docs", default="", help="write it as documents for the MyOps page's screener collection")
    n.add_argument("--preset", default="Near breakout", help=f"print this screen: {', '.join(filters.PRESETS)}")
    args = p.parse_args()
    if args.cmd == "snapshot":
        snap = asyncio.run(filters.snapshot(args.top, [t for t in args.tickers.split(",") if t] or None))
        if args.out:
            with open(args.out, "w") as fh:
                json.dump(snap, fh)
        if args.docs:
            with open(args.docs, "w") as fh:
                json.dump(filters.artifact_docs(snap), fh)
        hits = filters.apply(snap["rows"], filters.PRESETS.get(args.preset, {}))
        print(f"{snap['count']} stocks ({snap['universe']}, {snap['seconds']}s, {len(snap['failed'])} failed). {args.preset}:")
        for r in hits:
            print(f"  {r['ticker']:6} {r['name'][:28]:28} ${r['price']:<9} score {r['score']:<3} RSI {r['rsi']} "
                  f"{r['off_high']}% off high, {r['to_pivot']}% below pivot")
        return
    if args.cmd == "analyze":
        print(json.dumps(asyncio.run(analyze(args.ticker)), indent=2))
        return
    report = asyncio.run(scan(args.top, [t for t in args.tickers.split(",") if t] or None, args.limit))
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump(report, fh, indent=2)
    if args.report_doc:
        with open(args.report_doc, "w") as fh:
            json.dump(report_doc(report), fh, indent=2)
    print(summary(report))


if __name__ == "__main__":
    main()
