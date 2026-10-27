"use client";
import clsx from "clsx";
import { useEffect, useState } from "react";
import { PageHeader, ThemeToggle } from "@/components/shell";
import { Button, ErrorBox, Panel, Skeleton } from "@/components/ui";
import { apiBase, post, useApi, type Status } from "@/lib/api";
import { ago, dateShort, num } from "@/lib/format";

const PURPOSE: Record<string, string> = {
  results_extract: "Results tables from filings", mgmt_change: "Management-change filings", summary: "One-line filing summaries",
  classify: "Classifying unusual filings", guidance_extract: "Guidance from transcripts", guidance_assess: "Judging qualitative promises",
  dossier: "Writing research dossiers", ask: "Answering your questions", check: "Connection check",
};

function Dot({ status }: { status: string | null }) {
  return <span className={clsx("inline-block size-2 rounded-full", status === "ok" ? "bg-up" : status === "partial" ? "bg-warn" : status ? "bg-down" : "bg-line-strong")} />;
}

export default function Settings() {
  const { data: s, error, mutate } = useApi<Status>("/api/status", { refreshInterval: 15000 });
  const [name, setName] = useState("");
  const [saved, setSaved] = useState(false);
  const [refresh, setRefresh] = useState<string | null>(null);
  useEffect(() => { try { setName(localStorage.getItem("finn-name") || ""); } catch {} }, []);

  return (
    <div className="mx-auto max-w-[900px]">
      <PageHeader title="Settings" sub="Appearance, data sources, and what FINN's AI has cost so far." />
      <div className="flex flex-col gap-5 px-4 pb-10 sm:px-6 lg:px-8">
        <Panel title="You">
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-[13px] text-muted" htmlFor="nm">Name for the greeting</label>
            <input id="nm" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Aditya"
              className="h-9 w-48 rounded-[var(--radius-sm)] border border-line bg-surface px-2.5 text-[13px]" />
            <Button size="sm" onClick={() => { try { localStorage.setItem("finn-name", name.trim()); } catch {} setSaved(true); setTimeout(() => location.reload(), 300); }}>
              {saved ? "Saved" : "Save"}
            </Button>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <span className="text-[13px] text-muted">Theme</span>
            <ThemeToggle />
          </div>
        </Panel>

        {error && <ErrorBox error={error} onRetry={() => mutate()} />}
        <Panel title="Data sources" action={s && !s.sample_mode && (
          <Button size="sm" variant="outline" onClick={async () => { const r = await post("/api/refresh"); setRefresh(r.message ?? "Refresh started"); setTimeout(() => mutate(), 4000); }}>Refresh now</Button>
        )}>
          {!s ? <Skeleton className="h-32" /> : (
            <div className="space-y-4 text-[13px]">
              {refresh && <p className="text-[12.5px] text-muted">{refresh}</p>}
              <div className="flex items-start gap-3">
                <Dot status={s.runs.prices.status} />
                <div className="flex-1">
                  <p className="font-medium">Prices and volume: Yahoo Finance (end of day)</p>
                  <p className="text-muted">Latest session stored: {s.prices.as_of ? dateShort(s.prices.as_of) : "none"}{s.prices.stale ? ` (expected ${dateShort(s.prices.expected_session)}; may be a market holiday or the source failed)` : ""}. Last fetch {ago(s.runs.prices.last_run)}.</p>
                  {s.runs.prices.detail && <p className="mt-0.5 text-[12px] text-faint">{s.runs.prices.detail}</p>}
                </div>
              </div>
              <div className="flex items-start gap-3">
                <Dot status={s.runs.announcements.status} />
                <div className="flex-1">
                  <p className="font-medium">Announcements: BSE corporate filings (NSE as fallback)</p>
                  <p className="text-muted">{num(s.announcements.total)} filings stored. Last check {ago(s.runs.announcements.last_run)}, every 30 minutes while the server runs.
                    {" "}Classified by rules: {num(s.announcements.classified_by.rule ?? 0)}, by AI: {num(s.announcements.classified_by.llm ?? 0)}.</p>
                  {s.runs.announcements.detail && <p className="mt-0.5 text-[12px] text-faint">{s.runs.announcements.detail}</p>}
                </div>
              </div>
              <div className="flex items-start gap-3">
                <Dot status={s.llm.enabled ? "ok" : null} />
                <div className="flex-1">
                  <p className="font-medium">AI: Google Gemini {s.llm.enabled ? "(connected)" : "(no key)"}</p>
                  <p className="text-muted">{s.llm.enabled
                    ? `Bulk extraction uses ${s.llm.fast_model}; research writing uses ${s.llm.smart_model}.${s.llm.groq ? " Groq is set as a fallback for text tasks." : ""}`
                    : "Add GEMINI_API_KEY to backend/.env and restart the backend. Prices, filings and alerts work without it."}</p>
                </div>
              </div>
              <p className="text-[12px] text-faint">Backend: {apiBase()}</p>
            </div>
          )}
        </Panel>

        <Panel title="AI usage">
          {!s ? <Skeleton className="h-24" /> : (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[["Model calls", s.ledger.calls], ["Answered from cache", s.ledger.cache_hits], ["Input tokens", s.ledger.input_tokens], ["Output tokens", s.ledger.output_tokens]].map(([k, v]) => (
                  <div key={k as string} className="rounded-[var(--radius-sm)] bg-surface-2 px-3 py-2">
                    <p className="text-[12px] text-muted">{k}</p><p className="num text-[16px] font-semibold">{num(v as number)}</p>
                  </div>
                ))}
              </div>
              {Object.keys(s.ledger.by_purpose).length > 0 && (
                <table className="num mt-4 w-full text-[12.5px]">
                  <thead className="text-[11.5px] text-muted"><tr><th className="py-1 text-left font-medium">Task</th><th className="py-1 text-right font-medium">Calls</th><th className="py-1 text-right font-medium">Cached</th><th className="py-1 text-right font-medium">Tokens</th><th className="hidden py-1 pl-3 text-left font-medium sm:table-cell">Model</th></tr></thead>
                  <tbody>
                    {Object.entries(s.ledger.by_purpose).map(([k, v]) => (
                      <tr key={k} className="border-t border-line">
                        <td className="py-1.5">{PURPOSE[k] ?? k}</td><td className="py-1.5 text-right">{v.calls}</td><td className="py-1.5 text-right">{v.cache_hits}</td>
                        <td className="py-1.5 text-right">{num(v.tokens)}</td><td className="hidden py-1.5 pl-3 text-muted sm:table-cell">{v.models.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className="mt-3 text-[12px] text-faint">
                Routine filings are classified by rules and never reach a model. Each filing is read once; repeats come from the cache.
                Percentages, margins and growth are computed in code, not by the model. On Gemini's free tier this costs ₹0.
              </p>
            </>
          )}
        </Panel>

        <Panel title="About the data">
          <ul className="space-y-1.5 text-[12.5px] text-muted">
            <li>Prices are end of day. FINN never shows live prices.</li>
            <li>Exchange data comes from the public endpoints behind BSE's and NSE's websites. They are not official APIs and can change or block requests; FINN polls slowly and stores what it fetches.</li>
            <li>Research uses only primary documents: results filings, concall transcripts and annual reports. Statements that can't be matched to a cited source are marked unverified.</li>
            <li>Nothing here is investment advice.</li>
          </ul>
        </Panel>
      </div>
    </div>
  );
}
