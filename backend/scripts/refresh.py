"""Run one ingestion pass from the command line.

    python -m scripts.refresh            # prices + announcements + AI enrichment
    python -m scripts.refresh prices
    python -m scripts.refresh announcements --days 10
    python -m scripts.refresh research TCS   # build a research dossier (waits until done)
    python -m scripts.refresh check          # test which data sources are reachable from this machine
"""
import argparse
import json
import time

from finn.db import init_db


def check() -> None:
    from datetime import date, timedelta

    from finn import config
    from finn.sources import announcements, prices, screener
    from finn.sources.http import SourceError

    def run(name, fn):
        t = time.time()
        try:
            out = fn()
            print(f"  OK    {name:<28} {out}  ({time.time() - t:.1f}s)")
        except (SourceError, Exception) as e:  # noqa: BLE001
            print(f"  FAIL  {name:<28} {str(e)[:150]}")

    print("Checking data sources from this machine...")
    run("Yahoo Finance (yfinance)", lambda: f"{len(prices.fetch_history(['RELIANCE'], '5d').get('RELIANCE', []))} days of RELIANCE.NS")
    end = date.today()
    run("BSE announcements", lambda: f"{len(announcements.fetch_bse('500325', end - timedelta(days=7), end))} RELIANCE filings (7d)")
    run("NSE announcements", lambda: f"{len(announcements.fetch_nse('RELIANCE', end - timedelta(days=7), end))} RELIANCE filings (7d)")
    run("screener.in", lambda: (lambda d: f"{len(d['transcripts'])} transcripts, {len(d['annual_reports'])} annual reports")(screener.discover("RELIANCE")))
    from finn.sources import news

    run("Google News (headlines)", lambda: f"{len(news.fetch('RELIANCE', 'Reliance Industries Ltd'))} RELIANCE headlines (7d)")
    if config.GEMINI_API_KEY:
        from finn.ai.llm import generate_json

        run("Gemini API", lambda: generate_json("check", "Reply with JSON.", 'Return {"ok": true}', use_cache=False))
    else:
        print("  SKIP  Gemini API                   GEMINI_API_KEY not set in backend/.env")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("what", nargs="?", default="all", choices=["all", "prices", "announcements", "news", "enrich", "research", "check"])
    p.add_argument("symbol", nargs="?")
    p.add_argument("--days", type=int, default=None)
    a = p.parse_args()
    init_db()
    if a.what == "check":
        return check()
    from finn.pipeline import ingest

    ingest.bootstrap()
    if a.what == "prices":
        out = ingest.refresh_prices()
    elif a.what == "announcements":
        out = ingest.refresh_announcements(days_back=a.days)
    elif a.what == "news":
        out = ingest.refresh_news()
    elif a.what == "enrich":
        out = ingest.enrich_pending(limit=100)
    elif a.what == "research":
        if not a.symbol:
            raise SystemExit("usage: python -m scripts.refresh research TCS")
        from finn.db import Job, session_scope
        from finn.research import build

        jid = build.start(a.symbol, force=True)
        last = None
        while True:
            with session_scope() as s:
                j = s.get(Job, jid)
                if j.step != last:
                    print(f"[{j.progress:4.0%}] {j.step}")
                    last = j.step
                if j.status in ("done", "failed"):
                    for line in j.log or []:
                        print("   ·", line["msg"])
                    if j.error:
                        print("ERROR:", j.error.splitlines()[0])
                    break
            time.sleep(2)
        return
    else:
        out = ingest.refresh_all()
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
