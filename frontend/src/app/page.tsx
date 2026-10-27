"use client";
import clsx from "clsx";
import { Bell, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { RangeChart } from "@/components/charts";
import { FeedRow, FeedSkeleton, RoutineGroup } from "@/components/feed";
import { CompanySearch, useUserName } from "@/components/shell";
import { Chips, Delta, Empty, ErrorBox, Panel, Skeleton, Sparkline } from "@/components/ui";
import { post, useApi, type Feed, type Portfolio, type Status } from "@/lib/api";
import { ago, dateShort, FILTERS, greeting, inr, price } from "@/lib/format";

function HeroTile({ label, value, sub, href }: { label: string; value: React.ReactNode; sub: React.ReactNode; href: string }) {
  return (
    <Link href={href} className="rounded-[14px] border border-ink-line bg-ink-2 px-4 py-3.5 transition-colors hover:bg-ink-3">
      <p className="text-[12.5px] text-ink-muted">{label}</p>
      <p className="num mt-1.5 text-[24px] font-semibold tracking-[-0.02em] text-ink-text">{value}</p>
      <div className="mt-1 text-[12.5px] text-ink-muted">{sub}</div>
    </Link>
  );
}

function Freshness({ status }: { status?: Status }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  if (!status) return null;
  if (status.sample_mode) return <p className="text-[12px] text-ink-muted">Sample mode: no live sources are being polled.</p>;
  const ann = status.runs.announcements;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink-muted">
      <span>Prices: end of day, {status.prices.as_of ? dateShort(status.prices.as_of) : "not loaded yet"}
        {status.prices.stale && <span className="text-warn"> (stale)</span>}</span>
      <span>Filings checked {ago(ann.last_success)}{ann.status === "failed" && <span className="text-warn"> · last check failed</span>}</span>
      {!status.sample_mode && (
        <button disabled={busy} onClick={async () => {
          setBusy(true);
          try { const r = await post("/api/refresh"); setMsg(r.status === "started" ? "Refreshing in the background…" : r.message); }
          catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
        }} className="inline-flex items-center gap-1 text-ink-text/80 hover:text-ink-text">
          <RefreshCw className={clsx("size-3", busy && "animate-spin")} /> {msg ?? "Refresh"}
        </button>
      )}
    </div>
  );
}

export default function Home() {
  const name = useUserName();
  const [cat, setCat] = useState("all");
  const { data: status } = useApi<Status>("/api/status");
  const { data: pf, error: pfErr } = useApi<Portfolio>("/api/portfolio", { refreshInterval: 120000 });
  const { data: feed, error: feedErr, mutate } = useApi<Feed>(`/api/feed?hours=24&category=${encodeURIComponent(cat)}`, { refreshInterval: 60000 });
  const { data: allFeed } = useApi<Feed>(`/api/feed?hours=24`, { refreshInterval: 60000 });
  const { data: alerts } = useApi<{ items: any[]; today: number; unseen: number }>("/api/alerts?days=3");

  const counts = allFeed?.counts ?? {};
  const totalMaterial = allFeed?.items.length ?? 0;
  const companiesWithNews = new Set((allFeed?.items ?? []).filter((i) => i.importance >= 60).map((i) => i.company.symbol)).size;
  const chips = FILTERS.filter((f) => f.key === "all" || counts[f.key]).map((f) => ({ ...f, count: f.key === "all" ? totalMaterial : counts[f.key] }));
  const movers = (pf?.movers ?? []).map((s) => pf!.holdings.find((h) => h.symbol === s)!).filter(Boolean).slice(0, 5);
  const dayTone = (pf?.day_change_pct ?? 0) >= 0 ? "up" : "down";

  return (
    <div>
      {/* Dark hero band: greeting, search, the four numbers that frame the day */}
      <section className="bg-ink px-4 pt-5 pb-5 text-ink-text sm:px-6 lg:px-8 lg:pt-8 lg:pb-8">
        <div className="flex items-start justify-between gap-6">
          <div className="min-w-0">
            <div className="mb-4 flex items-center justify-between lg:hidden">
              <span className="text-[16px] font-semibold tracking-[-0.02em]">FINN</span>
              <Link href="/alerts" className="relative rounded-md p-1.5 text-ink-muted" aria-label="Alerts">
                <Bell className="size-5" />
                {(alerts?.unseen ?? 0) > 0 && <span className="absolute right-1 top-1 size-2 rounded-full bg-accent" />}
              </Link>
            </div>
            <h1 className="text-[22px] font-semibold tracking-[-0.025em] lg:text-[26px]">{greeting()}{name ? `, ${name}` : ""}</h1>
            <p className="mt-1 text-[13.5px] text-ink-muted">
              {totalMaterial ? `${totalMaterial} thing${totalMaterial > 1 ? "s" : ""} worth your attention in the last 24 hours` : "Here's what moved your companies today"}
              {allFeed?.routine.length ? `, ${allFeed.routine.length} routine filings filtered out.` : "."}
            </p>
          </div>
          <CompanySearch dark className="hidden w-[360px] shrink-0 md:block" />
        </div>

        {/* Desktop/tablet: four tiles. Mobile: one portfolio card (the tiles become the list below). */}
        <div className="mt-6 hidden grid-cols-2 gap-3 md:grid xl:grid-cols-4">
          <HeroTile href="/portfolio" label="Portfolio value" value={pf ? inr(pf.total_value) : "—"}
            sub={pf ? <><Delta value={pf.day_change_pct} digits={2} className={dayTone === "up" ? "text-up" : "text-down"} /> on the day ({inr(Math.abs(pf.day_change_abs))})</> : "Loading…"} />
          <HeroTile href="/portfolio" label="Companies" value={pf?.holdings.length ?? "—"} sub={`${companiesWithNews} with major news`} />
          <HeroTile href="/announcements" label="Announcements, 24h" value={totalMaterial}
            sub={`${allFeed?.high_importance ?? 0} high importance, ${allFeed?.routine.length ?? 0} routine hidden`} />
          <HeroTile href="/alerts" label="Alerts" value={alerts?.today ?? 0} sub={`${alerts?.unseen ?? 0} unseen in the last 3 days`} />
        </div>
        <Link href="/portfolio" className="mt-5 flex items-center justify-between rounded-[14px] border border-ink-line bg-ink-2 px-4 py-3.5 md:hidden">
          <div>
            <p className="text-[12.5px] text-ink-muted">Portfolio value</p>
            <p className="num mt-1 text-[24px] font-semibold tracking-[-0.02em]">{pf ? inr(pf.total_value) : "—"}</p>
            {pf && <p className="mt-0.5 text-[12.5px]"><Delta value={pf.day_change_pct} digits={2} /> <span className="text-ink-muted">today</span></p>}
          </div>
          {pf && <Sparkline data={pf.history.slice(-30).map((h) => h.value)} width={120} height={48} />}
        </Link>
        <div className="mt-4"><Freshness status={status} /></div>
      </section>

      <div className="grid gap-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section className="min-w-0 xl:rounded-[var(--radius-lg)] xl:border xl:border-line xl:bg-surface">
          <header className="flex items-center justify-between pb-2 xl:px-5 xl:pt-4">
            <h2 className="text-[16px] font-semibold tracking-[-0.01em]">Top updates</h2>
            <Link href="/announcements" className="text-[13px] font-medium text-accent hover:underline">View all</Link>
          </header>
          <div className="pb-4 xl:px-5 xl:pb-5">
            <Chips options={chips} value={cat} onChange={setCat} className="mb-3 mt-1" />
            {feedErr ? <ErrorBox error={feedErr} onRetry={() => mutate()} /> : !feed ? <FeedSkeleton /> : feed.items.length === 0 ? (
              <Empty title={cat === "all" ? "Nothing material in the last 24 hours" : "Nothing in this category in the last 24 hours"}
                body={<>Routine filings are still collected. <Link href="/announcements" className="text-accent">Widen the window</Link> to see more.</>} />
            ) : (
              <div className="flex flex-col gap-2.5">
                {feed.items.slice(0, 8).map((i) => <FeedRow key={i.id} item={i} />)}
                {feed.items.length > 8 && (
                  <Link href="/announcements" className="py-2 text-center text-[13px] font-medium text-accent">
                    {feed.items.length - 8} more in the full digest
                  </Link>
                )}
                {cat === "all" && <RoutineGroup items={feed.routine} />}
              </div>
            )}
          </div>
        </section>

        <Panel title="Portfolio" action={<Link href="/portfolio" className="text-[13px] font-medium text-accent hover:underline">View all</Link>} className="hidden h-fit md:block">
          {pfErr ? <ErrorBox error={pfErr} /> : !pf ? <Skeleton className="h-64" /> : (
            <>
              <p className="num text-[26px] font-semibold tracking-[-0.02em]">{inr(pf.total_value)}</p>
              <p className="text-[13px]"><Delta value={pf.day_change_pct} digits={2} /> <span className="text-muted">({inr(pf.day_change_abs)}) on {dateShort(pf.as_of)}</span></p>
              <div className="mt-4"><RangeChart data={pf.history} height={170} compact /></div>
              <h3 className="mt-5 text-[13.5px] font-semibold">Top movers</h3>
              <ul className="mt-2 divide-y divide-line">
                {movers.map((h) => (
                  <li key={h.symbol}>
                    <Link href={`/research/${h.symbol}`} className="flex items-center gap-3 py-2.5 hover:opacity-80">
                      <span className="w-28 truncate text-[13px] font-medium">{h.symbol}</span>
                      <span className="num flex-1 text-right text-[12.5px] text-muted">{price(h.close)}</span>
                      <Delta value={h.change_pct} className="w-16 text-right text-[13px]" />
                    </Link>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Panel>
      </div>
    </div>
  );
}
