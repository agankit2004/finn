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
