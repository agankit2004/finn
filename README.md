# FINN — Financial Investment Agent

A mobile-first web app for investors tracking Indian listed companies. FINN filters the daily flood of exchange filings and price moves down to the few that matter, explains why, and researches any NSE company from its own documents.

- **Push.** A ranked brief of every filing across your portfolio for the window you choose. Routine paperwork is collapsed. Results filings become a Revenue / EBITDA / PBT / PAT table with QoQ and YoY. Management changes show who the person is, from the filing itself. Price and volume alerts fire on thresholds you set.
- **Pull.** A research dossier for any NSE ticker, built only from primary documents: results filings, concall transcripts and the annual report. Every claim links to the page it came from. The flagship view, **Guidance vs delivered**, checks what management promised in the last four calls against what the results show.

**Live prototype:** https://finn-plum.vercel.app (backend: https://finn-api-ds9a.onrender.com/api/health). The free backend sleeps when idle, so the first page can take ~30 s.

---

## 1. What you need

| Need | Why | Where |
|---|---|---|
| **Python 3.10+** | Backend | python.org/downloads (macOS: `brew install python@3.12`) |
| **Node.js 20+** | Frontend | nodejs.org (macOS: `brew install node`) |
| **Gemini API key** (free) | Reading filings, research, Q&A | aistudio.google.com/apikey → *Create API key* |
| Groq API key (optional, free) | Fallback for text-only AI tasks | console.groq.com/keys |
| logo.dev key (optional, free) | Company logos; without it, logos come from site icons and many show initials | logo.dev → sign up → copy the **publishable** key (`pk_…`) into `LOGO_DEV_TOKEN` |

Without a Gemini key, prices, filings, news, ranking and alerts still work. Results tables, summaries and research need the key.

### Connecting Google Gemini
1. Go to **aistudio.google.com/apikey**, sign in with a Google account, click **Create API key**, and copy it (starts with `AIza`). No billing needed for the free tier.
2. Either:
   - **In the app:** Settings → *Google Gemini* → paste → **Connect**. FINN tests the key with Google and saves it to `backend/.env` (works from your own computer or Wi-Fi only), or
   - **By hand:** put `GEMINI_API_KEY=AIza...` in `backend/.env` and restart `./start.sh`.
3. Check: `./start.sh check` shows **OK  Gemini API**, and Settings shows *Connected*.

FINN calls Gemini's REST API directly (`generativelanguage.googleapis.com`). The model names default to Google's `gemini-flash-lite-latest` (bulk reading) and `gemini-flash-latest` (research). If Google renames them, set `GEMINI_FAST_MODEL` / `GEMINI_SMART_MODEL` in `.env`. When a model is busy (503) or its daily free quota is used up, FINN moves down `GEMINI_FALLBACK_MODELS` (default `gemini-3.6-flash, gemini-3.5-flash, gemini-3.5-flash-lite, gemini-flash-lite-latest`) and skips a used-up model until Google's reset time.

## 2. Install and run (about 3 minutes)

```bash
cd finn
./start.sh check     # 1) tests Yahoo, BSE, NSE, screener.in and Gemini from YOUR machine
./start.sh           # 2) installs everything on first run, then starts FINN
```

Windows: use `start.bat check`, then `start.bat`.

The first run creates `backend/.env`. Open it and paste your key:

```
GEMINI_API_KEY=your-key-here
FINN_USER_NAME=Aditya
```

Then stop FINN (Ctrl+C) and run `./start.sh` again.

Open **http://localhost:3000**. On first start FINN creates the 18-company demo portfolio, fetches about two years of prices and pulls the last 10 days of filings. This takes 1–3 minutes, and the Home screen fills in as data arrives (Settings shows progress).

### On your phone
Keep the laptop and phone on the same Wi-Fi network. `start.sh` prints a link like `http://192.168.1.23:3000`; open it on the phone. To install it like an app, use Share → *Add to Home Screen*.

### Just want to see the interface?
`./start.sh sample` runs with **synthetic, clearly-labelled sample data** (a banner says so on every screen). It uses its own database file, so it never mixes with real data.

## 3. How to check it works

1. `./start.sh check` should show **OK** for Yahoo, BSE, Google News and Gemini (NSE and screener are fallbacks; OK is a bonus).
2. **Home:** the hero shows portfolio value with an end-of-day date. *Top updates* lists ranked filings, with "N routine filings hidden" at the bottom.
3. Tap a **Results** item: a table of Revenue, EBITDA, PBT and PAT with QoQ/YoY and the page it came from. *Open filing* opens the exchange PDF.
4. **Alerts:** the default price move is 4%. Change it to 1% and save: alerts appear for any holding that moved more than 1% in recent sessions. Raise it again and the smaller ones drop out of the lists (they're kept, not deleted).
5. **Research:** search `ASIANPAINT` (not in the portfolio) → *Build research dossier*. In 2–5 minutes you get Overview, Financials, Guidance vs delivered and Ask FINN. Tap any small blue number to see the source passage and open the PDF at that page.
6. **Settings:** data-source health, last refresh times, and the AI usage ledger (calls, cache hits, tokens).
7. Backend tests: `cd backend && source .venv/bin/activate && python -m pytest -q` (56 tests, no network needed; the screener parser is tested on a saved copy of a real page).

Useful commands (run inside `backend/` with the venv active):

```bash
python -m scripts.refresh                    # one full refresh now
python -m scripts.refresh announcements --days 30
python -m scripts.refresh news
python -m scripts.refresh research TCS       # build a dossier from the terminal, with progress
```

---

## 4. How it works

```
 Yahoo (yfinance) ──┐                         ┌── rules classifier (most filings, no AI)
 BSE / NSE filings ─┼─ ingest → dedupe ──────►├── importance score (explainable)
 Filing PDFs ───────┘   (unique source ids,   ├── results → Gemini Flash-Lite reads table → CODE computes EBITDA, QoQ, YoY
                         content hashes)      ├── mgmt change → name, role, profile from the filing
                                              └── alerts: price ±X%, volume N×, categories you track
                                                       │
 Research (any NSE ticker):                            ▼
   BSE filings + screener links → results filings, transcripts, annual report
   → extract metrics (cached) → chunk with page numbers → BM25 retrieval
   → guidance extracted with verbatim quotes → verdicts computed in CODE
   → one Gemini Flash call writes the narrative, citing sources → grounding check
                                                       │
                     SQLite (local) / Postgres (deployed) ◄── FastAPI ◄── Next.js (mobile-first)
```

**Backend** (`backend/finn/`): FastAPI, SQLAlchemy, PyMuPDF.
- `sources/`: Yahoo, BSE/NSE, screener links, PDF cache.
- `pipeline/`: classification, scoring, financial maths, enrichment, alerts, ingestion.
- `research/`: chunking and retrieval, guidance, dossier, Q&A, grounding.
- `ai/`: Gemini client with caching and a token ledger.

**Frontend** (`frontend/src/`): Next.js 16, Tailwind 4, Recharts, SWR. One responsive codebase: a sidebar on laptop, a bottom tab bar on phone.

### Data sources and their honest limits
- **Prices:** Yahoo Finance via `yfinance` (`RELIANCE.NS`). **End-of-day only**, labelled as such everywhere. If Yahoo fails, FINN tries NSE's official daily bhavcopy file. Stored prices keep working through an outage, and a "stale" flag appears if the latest session is missing.
- **Announcements:** BSE's corporate-filings JSON (the endpoint behind bseindia.com), then NSE's, then the filings listed on the company's **screener.in** page. **None is an official API.** In October 2026 BSE and NSE refused FINN's requests (403) from every machine tried, so the screener route does the work: it lists each company's latest BSE filings with their own title, exact filing time and the **original BSE PDF**, which is what FINN reads. Screener's one-line summaries are ignored, and each item's *Source* box says it was found through screener. FINN makes one request per company per poll with a 3-second gap, a circuit breaker per source, and stores everything; the same BSE document found two ways is stored once (matched on BSE's file name).
- **Fundamentals:** results filings, concall transcripts and annual reports. Screener's per-quarter links redirect to each quarter's results filing **on BSE**; its concall list links transcripts filed with the exchange. Screener's own numbers and tables are never used as evidence. Documents found by earlier builds are reused, so a rebuild on a machine that can't reach the sources never loses them.
- **Where the sources can be reached:** BSE, NSE and screener.in block most cloud servers (Render included), but work from a laptop. So filings are collected by a *collector* (a laptop running FINN, or the GitHub Actions workflow in §5) into the shared database, and the deployed site shows what's there. Dossiers built from the website when the sources are blocked say *Built with limited sources*.
- **News headlines:** Google News RSS per company (free, no key), searched with the names headlines actually use (L&T, HUL, Airtel…), filtered to headlines that name the company, and grouped when several publishers cover the same story. FINN stores only the headline, publisher, time and link. News appears on Home and each company's *News* tab, and is **never used as research evidence** (the brief requires primary sources for analysis).
- **Management background** comes from the profile companies must include in the appointment filing. FINN does not scrape LinkedIn (its terms forbid it); it offers a LinkedIn search link instead.

### AI design: cheap, cached, checked
- **Rules first.** BSE category + keyword rules classify most filings; only leftovers go to the model, 40 per call.
- **Model routing.** Flash-Lite for bulk extraction; Flash only for research writing and Q&A. Configurable in `.env`.
- **Numbers never come from the model.** The model reads values off the page; code normalises units (lakh → crore), picks QoQ/YoY columns **by date**, computes EBITDA, margins and growth, handles negative bases ("loss narrowed"), and runs consistency checks (PBT − tax ≈ PAT). For every column it uses, code checks **revenue + other income = total income**. If that fails but total income − expenses = PBT holds, revenue is recomputed as total income − other income and the card says so; otherwise revenue is shown as *n/a*. (This caught Infosys Q1 FY27 read off a scanned page as 25,287, its employee cost, instead of 48,211.)
- **Guidance verdicts.** Quotes must appear verbatim in the transcript or are flagged. Numeric targets are judged in code against the results; a target without a stated period is judged on the fiscal year it refers to (a Q4 call talks about the next year), and the verdict says that it assumed this.
- **Grounding.** Every AI sentence must cite source ids. FINN checks that each cited id exists and that **every number in the sentence appears in the cited source**. Failures are shown as *unverified*, not hidden.
- **Facts vs interpretation.** Tables say "computed by FINN"; narrative says "FINN's read"; guidance verdicts say whether code or the model decided.
- **Caching.** Every response is cached by input hash, so a filing costs tokens once. On the free tier the cost is ₹0; Settings shows the ledger.
- **Free-tier limits.** Gemini's free tier allows about 20 requests a day per Flash model. FINN skips a model whose daily quota is used up, and the website builds at most `FINN_MAX_API_BUILDS_PER_DAY` (default 6) dossiers a day; builds from the command line or collector aren't counted.

---

## 5. Deploy (free tiers)

1. **Database:** create a free Postgres at neon.tech and copy its connection string.
2. **Backend on Render:** *New → Blueprint* → pick this repo (uses `render.yaml`). Set `DATABASE_URL` and `GEMINI_API_KEY`. Copy the generated `FINN_REFRESH_SECRET`.
3. **Frontend on Vercel:** import the repo and set the root directory to `frontend`. Add env `NEXT_PUBLIC_API_URL=https://<your-render-app>.onrender.com`.
4. **Prices and wake-ups:** add the repository secret `FINN_API_URL` (and optionally `FINN_REFRESH_SECRET`). `.github/workflows/refresh.yml` calls the backend every 30 minutes in market hours: prices refresh and the free server stays awake.
5. **Filings (the collector).** BSE, NSE and screener.in block Render, so filings must be collected elsewhere into the same database:
   - **GitHub Actions:** add the secrets `DATABASE_URL` and `GEMINI_API_KEY`. `.github/workflows/collect.yml` runs every 30 minutes in market hours; its first step prints which sources answer from GitHub's machines.
   - **A laptop:** put Neon's `DATABASE_URL` in `backend/.env` and keep `./start.sh` running (it polls every 30 minutes), or run `python -m scripts.refresh announcements` and `python -m scripts.refresh enrich`. Build dossiers here too: `python -m scripts.refresh research TCS`.

Free-tier caveats: Render sleeps after 15 idle minutes, so the first request takes about 30 s. Gemini's free tier has per-minute and per-day limits (see *Free-tier limits* above).

---

## 6. Scope: what's in, what's left out

**In:** windowed digest with ranking and routine collapse; configurable price/volume/category alerts with per-stock overrides; results extraction with QoQ/YoY; management-change profiles; one-line summaries for material filings; research dossier for any NSE ticker (snapshot, trajectory, balance sheet, cash quality, guidance vs delivered, narrative vs numbers, bull/bear, grounded Q&A); light and dark themes; installable PWA.

**Deliberately left out:** live prices (no free licensed source); push notifications to the phone (alerts are in-app); bank-specific metrics such as NIM, GNPA and CASA (banks get an adapted results template and a note instead); multi-user accounts; vector embeddings (BM25 is enough at this scale; pgvector is the upgrade path); news and broker research (excluded on purpose for the pull side).

**Next:** licensed exchange feed; Web Push / WhatsApp delivery of alerts; sector-relative signals ("margin compressed while peers expanded"); embeddings + reranking for very long annual reports; bank and insurer templates; tracking guidance changes call over call.

*Not investment advice. Prices are end-of-day. Exchange data comes from unofficial public endpoints and may be incomplete.*
