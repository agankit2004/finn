"use client";
import Link from "next/link";
import { CompanySearch, PageHeader } from "@/components/shell";
import { Empty, Panel, Skeleton } from "@/components/ui";
import { useApi, type Portfolio } from "@/lib/api";
import { ago } from "@/lib/format";

type Index = {
  dossiers: { symbol: string; name: string; sector?: string; generated_at: string; latest_quarter?: string }[];
  building: { symbol: string; job_id: number; step: string; progress: number }[];
  suggested: string[];
};

export default function ResearchIndex() {
  const { data } = useApi<Index>("/api/research", { refreshInterval: 5000 });
  const { data: pf } = useApi<Portfolio>("/api/portfolio");
  return (
    <div className="mx-auto max-w-[1000px]">
      <PageHeader title="Company research"
        sub="Pick any NSE company. FINN reads its results filings, concall transcripts and annual report, and nothing else." />
      <div className="flex flex-col gap-5 px-4 pb-10 sm:px-6 lg:px-8">
        <CompanySearch autoFocus placeholder="Type an NSE symbol or company name, e.g. ASIANPAINT" />

        {data?.building.length ? (
          <Panel title="Building now">
            <ul className="space-y-3">
              {data.building.map((b) => (
                <li key={b.job_id}>
                  <Link href={`/research/${b.symbol}`} className="block">
                    <div className="flex justify-between text-[13px]"><span className="font-semibold">{b.symbol}</span><span className="text-muted">{b.step}</span></div>
                    <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-2">
                      <div className="h-full bg-accent transition-all" style={{ width: `${Math.max(4, b.progress * 100)}%` }} />
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}

        <Panel pad={false} title="Your dossiers">
          {!data ? <div className="p-5"><Skeleton className="h-24" /></div> : data.dossiers.length === 0 ? (
            <Empty title="No dossiers yet" body="Search for a company above, or start with one of the suggestions below." />
          ) : (
            <ul className="divide-y divide-line border-t border-line">
              {data.dossiers.map((d) => (
                <li key={d.symbol}>
                  <Link href={`/research/${d.symbol}`} className="flex items-center gap-3 px-4 py-3 hover:bg-surface-2/60 sm:px-5">
                    <span className="grid size-9 shrink-0 place-items-center rounded-[10px] bg-ink text-[12px] font-semibold text-ink-text">{d.symbol.slice(0, 2)}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13.5px] font-semibold">{d.name}</span>
                      <span className="block text-[12px] text-muted">{d.symbol}{d.sector ? ` · ${d.sector}` : ""}{d.latest_quarter ? ` · numbers to ${d.latest_quarter}` : ""}</span>
                    </span>
                    <span className="text-[12px] text-faint">{ago(d.generated_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="grid gap-5 md:grid-cols-2">
          <Panel title="Outside your portfolio">
            <p className="-mt-1 mb-3 text-[12.5px] text-muted">Companies picked to show the research engine on names you don't hold.</p>
            <div className="flex flex-wrap gap-1.5">
              {(data?.suggested ?? []).map((s) => (
                <Link key={s} href={`/research/${s}`} className="rounded-full border border-line px-3 py-1.5 text-[12.5px] font-medium hover:border-accent hover:text-accent">{s}</Link>
              ))}
            </div>
          </Panel>
          <Panel title="Your holdings">
            <div className="flex flex-wrap gap-1.5">
              {(pf?.holdings ?? []).map((h) => (
                <Link key={h.symbol} href={`/research/${h.symbol}`} className="rounded-full bg-surface-2 px-3 py-1.5 text-[12.5px] text-muted hover:text-text">{h.symbol}</Link>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
