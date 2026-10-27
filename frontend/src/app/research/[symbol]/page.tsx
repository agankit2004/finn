"use client";
import clsx from "clsx";
import { ArrowLeft, Check, ExternalLink, FileText, Loader2, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AskPanel } from "@/components/ask";
import { NewsPanel } from "@/components/news";
import { RangeChart } from "@/components/charts";
import { FeedRow } from "@/components/feed";
import { Note } from "@/components/item-detail";
import { BullBear, BusinessSection, FinancialsSection, GuidanceLedger, SnapshotTiles, StatementList, StatementText } from "@/components/research";
import { Button, Delta, Empty, ErrorBox, Panel, Skeleton } from "@/components/ui";
import { fileUrl, post, useApi, type Cite, type FeedItem, type Job, type Status } from "@/lib/api";
import { ago, crore, dateShort, num, pct, price } from "@/lib/format";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "financials", label: "Financials" },
  { key: "guidance", label: "Guidance vs delivered" },
  { key: "announcements", label: "Announcements" },
  { key: "news", label: "News" },
  { key: "documents", label: "Documents" },
  { key: "ask", label: "Ask FINN" },
] as const;
type Tab = (typeof TABS)[number]["key"];

const DOC_LABEL: Record<string, string> = { results: "Results filing", transcript: "Concall transcript", annual_report: "Annual report", presentation: "Presentation" };

function BuildPanel({ symbol, job, onStart, llm }: { symbol: string; job?: Job | null; onStart: () => void; llm: boolean }) {
  const building = job && (job.status === "queued" || job.status === "running");
  return (
    <Panel>
      {building ? (
        <div>
          <div className="flex items-center gap-2 text-[14px] font-semibold"><Loader2 className="size-4 animate-spin text-accent" />Building the dossier for {symbol}</div>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-accent transition-all duration-700" style={{ width: `${Math.max(4, (job!.progress ?? 0) * 100)}%` }} />
          </div>
          <p className="mt-2 text-[13px]">{job!.step}</p>
          <ul className="mt-3 space-y-1 text-[12px] text-muted">{job!.log.map((l) => <li key={l.t + l.msg}>{l.msg}</li>)}</ul>
          <p className="mt-3 text-[12px] text-faint">This takes 2–5 minutes the first time: FINN downloads the filings, reads each results statement and transcript, then writes the dossier. After that it's cached.</p>
        </div>
      ) : (
        <div className="max-w-2xl">
          <p className="text-[15px] font-semibold">No research dossier for {symbol} yet</p>
          <p className="mt-1 text-[13px] text-muted">
            FINN will find this company's last six results filings, last four concall transcripts and latest annual report on the exchange,
            extract the numbers, compare management's guidance with what was delivered, and write it up with page references.
            Only the company's own documents are used.
          </p>
          {job?.status === "failed" && <Note tone="warn" className="mt-3">The last build failed: {job.error}</Note>}
          {!llm && <Note className="mt-3">Without a Gemini API key FINN can list the documents but not read them. Add the key to backend/.env (free).</Note>}
          <Button className="mt-4" onClick={onStart}>Build research dossier</Button>
        </div>
      )}
    </Panel>
  );
}

export default function CompanyPage() {
  const { symbol: raw } = useParams<{ symbol: string }>();
  const symbol = decodeURIComponent(raw).toUpperCase();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("overview");
  const [jobId, setJobId] = useState<number | null>(null);
  const [startErr, setStartErr] = useState<string | null>(null);
  const { data: status } = useApi<Status>("/api/status");
  // A first visit triggers a background price fetch; re-check a few times until prices arrive.
  const pricePolls = useRef(0);
  const { data: co, error: coErr, mutate: mutateCo } = useApi<any>(`/api/companies/${symbol}`, {
    refreshInterval: (d: any) => (d && !d.prices?.length && pricePolls.current++ < 5 ? 4000 : 0),
  });
  const { data: rs, mutate: mutateRs } = useApi<{ status: string; content: any; job: Job | null }>(`/api/research/${symbol}`);
  const activeJob = jobId ?? (rs?.status === "building" ? rs.job?.id : null) ?? null;
  const { data: job } = useApi<Job>(activeJob ? `/api/jobs/${activeJob}` : null, { refreshInterval: 2000 });
  const numbers = useRef(new Map<string, number>());
  const number = (id: string) => {
    if (!numbers.current.has(id)) numbers.current.set(id, numbers.current.size + 1);
    return numbers.current.get(id)!;
  };

  useEffect(() => {
    if (job && (job.status === "done" || job.status === "failed")) {
      setJobId(null);
      mutateRs();
      mutateCo();
    }
  }, [job, mutateRs, mutateCo]);

  async function start(force = false) {
    setStartErr(null);
    try {
      const r = await post<{ job_id: number }>(`/api/research/${symbol}${force ? "?force=true" : ""}`);
      setJobId(r.job_id);
      mutateRs();
    } catch (e: any) { setStartErr(e.message); }
  }
  async function addToPortfolio() {
    await post("/api/portfolio/holdings", { symbol, quantity: 10 });
    mutateCo();
  }

  if (coErr) return <div className="p-6"><ErrorBox error={coErr} /><Button className="mt-4" variant="outline" href="/research">Back to research</Button></div>;
  const d = rs?.content;
  const cites: Record<string, Cite> = d?.citations ?? {};
  const st = co?.stats ?? {};
  const building = job ? (job.status === "queued" || job.status === "running") : rs?.status === "building";
  const llm = !!status?.llm.enabled;

  return (
    <div className="mx-auto max-w-[1200px]">
      <div className="px-4 pt-4 sm:px-6 lg:px-8 lg:pt-6">
        <button onClick={() => router.back()} className="mb-3 inline-flex items-center gap-1 text-[12.5px] text-muted hover:text-text lg:hidden">
          <ArrowLeft className="size-3.5" />Back
        </button>
        <nav className="mb-3 hidden text-[12.5px] text-faint lg:block"><Link href="/research" className="hover:text-text">Company research</Link> / {symbol}</nav>
        <div className="flex flex-wrap items-start gap-4">
          <span className="grid size-12 shrink-0 place-items-center rounded-[12px] bg-ink text-[16px] font-semibold text-ink-text">{symbol.slice(0, 2)}</span>
          <div className="min-w-0 flex-1">
            {!co ? <Skeleton className="h-6 w-56" /> : <h1 className="text-[18px] font-semibold leading-tight tracking-[-0.02em] sm:text-[20px] lg:text-[22px]">{co.name}</h1>}
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px]">
              <span className="font-semibold">{symbol}</span>
              {co?.sector && <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-muted">{co.sector}</span>}
              <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-muted">NSE</span>
              {co?.bse_code && <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-muted">BSE {co.bse_code}</span>}
              {co?.in_portfolio
                ? <span className="inline-flex items-center gap-1 rounded-md bg-accent-soft px-1.5 py-0.5 font-medium text-accent"><Check className="size-3" />In portfolio</span>
                : co && <button onClick={addToPortfolio} className="inline-flex items-center gap-1 rounded-md border border-line px-1.5 py-0.5 text-muted hover:text-text"><Plus className="size-3" />Add to portfolio</button>}
            </div>
          </div>
          <div className="flex w-full items-baseline gap-3 sm:block sm:w-auto sm:text-right">
            <p className="num text-[22px] font-semibold tracking-[-0.02em]">{price(st.close)}</p>
            <p className="text-[13px]"><Delta value={st.change_pct} digits={2} /> <span className="num text-muted">({st.change_abs != null ? (st.change_abs > 0 ? "+" : "") + num(st.change_abs, 2) : "—"})</span></p>
            <p className="text-[11.5px] text-faint sm:mt-0">End of day, {dateShort(st.date)}</p>
          </div>
        </div>

        <div className="scrollbar-none -mx-4 mt-5 flex gap-1 overflow-x-auto border-b border-line px-4 sm:mx-0 sm:px-0" role="tablist">
          {TABS.map((t) => (
            <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
              className={clsx("relative h-10 shrink-0 px-3 text-[13px] font-medium transition-colors",
                tab === t.key ? "text-text" : "text-muted hover:text-text")}>
              {t.label}
              {tab === t.key && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent" />}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-5 px-4 py-5 pb-10 sm:px-6 lg:px-8">
        {startErr && <ErrorBox error={startErr} />}
        {d && !building && (
          <p className="-mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-faint">
            <span>Dossier built {ago(d.generated_at)} from {d.coverage.results_filings} results filing{d.coverage.results_filings === 1 ? "" : "s"},
              {" "}{d.coverage.transcripts} transcript{d.coverage.transcripts === 1 ? "" : "s"}{d.coverage.annual_report ? " and the latest annual report" : ""}.</span>
            {!status?.sample_mode && <button onClick={() => start(true)} className="inline-flex items-center gap-1 text-muted hover:text-text"><RefreshCw className="size-3" />Rebuild</button>}
          </p>
        )}

        {tab === "overview" && (
          <>
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
              <Panel>
                {co ? <RangeChart data={co.prices} valueKey="close" fmt={price} height={230} defaultRange="1Y" /> : <Skeleton className="h-60" />}
              </Panel>
              <Panel title="Key stats">
                <dl className="space-y-2.5 text-[13px]">
                  {[
                    ["Market cap", st.market_cap_cr ? crore(st.market_cap_cr, { short: true }) : "—"],
                    ["P/E (trailing)", st.pe ? num(st.pe, 1) : "—"],
                    ["52-week high", price(st.high_52w)],
                    ["52-week low", price(st.low_52w)],
                    ["Dividend yield", st.dividend_yield != null ? pct(st.dividend_yield, 2, false) : "—"],
                    ["Volume vs 20-day avg", st.volume_mult != null ? `${st.volume_mult.toFixed(2)}×` : "—"],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-3 border-b border-line pb-2.5 last:border-0 last:pb-0">
                      <dt className="text-muted">{k}</dt><dd className="num font-medium">{v}</dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-3 text-[11px] text-faint">Market data from Yahoo Finance, end of day. Not used as research evidence.</p>
              </Panel>
            </div>
            {!d ? <BuildPanel symbol={symbol} job={job ?? rs?.job} onStart={() => start()} llm={llm} /> : (
              <>
                {d.snapshot && <SnapshotTiles snap={d.snapshot} />}
                <BusinessSection d={d} cites={cites} number={number} />
                {d.narrative?.length > 0 && (
                  <Panel title="Narrative vs numbers" action={<button className="text-[12.5px] font-medium text-accent" onClick={() => setTab("guidance")}>See the guidance ledger</button>}>
                    <ul className="space-y-2.5">
                      {d.narrative.map((n: any, i: number) => (
                        <li key={i} className="flex gap-2.5 text-[13.5px] leading-relaxed">
                          <span className={clsx("mt-0.5 shrink-0 rounded-md px-1.5 text-[11.5px] font-semibold leading-5",
                            n.stance === "agrees" ? "bg-up/10 text-up" : n.stance === "diverges" ? "bg-down/10 text-down" : "bg-warn/10 text-warn")}>
                            {n.stance === "agrees" ? "Matches" : n.stance === "diverges" ? "Diverges" : "Mixed"}</span>
                          <StatementText s={n} cites={cites} number={number} />
                        </li>
                      ))}
                    </ul>
                  </Panel>
                )}
                <BullBear d={d} cites={cites} number={number} />
              </>
            )}
          </>
        )}

        {tab === "financials" && (d ? <FinancialsSection d={d} /> : <BuildPanel symbol={symbol} job={job ?? rs?.job} onStart={() => start()} llm={llm} />)}

        {tab === "guidance" && (d ? (
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
            <Panel title="What management promised vs what was delivered">
              <GuidanceLedger items={d.guidance.items} tally={d.guidance.tally} cites={cites} number={number} />
            </Panel>
            <div className="flex flex-col gap-5">
              <Panel title="How FINN checks this">
                <ol className="list-decimal space-y-1.5 pl-4 text-[12.5px] text-muted">
                  <li>Guidance is extracted from the last four concall transcripts, with the exact quote and page. Quotes are verified against the transcript text.</li>
                  <li>Numeric targets (growth, margin, capex) are compared in code against the results filings, using year-to-date figures until the year ends.</li>
                  <li>Only promises without a hard number are judged by the model, citing its evidence. Those are marked "FINN's read".</li>
                </ol>
              </Panel>
              {d.narrative?.length > 0 && (
                <Panel title="Narrative vs numbers"><StatementList items={d.narrative} cites={cites} number={number} /></Panel>
              )}
            </div>
          </div>
        ) : <BuildPanel symbol={symbol} job={job ?? rs?.job} onStart={() => start()} llm={llm} />)}

        {tab === "news" && <NewsPanel symbol={symbol} hours={24 * 14} limit={30} title={`${symbol} in the news`} />}

        {tab === "announcements" && (
          <div className="flex flex-col gap-2.5">
            {!co ? <Skeleton className="h-40" /> : co.announcements.length === 0 ? (
              <Empty title="No filings stored for this company yet" body={co.in_portfolio ? "FINN checks the exchange every 30 minutes." : "Build the dossier or add it to your portfolio to start collecting filings."} />
            ) : co.announcements.map((a: FeedItem) => <FeedRow key={a.id} item={a} compact />)}
          </div>
        )}

        {tab === "documents" && (
          <Panel pad={false} title="Primary documents FINN has read">
            {!d?.documents?.length ? <Empty title="No documents yet" body="Build the dossier to discover this company's filings, transcripts and annual report." /> : (
              <ul className="divide-y divide-line border-t border-line">
                {d.documents.map((doc: any) => (
                  <li key={doc.id} className="flex items-center gap-3 px-4 py-3 sm:px-5">
                    <FileText className="size-4 shrink-0 text-faint" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-medium">{doc.title}</p>
                      <p className="text-[12px] text-muted">
                        {DOC_LABEL[doc.type] ?? doc.type}{doc.period ? ` · ${doc.period}` : ""}{doc.pages ? ` · ${doc.pages} pages` : ""}
                        {doc.filed_at ? ` · filed ${dateShort(doc.filed_at)}` : ""} · via {doc.via}
                        {doc.status !== "parsed" && <span className="text-warn"> · {doc.status}</span>}
                      </p>
                    </div>
                    <a href={fileUrl(doc.id)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[12.5px] font-medium text-accent hover:underline">
                      Open <ExternalLink className="size-3" /></a>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        )}

        {tab === "ask" && (d ? <AskPanel symbol={symbol} name={co?.name ?? symbol} enabled={llm && !status?.sample_mode} />
          : <BuildPanel symbol={symbol} job={job ?? rs?.job} onStart={() => start()} llm={llm} />)}
      </div>
    </div>
  );
}
