# Build log: key decisions

A record of the choices made while building FINN with an AI coding agent (Claude), and why. Pair this with the exported conversation for the "AI build history" deliverable.

## 27 Oct: plan
- Read the brief and glossary; proposed a plan (push digest + alerts, pull dossier with Guidance vs delivered as the flagship) and waited for approval.
- Adopted the user's mockup (dark navy sidebar and hero, light content panels, blue accent) as the visual direction.

## 27 Oct: build
- **Thin stack:** FastAPI + SQLAlchemy + Next.js. SQLite locally (zero setup), Postgres when deployed. No Redis, queue or vector DB: nothing in the requirements justified them.
- **Exchange access:** BSE as primary because its JSON includes a category field and it blocks less than NSE; NSE as fallback. Polite polling, everything stored, so the UI never depends on a live call to an exchange.
- **Rules-first classification:** about 30 ordered regex rules map BSE subjects to ENAM's taxonomy with a `subtype` (results filing vs board-meeting notice vs newspaper ad). Only unmatched filings reach the model. This alone removes most AI spend.
- **Results extraction:** Indian results statements print current quarter, previous quarter and year-ago quarter side by side, so one filing yields QoQ and YoY. The model only transcribes the table (relevant pages only, as a PDF subset). Code picks columns by period-end date, converts units and computes EBITDA and growth.
- **Management bios from the filing:** SEBI requires a brief profile of appointed directors and KMP in the disclosure. That is primary, legal and free, unlike scraping LinkedIn.
- **Guidance vs delivered:** quotes are verified against the transcript text; numeric verdicts are decided in code, using year-to-date actuals until the year ends. Only qualitative promises are judged by the model, and those are labelled.
- **Grounding check:** a cheap deterministic test that every number in an AI sentence appears in the source it cites. It catches the most damaging failure (made-up figures) without a second model call.
- **Sample mode:** the build environment could not reach Yahoo, BSE, NSE or Gemini, so the UI was developed against synthetic fixtures. These live in a separate database, every item is marked "[Sample]", and a banner shows on every screen.
- **Testing:** 30 unit tests cover the maths (signs, units, column selection), classification rules, alert de-duplication, grounding, guidance verdicts, retrieval and the full results-extraction path with the model mocked, plus parsers for the BSE and screener formats.
- **Design QA:** screenshot passes at 1440 px and 390 px, light and dark. Fixed: results table clipping QoQ/YoY on phones, company header squeezing the price, a sample banner overlapping the sidebar, an overflowing "routine filings" line, and price/volume alerts for the same stock-day showing twice.

## 27 Oct: news + Gemini setup
- Added real news headlines (Google News RSS, no key) as a clearly separated, secondary layer: Home "In the news" and a per-company News tab. Same story from several publishers is grouped (stemmed word overlap). Relevance uses the names headlines actually use (e.g. "L&T", "HUL") so "Reliance Power" doesn't show up under Reliance Industries. News never enters the research pipeline.
- Added an in-app "Connect Google Gemini" box: the key is tested against Google before it's saved to backend/.env, invalid keys fail fast, and the endpoint only accepts requests from the local machine or network.

## 27 Oct: first run on real data, deployment
- **Ran it for real** on the developer's Mac: Yahoo prices worked; BSE and NSE both returned 403 (bot protection) for every request. Decided not to work around the protection (the brief asks for polite use of unofficial endpoints).
- **Deployed on free tiers:** Neon Postgres (Singapore), Render backend (Singapore, next to the database: ~1 ms per query vs ~150 ms from India), Vercel frontend. The local SQLite data was copied into Neon table by table with matching row counts.
- **Gemini on a new key:** Google retired `gemini-2.x` for new keys, so the configured fallbacks were dead and a busy main model (503) made every dossier lose its written sections after ~2 minutes of retries. Fallbacks now point at current models, a busy model gets one quick retry before the next is tried, and a used-up daily quota (the free tier allows ~20 requests/day per Flash model) skips that model until Google's reset time.
- **Smaller fixes from real use:** prices for any ticker on first visit; "hi" in Ask FINN gets a hint without a model call; portfolio add by shares or ₹ amount (converted in code at the last close), edit and remove; company logos (logo.dev, initials as fallback); a *Source* box on every alert and filing; the Home tiles counted price alerts as announcements; saving prices did one query per day (~500 round trips for a new stock), now one per company.
- **A test-isolation bug:** a new test file imported FINN before the others switched to a temporary database, so tests wrote a fake company into the real database. Found, rows removed, and `tests/conftest.py` now isolates every test.

## 27–28 Oct: getting primary filings despite the blocks
- **screener.in as the route to BSE documents.** A company's screener page lists its latest BSE filings (own title, exact time, original BSE PDF), per-quarter links that redirect to each results filing on BSE, and its concall transcripts. FINN uses only those links and reads the BSE documents themselves, so the evidence stays primary; screener's numbers and summaries are never used. Each item says it was found through screener.
- **Considered and rejected:** Yahoo Finance for announcements (no management changes, orders, transcripts or results PDFs, and its numbers are secondary, which the brief rules out for research); NSE's RSS feed (no response).
- **Where collection runs.** BSE, NSE and screener also block Render, so filings are collected into the shared database by a collector (a laptop, or a GitHub Actions workflow) and the site shows what's there. Rebuilds reuse documents found earlier, and a dossier built where sources are blocked says so instead of looking thin.
- **Tuned on 100 real filings:** board-meeting outcomes without "results" in the title, "Bagging/receiving of order(s)", IPOs of subsidiaries, CP repayments (routine), analyst presentations, and unread management changes (were scored 20 and hidden).
- **Caught a misread number with arithmetic.** On a scanned Infosys filing the model took employee cost (25,287) as last quarter's revenue, giving "+94.7% QoQ". Code now checks revenue + other income = total income for every column and either recomputes revenue from validated totals (saying so) or shows n/a. Also made page selection tolerant of poor scans (Maruti) and told the model to use the standalone P&L when the consolidated one isn't in the pages.
- **Dossier builds on real documents** (6 results filings and up to 35 transcripts each) exposed three crashes: a DB transaction held open across long model calls (Neon dropped it), model output wrapped in a list, and guidance fields longer than their columns. All fixed.
- **Guidance vs delivered:** 19 of 46 items were "pending" only because management didn't name a period. They're now judged on the fiscal year they refer to (a Q4 call talks about the next year), and the verdict says it assumed this.
- **Demo safety:** price-alert threshold back to the 4% default (0.5% had produced 168 alerts); lists now show stored alerts that pass the current thresholds; the website builds at most 6 dossiers a day to protect the free AI quota.
