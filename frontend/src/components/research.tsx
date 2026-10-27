"use client";
import clsx from "clsx";
import { ExternalLink, Quote } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fileUrl, type Cite, type Statement } from "@/lib/api";
import { crore, dateShort, num, pct } from "@/lib/format";
import { SegmentDonut, TrajectoryChart } from "./charts";
import { Note } from "./item-detail";
import { Delta, Panel } from "./ui";

const DOC_LABEL: Record<string, string> = { results: "Results filing", transcript: "Concall transcript", annual_report: "Annual report", presentation: "Investor presentation" };

/** A tappable evidence marker: shows the source passage and opens the PDF at the cited page. */
export function CiteChip({ id, n, cite }: { id: string; n: number; cite?: Cite }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  if (!cite) return null;
  const label = cite.kind === "fact" ? "From results data" : cite.kind === "guidance" ? "Management guidance" : DOC_LABEL[cite.doc_type ?? ""] ?? "Source";
  return (
    <span ref={ref} className="relative inline-block align-baseline">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label={`Source ${n}`}
        className={clsx("num ml-0.5 inline-flex h-[17px] min-w-[17px] -translate-y-px items-center justify-center rounded-[5px] px-1 text-[10.5px] font-semibold",
          open ? "bg-accent text-white" : "bg-accent-soft text-accent hover:bg-accent hover:text-white")}>
        {n}
      </button>
      {open && (
        <span className="anim-fade absolute left-1/2 top-6 z-30 block w-[280px] -translate-x-1/2 rounded-[10px] border border-line bg-surface p-3 text-left shadow-xl sm:w-[320px]">
          <span className="block text-[11.5px] font-medium text-faint">{label}{cite.period ? `, ${cite.period}` : ""}{cite.page ? `, page ${cite.page}` : ""}</span>
          {cite.title && <span className="mt-0.5 block truncate text-[12.5px] font-medium text-text">{cite.title}</span>}
          {cite.snippet && <span className="mt-1.5 line-clamp-5 block text-[12px] leading-relaxed text-muted">{cite.snippet}</span>}
          {cite.doc_id && (
            <a href={fileUrl(cite.doc_id, cite.page)} target="_blank" rel="noreferrer"
              className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-accent hover:underline">
              Open {cite.page ? `page ${cite.page}` : "document"} <ExternalLink className="size-3" />
            </a>
          )}
        </span>
      )}
    </span>
  );
}

export function useCiteNumbers() {
  const map = useRef(new Map<string, number>());
  return (id: string) => {
    if (!map.current.has(id)) map.current.set(id, map.current.size + 1);
    return map.current.get(id)!;
  };
}

export function StatementText({ s, cites, number }: { s: Statement; cites: Record<string, Cite>; number: (id: string) => number }) {
  return (
    <span>
      <span className={clsx(!s.verified && "decoration-warn/70 underline decoration-dotted underline-offset-4")}
        title={s.verified ? undefined : `Not verified: ${s.reason ?? "check the source"}`}>{s.text}</span>
      {s.cites.map((c) => <CiteChip key={c} id={c} n={number(c)} cite={cites[c]} />)}
      {!s.verified && <span className="ml-1.5 text-[11px] font-medium text-warn">unverified</span>}
    </span>
  );
}

export function StatementList({ items, cites, number, empty, className }: {
  items: Statement[]; cites: Record<string, Cite>; number: (id: string) => number; empty?: string; className?: string;
}) {
  if (!items?.length) return empty ? <p className="text-[13px] text-faint">{empty}</p> : null;
  return (
    <ul className={clsx("space-y-2.5", className)}>
      {items.map((s, i) => (
        <li key={i} className="flex gap-2.5 text-[13.5px] leading-relaxed">
          <span className="mt-[9px] size-1 shrink-0 rounded-full bg-faint" />
          <StatementText s={s} cites={cites} number={number} />
        </li>
      ))}
    </ul>
  );
}

const VERDICT: Record<string, { label: string; cls: string }> = {
  met: { label: "Delivered", cls: "text-up bg-up/10" },
  on_track: { label: "On track", cls: "text-up bg-up/10" },
  partly: { label: "Partly", cls: "text-warn bg-warn/10" },
  tracking: { label: "In progress", cls: "text-muted bg-surface-2" },
  behind: { label: "Behind", cls: "text-down bg-down/10" },
  missed: { label: "Missed", cls: "text-down bg-down/10" },
  pending: { label: "Not yet measurable", cls: "text-muted bg-surface-2" },
  unverifiable: { label: "No hard number", cls: "text-muted bg-surface-2" },
  unclear: { label: "Unclear", cls: "text-muted bg-surface-2" },
};

function target(g: any) {
  if (g.target_low == null && g.target_high == null) return null;
  const u = g.unit === "cr" ? " cr" : "%";
  const pre = g.unit === "cr" ? "₹" : "";
  const lo = g.target_low != null ? `${pre}${num(g.target_low, g.unit === "cr" ? 0 : 1)}` : "";
  const hi = g.target_high != null && g.target_high !== g.target_low ? `–${num(g.target_high, g.unit === "cr" ? 0 : 1)}` : "";
  return `${lo}${hi}${u}`;
}

export function GuidanceLedger({ items, tally, cites, number }: { items: any[]; tally: Record<string, number>; cites: Record<string, Cite>; number: (id: string) => number }) {
  if (!items?.length) {
    return <Note>No explicit numeric guidance found in the transcripts FINN read. Some managements don't guide; others guide only in presentations.</Note>;
  }
  const order = ["met", "on_track", "partly", "tracking", "behind", "missed", "unclear", "pending", "unverifiable"];
  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {order.filter((k) => tally[k]).map((k) => (
          <span key={k} className={clsx("num rounded-full px-2.5 py-1 text-[12px] font-medium", VERDICT[k].cls)}>{tally[k]} {VERDICT[k].label.toLowerCase()}</span>
        ))}
      </div>
      <ol className="mt-4 space-y-3">
        {items.map((g) => {
          const v = VERDICT[g.verdict] ?? VERDICT.pending;
          const t = target(g);
          return (
            <li key={g.id} className="rounded-[var(--radius)] border border-line p-3.5 sm:p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className={clsx("rounded-md px-2 py-0.5 text-[12px] font-semibold", v.cls)}>{v.label}</span>
                {g.target_period && <span className="text-[12px] text-muted">for {g.target_period}</span>}
                <span className="ml-auto text-[11.5px] text-faint">
                  {g.assessment_method === "code" ? "Checked by FINN against results" : g.assessment_method === "llm" ? "FINN's read" : ""}
                </span>
              </div>
              <blockquote className="mt-2.5 flex gap-2 text-[13.5px] leading-relaxed">
                <Quote className="mt-1 size-3.5 shrink-0 text-faint" />
                <span>
                  {g.quote}
                  {g.doc_id && (
                    <a href={fileUrl(g.doc_id, g.page)} target="_blank" rel="noreferrer" className="ml-1.5 whitespace-nowrap text-[12px] font-medium text-accent hover:underline">
                      {g.made_in ? `${g.made_in} call` : "Transcript"}{g.page ? `, p. ${g.page}` : ""}
                    </a>
                  )}
                </span>
              </blockquote>
              {(t || g.actual_value != null || g.assessment) && (
                <div className="mt-3 grid gap-2 rounded-[var(--radius-sm)] bg-surface-2 p-2.5 text-[12.5px] sm:grid-cols-[auto_auto_1fr] sm:gap-5">
                  {t && <span><span className="text-muted">Promised </span><b className="num">{t}</b></span>}
                  {g.actual_value != null && g.assessment_method === "code" && (
                    <span><span className="text-muted">Delivered </span><b className="num">{g.unit === "cr" ? crore(g.actual_value) : g.metric === "ebitda_margin" ? `${g.actual_value.toFixed(1)}%` : pct(g.actual_value)}</b></span>
                  )}
                  <span className="text-muted">
                    {g.assessment_method === "llm"
                      ? <StatementText s={{ text: g.assessment, cites: g.cites ?? [], verified: g.verified }} cites={cites} number={number} />
                      : g.actual_basis ?? g.assessment}
                  </span>
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function SnapshotTiles({ snap }: { snap: any }) {
  if (!snap) return null;
  const tiles = [
    { label: `${snap.revenue_label}, ${snap.quarter}`, value: crore(snap.revenue), delta: snap.revenue_yoy, note: "YoY" },
    { label: `${snap.ebitda_label} margin`, value: snap.ebitda_margin != null ? `${snap.ebitda_margin.toFixed(1)}%` : "—",
      sub: snap.ebitda_margin_change_bps != null ? `${snap.ebitda_margin_change_bps > 0 ? "+" : ""}${snap.ebitda_margin_change_bps} bps QoQ` : undefined },
    { label: `PAT, ${snap.quarter}`, value: crore(snap.pat), delta: snap.pat_yoy, note: "YoY" },
    { label: snap.ttm?.label ?? "Trailing 12 months", value: snap.ttm ? crore(snap.ttm.revenue, { short: true }) : "—",
      sub: snap.ttm?.pat != null ? `PAT ${crore(snap.ttm.pat, { short: true })}` : undefined },
  ];
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius)] border border-line bg-line lg:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className="bg-surface px-3.5 py-3">
          <p className="truncate text-[12px] text-muted">{t.label}</p>
          <p className="num mt-1 text-[17px] font-semibold tracking-[-0.01em]">{t.value}</p>
          <p className="mt-0.5 text-[12px] text-muted">
            {t.delta !== undefined ? <><Delta value={t.delta} /> {t.note}</> : t.sub ?? " "}
          </p>
        </div>
      ))}
    </div>
  );
}

export function QuarterTable({ rows, isFin }: { rows: any[]; isFin: boolean }) {
  if (!rows?.length) return null;
  const lines: [string, string, (r: any) => string][] = [
    [isFin ? "Interest earned" : "Revenue", "revenue", (r) => num(r.revenue)],
    ["YoY", "revenue_yoy", (r) => pct(r.revenue_yoy)],
    [isFin ? "Operating profit" : "EBITDA", "ebitda", (r) => num(r.ebitda)],
    ["Margin", "ebitda_margin", (r) => (r.ebitda_margin != null ? `${r.ebitda_margin.toFixed(1)}%` : "—")],
    ["PBT", "pbt", (r) => num(r.pbt)],
    ["PAT", "pat", (r) => num(r.pat)],
    ["PAT YoY", "pat_yoy", (r) => pct(r.pat_yoy)],
  ];
  return (
    <div className="overflow-x-auto rounded-[var(--radius)] border border-line">
      <table className="num w-full min-w-[560px] text-[12.5px]">
        <thead className="bg-surface-2 text-[11.5px] text-muted">
          <tr>
            <th className="sticky left-0 bg-surface-2 px-3 py-2 text-left font-medium">₹ crore</th>
            {rows.map((r) => (
              <th key={r.label} className="px-3 py-2 text-right font-medium">
                {r.source?.doc_id ? <a href={fileUrl(r.source.doc_id, r.source.page)} target="_blank" rel="noreferrer" className="hover:text-accent">{r.label}</a> : r.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {lines.map(([label, key, f]) => (
            <tr key={key} className={clsx("border-t border-line", key.endsWith("yoy") || key === "ebitda_margin" ? "text-muted" : "")}>
              <td className="sticky left-0 bg-surface px-3 py-1.5 text-left font-medium text-text">{label}</td>
              {rows.map((r) => (
                <td key={r.label} className={clsx("px-3 py-1.5 text-right",
                  key.endsWith("yoy") && r[key] != null && (r[key] >= 0 ? "text-up" : "text-down"))}>{f(r)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FinancialsSection({ d }: { d: any }) {
  const isFin = d.company.is_financial;
  const q = d.trajectory?.quarters ?? [];
  const y = d.trajectory?.years ?? [];
  const bs = d.balance_sheet;
  const cq = d.cash_quality;
  return (
    <div className="flex flex-col gap-5">
      <Panel title="Quarterly trajectory" action={<span className="text-[11.5px] text-faint">{d.basis}, from results filings</span>}>
        {q.length ? (
          <>
            <TrajectoryChart rows={q} revLabel={isFin ? "Interest earned" : "Revenue"} />
            <p className="mt-1 text-[11.5px] text-faint">Light bars: {isFin ? "interest earned" : "revenue"}. Dark bars: PAT. Line: {isFin ? "operating" : "EBITDA"} margin (right axis).</p>
            <div className="mt-4"><QuarterTable rows={q} isFin={isFin} /></div>
            {d.trajectory.observations?.length > 0 && (
              <ul className="mt-4 space-y-1.5 text-[13px]">
                {d.trajectory.observations.map((o: any) => (
                  <li key={o.text} className="flex gap-2"><span className="mt-[8px] size-1 shrink-0 rounded-full bg-faint" />{o.text}
                    <span className="text-[11px] text-faint">computed</span></li>
                ))}
              </ul>
            )}
          </>
        ) : <Note>No results filings could be read for this company yet.</Note>}
      </Panel>

      {y.length > 0 && (
        <Panel title="Full years">
          <div className="overflow-x-auto rounded-[var(--radius)] border border-line">
            <table className="num w-full text-[12.5px]">
              <thead className="bg-surface-2 text-[11.5px] text-muted">
                <tr><th className="px-3 py-2 text-left font-medium">₹ crore</th>{y.map((r: any) => <th key={r.label} className="px-3 py-2 text-right font-medium">{r.label}</th>)}</tr>
              </thead>
              <tbody>
                {(["revenue", "ebitda", "pbt", "pat"] as const).map((k) => (
                  <tr key={k} className="border-t border-line">
                    <td className="px-3 py-1.5 font-medium">{{ revenue: isFin ? "Interest earned" : "Revenue", ebitda: isFin ? "Operating profit" : "EBITDA", pbt: "PBT", pat: "PAT" }[k]}</td>
                    {y.map((r: any) => <td key={r.label} className="px-3 py-1.5 text-right">{num(r[k])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Balance sheet" action={bs?.current?.as_of && <span className="text-[11.5px] text-faint">as of {dateShort(bs.current.as_of)}</span>}>
          {!bs ? <Note>No balance sheet in the filings read so far (it's published with Q2 and Q4 results).</Note> : (
            <>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-[13px]">
                {[
                  ["Total borrowings", crore(bs.current.total_debt)],
                  ["Cash & liquid investments", crore(bs.current.cash_and_investments)],
                  ["Net debt", crore(bs.current.net_debt)],
                  ["Equity", crore(bs.current.equity)],
                  ["Debt / equity", bs.current.de_ratio != null ? `${bs.current.de_ratio.toFixed(2)}×` : "—"],
                  ...(!isFin ? [["Cash cycle", bs.current.cash_cycle_days != null ? `${bs.current.cash_cycle_days} days` : "—"]] : []),
                ].map(([k, v]) => (
                  <div key={k}><dt className="text-[12px] text-muted">{k}</dt><dd className="num mt-0.5 font-semibold">{v}</dd></div>
                ))}
              </dl>
              {!isFin && bs.current.receivable_days != null && (
                <p className="mt-3 text-[12px] text-muted">
                  Receivables {bs.current.receivable_days} days, inventory {bs.current.inventory_days ?? "—"} days, payables {bs.current.payable_days ?? "—"} days, {bs.current.days_basis}.
                </p>
              )}
              {bs.current.note && <Note className="mt-3">{bs.current.note}</Note>}
              {bs.prior && bs.prior.net_debt != null && bs.current.net_debt != null && (
                <p className="mt-3 text-[12.5px]">Net debt {bs.current.net_debt <= bs.prior.net_debt ? "fell" : "rose"} from {crore(bs.prior.net_debt)} ({dateShort(bs.prior.as_of)}).</p>
              )}
              {bs.current.source?.doc_id && (
                <a href={fileUrl(bs.current.source.doc_id, bs.current.source.page)} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-[12px] font-medium text-accent hover:underline">
                  Statement of assets & liabilities, p. {bs.current.source.page} <ExternalLink className="size-3" /></a>
              )}
            </>
          )}
        </Panel>
        <Panel title="Cash quality">
          {!cq ? <Note>No cash-flow statement in the filings read so far.</Note> : (
            <>
              {cq.verdict && <p className="text-[14px] font-medium">{cq.verdict}</p>}
              <table className="num mt-3 w-full text-[12.5px]">
                <thead className="text-[11.5px] text-muted">
                  <tr><th className="py-1 text-left font-medium">Period</th><th className="py-1 text-right font-medium">Op. cash flow</th><th className="py-1 text-right font-medium">PAT</th><th className="py-1 text-right font-medium">CFO/PAT</th><th className="py-1 text-right font-medium">Free cash flow</th></tr>
                </thead>
                <tbody>
                  {cq.periods.map((p: any) => (
                    <tr key={p.label} className="border-t border-line">
                      <td className="py-1.5">{p.source?.doc_id ? <a className="hover:text-accent" href={fileUrl(p.source.doc_id, p.source.page)} target="_blank" rel="noreferrer">{p.label}</a> : p.label}</td>
                      <td className="py-1.5 text-right">{num(p.cfo)}</td>
                      <td className="py-1.5 text-right">{num(p.pat)}</td>
                      <td className={clsx("py-1.5 text-right font-medium", p.conversion != null && (p.conversion >= 0.9 ? "text-up" : p.conversion < 0.6 ? "text-down" : ""))}>
                        {p.conversion != null ? `${p.conversion.toFixed(2)}×` : "—"}</td>
                      <td className="py-1.5 text-right">{num(p.fcf)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-3 text-[11.5px] text-faint">Free cash flow = operating cash flow − capex (purchase of fixed and intangible assets). ₹ crore.</p>
            </>
          )}
        </Panel>
      </div>
    </div>
  );
}

export function BusinessSection({ d, cites, number }: { d: any; cites: Record<string, Cite>; number: (id: string) => number }) {
  const b = d.business ?? {};
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <Panel title="Business overview">
        {b.summary ? <p className="text-[14px] leading-relaxed">{b.summary}</p> : (
          <p className="text-[13px] text-faint">{d.coverage.llm ? "The annual report wasn't available to summarise." : "Add a Gemini key to generate the overview from the annual report."}</p>
        )}
        <StatementList items={b.points} cites={cites} number={number} className="mt-3" />
      </Panel>
      <Panel title="Revenue mix" action={b.segments?.[0]?.period && <span className="text-[11.5px] text-faint">{b.segments[0].period}</span>}>
        {b.segments?.length ? (
          <>
            <SegmentDonut segments={b.segments} />
            {b.segments[0].doc_id && (
              <a href={fileUrl(b.segments[0].doc_id, b.segments[0].page)} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-[12px] font-medium text-accent hover:underline">
                Segment note in results filing <ExternalLink className="size-3" /></a>
            )}
          </>
        ) : <p className="text-[13px] text-faint">The results filing doesn't report segments (single-segment company), or it wasn't read yet.</p>}
      </Panel>
    </div>
  );
}

export function BullBear({ d, cites, number }: { d: any; cites: Record<string, Cite>; number: (id: string) => number }) {
  if (!d.bull?.length && !d.bear?.length) return null;
  return (
    <Panel title="Bull and bear case" action={<span className="text-[11.5px] text-faint">FINN's read of the filings, not advice</span>}>
      <div className="grid gap-5 md:grid-cols-2">
        <div>
          <p className="mb-2 text-[13px] font-semibold text-up">What has to go right</p>
          <StatementList items={d.bull} cites={cites} number={number} />
        </div>
        <div>
          <p className="mb-2 text-[13px] font-semibold text-down">What could go wrong</p>
          <StatementList items={d.bear} cites={cites} number={number} />
        </div>
      </div>
      {d.open_questions?.length > 0 && (
        <div className="mt-5 border-t border-line pt-4">
          <p className="text-[13px] font-semibold">Questions worth asking management</p>
          <ul className="mt-2 space-y-1 text-[13px] text-muted">{d.open_questions.map((q: string) => <li key={q}>{q}</li>)}</ul>
        </div>
      )}
    </Panel>
  );
}
