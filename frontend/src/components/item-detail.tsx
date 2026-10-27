"use client";
import clsx from "clsx";
import { AlertTriangle, ExternalLink, FileText, Microscope, Sparkles, UserRound } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { annFileUrl, post, useApi, type FeedItem, type Person, type ResultRow, type Status } from "@/lib/api";
import { crore, dateShort, num, pct, price, toneOf, when } from "@/lib/format";
import { Button, Delta, Signal, Sparkline, Tag } from "./ui";

function GrowthCell({ g }: { g: { pct: number | null; label: string } }) {
  if (g.pct === null) return <span className="text-[12px] text-faint">{g.label === "n/a" ? "—" : g.label}</span>;
  return <Delta value={g.pct} />;
}

export function ResultsCard({ s }: { s: any }) {
  if (s.error) {
    return <Note tone="warn">Couldn't read the results table: {s.error}. Open the filing to see the numbers.</Note>;
  }
  const rows: ResultRow[] = s.rows ?? [];
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h3 className="text-[14px] font-semibold">{s.quarter} headline numbers</h3>
        <span className="text-[11.5px] text-faint">₹ crore, {s.basis}</span>
      </div>
      <div className="mt-2 overflow-x-auto rounded-[var(--radius)] border border-line">
        <table className="num w-full text-[13px]">
          <thead className="bg-surface-2 text-[11.5px] text-muted">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Metric</th>
              <th className="px-3 py-2 text-right font-medium">This quarter</th>
              <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Last quarter</th>
              <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Year ago</th>
              <th className="px-3 py-2 text-right font-medium">QoQ</th>
              <th className="px-3 py-2 text-right font-medium">YoY</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.metric} className="border-t border-line">
                <td className="px-3 py-2 font-medium">{r.label}</td>
                <td className="px-3 py-2 text-right font-semibold">{num(r.current)}</td>
                <td className="hidden px-3 py-2 text-right text-muted sm:table-cell">{num(r.previous)}</td>
                <td className="hidden px-3 py-2 text-right text-muted sm:table-cell">{num(r.year_ago)}</td>
                <td className="px-3 py-2 text-right"><GrowthCell g={r.qoq} /></td>
                <td className="px-3 py-2 text-right"><GrowthCell g={r.yoy} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-[12.5px]">
        {s.margins?.ebitda_margin != null && !s.is_financial && (
          <span className="text-muted">EBITDA margin <b className="num font-semibold text-text">{s.margins.ebitda_margin.toFixed(1)}%</b>
            {s.margins.ebitda_margin_prev_year != null && (
              <> vs {s.margins.ebitda_margin_prev_year.toFixed(1)}% a year ago (
                <span className={{ up: "text-up", down: "text-down", flat: "text-muted" }[toneOf(Math.round((s.margins.ebitda_margin - s.margins.ebitda_margin_prev_year) * 100))]}>
                  {(() => { const b = Math.round((s.margins.ebitda_margin - s.margins.ebitda_margin_prev_year) * 100); return `${b > 0 ? "+" : ""}${b} bps`; })()}</span>)</>
            )}
          </span>
        )}
        {s.margins?.pat_margin != null && <span className="text-muted">PAT margin <b className="num font-semibold text-text">{s.margins.pat_margin.toFixed(1)}%</b></span>}
      </div>
      {s.checks?.length > 0 && <Note tone="warn" className="mt-3">Verify against the filing: {s.checks.join("; ")}.</Note>}
      <p className="mt-3 text-[11.5px] leading-relaxed text-faint">
        Read from the results filing{ s.page ? `, page ${s.page}` : ""}. Growth rates and EBITDA computed by FINN in code
        {s.ebitda_method ? ` (EBITDA = ${s.ebitda_method})` : ""}. QoQ and YoY columns are matched by period dates.
      </p>
    </div>
  );
}

function PeopleCard({ people, company }: { people: Person[]; company: string }) {
  return (
    <div className="flex flex-col gap-3">
      {people.map((p, i) => (
        <div key={i} className="rounded-[var(--radius)] border border-line p-3.5">
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-full bg-surface-2 text-muted"><UserRound className="size-4.5" /></span>
            <div className="min-w-0 flex-1">
              <p className="text-[14px] font-semibold">{p.name}</p>
              <p className="text-[12.5px] text-muted">
                <span className={clsx("font-medium", p.change === "appointed" || p.change === "reappointed" ? "text-up" : "text-down")}>
                  {p.change?.replace("_", " ")}</span>
                {p.role ? ` · ${p.role}` : ""}{p.effective_date ? ` · effective ${dateShort(p.effective_date)}` : ""}
              </p>
            </div>
          </div>
          {p.reason && <p className="mt-2 text-[12.5px] text-muted">Reason given: {p.reason}</p>}
          {p.profile && (
            <div className="mt-2.5 rounded-[var(--radius-sm)] bg-surface-2 p-2.5">
              <p className="text-[11.5px] font-medium text-faint">Background, from the filing{p.page ? ` (p. ${p.page})` : ""}</p>
              <p className="mt-1 text-[13px]">{p.profile}</p>
              {(p.prior_roles?.length || p.qualifications?.length) ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {[...(p.qualifications ?? []), ...(p.prior_roles ?? [])].slice(0, 6).map((x) => (
                    <span key={x} className="rounded-md border border-line bg-surface px-1.5 py-0.5 text-[11.5px] text-muted">{x}</span>
                  ))}
                </div>
              ) : null}
            </div>
          )}
          <a className="mt-2.5 inline-flex items-center gap-1 text-[12.5px] font-medium text-accent hover:underline" target="_blank" rel="noreferrer"
            href={`https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(`${p.name} ${company}`)}`}>
            Look up on LinkedIn <ExternalLink className="size-3" />
          </a>
        </div>
      ))}
    </div>
  );
}

function PriceCard({ item }: { item: FeedItem }) {
  const s = item.structured ?? {};
  return (
    <div>
      <div className="rounded-[var(--radius)] border border-line p-3.5">
        <Sparkline data={item.price.spark} width={440} height={110} className="h-auto w-full" />
        <p className="mt-1 text-[11.5px] text-faint">Last 30 sessions, closing prices</p>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-3">
        <Fact label="Close" value={price(s.close)} />
        <Fact label="Day change" value={<Delta value={s.change_pct} digits={2} />} />
        <Fact label="Volume vs 20-day avg" value={s.volume_mult != null ? `${s.volume_mult.toFixed(1)}×` : "—"} />
      </div>
      <p className="mt-3 text-[12px] text-faint">
        Your threshold: {item.type === "price" ? `±${s.threshold}% daily move` : `${s.threshold}× average volume`}. End-of-day data for {dateShort(s.date)}; not live.
        Change it in <Link href="/alerts" className="text-accent hover:underline">Alerts</Link>.
      </p>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-[var(--radius-sm)] bg-surface-2 px-3 py-2">
      <p className="text-[11.5px] text-muted">{label}</p>
      <p className="num mt-0.5 text-[14px] font-semibold">{value}</p>
    </div>
  );
}

export function Note({ children, tone = "info", className }: { children: React.ReactNode; tone?: "info" | "warn"; className?: string }) {
  return (
    <div className={clsx("flex items-start gap-2 rounded-[var(--radius-sm)] px-3 py-2.5 text-[12.5px]",
      tone === "warn" ? "bg-warn/10 text-text" : "bg-surface-2 text-muted", className)}>
      {tone === "warn" && <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" />}
      <div>{children}</div>
    </div>
  );
}

export function ItemDetail({ item: initial, onNavigate }: { item: FeedItem; onNavigate?: () => void }) {
  const [item, setItem] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [why, setWhy] = useState(false);
  const { data: status } = useApi<Status>("/api/status");
  const s = item.structured;
  const kind = s?.kind;

  async function readNow() {
    if (!item.announcement_id) return;
    setBusy(true); setErr(null);
    try { setItem(await post<FeedItem>(`/api/announcements/${item.announcement_id}/enrich`)); }
    catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <article className="px-4 pt-4 pb-8 md:px-5">
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-faint">
        <Tag category={item.category} label={item.category_label} />
        <span>{when(item.time)}</span>
        <span>· {item.exchange === "EOD" ? "End-of-day prices" : item.exchange}</span>
        {item.sample && <span className="rounded bg-warn/15 px-1.5 text-warn">Sample</span>}
      </div>
      <Link href={`/research/${item.company.symbol}`} onClick={onNavigate} className="mt-3 block text-[12.5px] font-medium text-muted hover:text-text">
        {item.company.name} <span className="text-faint">· {item.company.symbol}</span>
      </Link>
      <h2 className="mt-1 text-[18px] font-semibold leading-snug tracking-[-0.015em]">{item.title}</h2>
      {item.subject && item.subject !== item.title && kind !== "results" && (
        <p className="mt-1 text-[12.5px] text-faint">Filed as: {item.subject}</p>
      )}

      <button onClick={() => setWhy((w) => !w)} className="mt-3 inline-flex items-center gap-2 text-[12px] text-muted hover:text-text" aria-expanded={why}>
        <Signal score={item.importance} /> Importance {item.importance}/100 · {why ? "hide reasons" : "why it's ranked here"}
      </button>
      {why && (
        <ul className="anim-fade mt-2 space-y-1 rounded-[var(--radius-sm)] bg-surface-2 px-3 py-2 text-[12px] text-muted">
          {item.reasons.map((r) => <li key={r}>{r}</li>)}
          {item.classified_by && <li>Category set by {item.classified_by === "rule" ? "exchange category + keyword rules" : item.classified_by === "llm" ? "AI (rules were unsure)" : "exchange category"}</li>}
        </ul>
      )}

      <div className="mt-5">
        {kind === "results" && <ResultsCard s={s} />}
        {kind === "management_change" && (
          <>
            {item.summary && <p className="mb-3 text-[13.5px]">{item.summary}</p>}
            <PeopleCard people={s.people ?? []} company={item.company.name} />
          </>
        )}
        {kind === "summary" && (
          <div>
            <p className="text-[11.5px] font-medium text-faint">FINN's read of the filing</p>
            <p className="mt-1 text-[14.5px] leading-relaxed">{item.summary}</p>
            {s.key_facts?.length > 0 && (
              <div className="mt-3 grid grid-cols-2 gap-2">
                {s.key_facts.map((f: any) => <Fact key={f.label} label={f.label} value={<span className="text-[13px]">{f.value}</span>} />)}
              </div>
            )}
          </div>
        )}
        {(item.type === "price" || item.type === "volume") && <PriceCard item={item} />}
        {kind === "not_results" && <Note>This filing turned out not to contain a results statement.</Note>}
        {!kind && item.type === "announcement" && (
          <div className="space-y-3">
            {item.enrich_status === "skipped" && (
              <Note>FINN doesn't summarise this category: the filing title says what it is. Open the PDF if you need detail.</Note>
            )}
            {item.enrich_status === "needs_key" && (
              <Note>FINN can read this filing and extract the key facts once a Gemini API key is added to the backend (free, see README).</Note>
            )}
            {(item.enrich_status === "failed" || item.enrich_status === "pending") && (
              <Note tone={item.enrich_status === "failed" ? "warn" : "info"}>
                {item.enrich_status === "failed" ? `FINN couldn't read this filing: ${item.enrich_error ?? "unknown error"}` : "FINN hasn't read this filing yet."}
              </Note>
            )}
            {item.has_file && status?.llm.enabled && item.enrich_status !== "skipped" && (
              <Button onClick={readNow} loading={busy} variant="outline"><Sparkles className="size-3.5" />Read this filing with AI</Button>
            )}
            {err && <Note tone="warn">{err}</Note>}
          </div>
        )}
      </div>

      <div className="mt-6 flex flex-wrap gap-2 border-t border-line pt-4">
        {item.announcement_id && item.has_file && (
          <Button href={undefined} variant="outline" onClick={() => window.open(annFileUrl(item.announcement_id!), "_blank")}>
            <FileText className="size-3.5" /> Open filing
          </Button>
        )}
        {item.source_url && (
          <a href={item.source_url} target="_blank" rel="noreferrer"
            className="inline-flex h-10 items-center gap-1.5 rounded-[var(--radius-sm)] px-3 text-[13px] text-muted hover:bg-surface-2 hover:text-text">
            Original on {item.exchange} <ExternalLink className="size-3" />
          </a>
        )}
        <Button href={`/research/${item.company.symbol}`} variant="ghost" className="ml-auto" onClick={onNavigate}>
          <Microscope className="size-3.5" /> Research {item.company.symbol}
        </Button>
      </div>
      {item.price?.close != null && (
        <p className="mt-3 text-[11.5px] text-faint">
          {item.company.symbol} last close {price(item.price.close)} ({pct(item.price.change_pct, 2)}) on {dateShort(item.price.date)}. End-of-day, not live.
        </p>
      )}
    </article>
  );
}

export { crore };
