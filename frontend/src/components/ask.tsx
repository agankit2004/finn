"use client";
import clsx from "clsx";
import { ArrowUp, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fileUrl, post, type Cite, type Statement } from "@/lib/api";
import { num } from "@/lib/format";
import { CiteChip, StatementText } from "./research";

type Answer = {
  answer: Statement[]; takeaways: { text: string; verified: boolean }[]; follow_ups: string[];
  citations: Record<string, Cite>; table: null | { kind: string; basis: string; columns: string[]; rows: { metric: string; values: (number | null)[] }[]; sources: any[] };
};
type Msg = { role: "user"; text: string } | { role: "finn"; data?: Answer; error?: string };

const SUGGESTED = [
  "What does the company do and how does it make money?",
  "How have revenue and profit trended?",
  "What did management guide for this year?",
  "How much debt does it carry?",
  "What are the key risks management mentions?",
  "Summarise the latest earnings call",
];

function cagr(vals: (number | null)[]): number | null {
  const v = vals.filter((x): x is number => x != null && x > 0);
  if (v.length < 3) return null;
  return (Math.pow(v[v.length - 1] / v[0], 1 / (v.length - 1)) - 1) * 100;
}

function AnswerView({ a, onAsk }: { a: Answer; onAsk: (q: string) => void }) {
  const numbers = useRef(new Map<string, number>());
  const number = (id: string) => {
    if (!numbers.current.has(id)) numbers.current.set(id, numbers.current.size + 1);
    return numbers.current.get(id)!;
  };
  const used = Object.entries(a.citations);
  return (
    <div className="space-y-3">
      {a.table && a.table.rows.length > 0 && (
        <div>
          <div className="overflow-x-auto rounded-[var(--radius)] border border-line">
            <table className="num w-full min-w-[420px] text-[12.5px]">
              <thead className="bg-surface-2 text-[11.5px] text-muted">
                <tr>
                  <th className="px-3 py-1.5 text-left font-medium">₹ crore</th>
                  {a.table.columns.map((c, i) => (
                    <th key={c} className="px-3 py-1.5 text-right font-medium">
                      {a.table!.sources[i]?.doc_id ? <a className="hover:text-accent" target="_blank" rel="noreferrer" href={fileUrl(a.table!.sources[i].doc_id, a.table!.sources[i].page)}>{c}</a> : c}
                    </th>
                  ))}
                  {a.table.kind === "annual" && <th className="px-3 py-1.5 text-right font-medium">CAGR</th>}
                </tr>
              </thead>
              <tbody>
                {a.table.rows.map((r) => {
                  const g = a.table!.kind === "annual" ? cagr(r.values) : null;
                  return (
                    <tr key={r.metric} className="border-t border-line">
                      <td className="px-3 py-1.5 font-medium">{r.metric}</td>
                      {r.values.map((v, i) => <td key={i} className="px-3 py-1.5 text-right">{num(v)}</td>)}
                      {a.table!.kind === "annual" && <td className="px-3 py-1.5 text-right font-medium">{g != null ? `${g.toFixed(1)}%` : "—"}</td>}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-1 text-[11px] text-faint">Table built by FINN from extracted results ({a.table.basis}); column headers link to the filing.</p>
        </div>
      )}
      <div className="space-y-2 text-[13.5px] leading-relaxed">
        {a.answer.map((s, i) => <p key={i}><StatementText s={s} cites={a.citations} number={number} /></p>)}
      </div>
      {a.takeaways.length > 0 && (
        <div className="rounded-[var(--radius-sm)] bg-surface-2 px-3 py-2.5">
          <p className="text-[12px] font-semibold">Key takeaways</p>
          <ul className="mt-1 space-y-0.5 text-[13px]">
            {a.takeaways.map((t) => <li key={t.text} className={clsx(!t.verified && "text-muted")}>{t.text}{!t.verified && <span className="ml-1 text-[11px] text-warn">unverified</span>}</li>)}
          </ul>
        </div>
      )}
      {used.length > 0 && (
        <p className="text-[12px] text-muted">
          Sources:{" "}
          {used.map(([id, c], i) => (
            <span key={id}>
              {i > 0 && ", "}
              {c.doc_id ? (
                <a className="text-accent hover:underline" target="_blank" rel="noreferrer" href={fileUrl(c.doc_id, c.page)}>
                  {c.title ? c.title.slice(0, 48) : "Document"}{c.page ? ` (p. ${c.page})` : ""}
                </a>
              ) : (c.title ?? id)}
            </span>
          ))}
        </p>
      )}
      {a.follow_ups.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {a.follow_ups.map((q) => (
            <button key={q} onClick={() => onAsk(q)} className="rounded-full border border-line px-2.5 py-1 text-[12px] text-muted hover:border-accent hover:text-accent">{q}</button>
          ))}
        </div>
      )}
    </div>
  );
}

export function AskPanel({ symbol, name, enabled }: { symbol: string; name: string; enabled: boolean }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs]);

  async function ask(question: string) {
    const text = question.trim();
    if (!text || busy) return;
    setQ("");
    setMsgs((m) => [...m, { role: "user", text }]);
    setBusy(true);
    try {
      const data = await post<Answer>(`/api/research/${symbol}/ask`, { question: text });
      setMsgs((m) => [...m, { role: "finn", data }]);
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "finn", error: e.message }]);
    } finally { setBusy(false); }
  }

  return (
    <div className="flex min-h-[480px] flex-col rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-4 py-3 sm:px-5">
        <p className="text-[15px] font-semibold">Ask FINN about {name}</p>
        <p className="text-[12.5px] text-muted">Answers come only from this company's annual report, results filings and concall transcripts, with page references. No news, no broker notes.</p>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4 sm:px-5">
        {msgs.length === 0 && (
          <div>
            <p className="text-[12.5px] font-medium text-muted">Try asking</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {SUGGESTED.map((s) => (
                <button key={s} disabled={!enabled} onClick={() => ask(s)}
                  className="rounded-full border border-line px-3 py-1.5 text-[12.5px] text-muted hover:border-accent hover:text-accent disabled:opacity-50">{s}</button>
              ))}
            </div>
            {!enabled && <p className="mt-3 text-[12.5px] text-warn">Answers need a Gemini API key in the backend's .env file (free; see README).</p>}
          </div>
        )}
        {msgs.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="flex justify-end">
              <p className="max-w-[85%] rounded-[14px] rounded-br-[4px] bg-accent px-3.5 py-2 text-[13.5px] text-white">{m.text}</p>
            </div>
          ) : (
            <div key={i} className="flex gap-2.5">
              <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-ink text-[11px] font-semibold text-ink-text">F</span>
              <div className="min-w-0 flex-1">
                {m.error ? <p className="text-[13px] text-down">{m.error}</p> : <AnswerView a={m.data!} onAsk={ask} />}
              </div>
            </div>
          ))}
        {busy && (
          <div className="flex items-center gap-2 text-[12.5px] text-muted">
            <Loader2 className="size-3.5 animate-spin" /> Reading the filings…
          </div>
        )}
        <div ref={end} />
      </div>
      <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="flex items-center gap-2 border-t border-line p-3">
        <input value={q} onChange={(e) => setQ(e.target.value)} disabled={!enabled} placeholder={`Ask a question about ${symbol}`}
          className="h-10 min-w-0 flex-1 rounded-[10px] border border-line bg-surface-2 px-3 text-[13.5px] outline-none focus:border-accent" aria-label="Your question" />
        <button type="submit" disabled={!q.trim() || busy || !enabled} aria-label="Ask"
          className="grid size-10 shrink-0 place-items-center rounded-[10px] bg-accent text-white disabled:opacity-40"><ArrowUp className="size-4" /></button>
      </form>
    </div>
  );
}

export { CiteChip };
