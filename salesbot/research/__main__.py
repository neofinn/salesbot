"""`python -m salesbot.research scan|analyze` - run the stock research engine from a shell."""

from __future__ import annotations

import argparse
import asyncio
import json

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
    args = p.parse_args()
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
