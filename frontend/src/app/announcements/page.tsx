"use client";
import { useMemo, useState } from "react";
import { FeedRow, FeedSkeleton, RoutineGroup } from "@/components/feed";
import { PageHeader } from "@/components/shell";
import { Chips, Empty, ErrorBox, Segmented } from "@/components/ui";
import { useApi, type Feed, type Portfolio } from "@/lib/api";
import { dateShort, FILTERS } from "@/lib/format";

const WINDOWS = [
  { key: "24", label: "24h" },
  { key: "72", label: "3 days" },
  { key: "168", label: "7 days" },
  { key: "720", label: "30 days" },
  { key: "custom", label: "Custom" },
] as const;
type WinKey = (typeof WINDOWS)[number]["key"];

function isoDay(d: Date) {
  return new Date(d.getTime() + 5.5 * 3600000).toISOString().slice(0, 10);
}

export default function Announcements() {
  const [win, setWin] = useState<WinKey>("24");
  const [start, setStart] = useState(isoDay(new Date(Date.now() - 7 * 86400000)));
  const [end, setEnd] = useState(isoDay(new Date()));
  const [cat, setCat] = useState("all");
  const [sort, setSort] = useState<"priority" | "time">("priority");
  const [sym, setSym] = useState("");
  const { data: pf } = useApi<Portfolio>("/api/portfolio");

  const base = win === "custom" ? `start=${start}&end=${end}&hours=2160` : `hours=${win}`;
  const q = `/api/feed?${base}&sort=${sort}${sym ? `&symbol=${sym}` : ""}`;
  const { data: all } = useApi<Feed>(q);
  const { data, error, mutate } = useApi<Feed>(`${q}&category=${encodeURIComponent(cat)}`);

  const chips = useMemo(() => {
    const counts = all?.counts ?? {};
    const total = all?.items.length ?? 0;
    return FILTERS.filter((f) => f.key === "all" || counts[f.key]).map((f) => ({ ...f, count: f.key === "all" ? total : counts[f.key] }));
  }, [all]);

  return (
    <div className="mx-auto max-w-[1100px]">
      <PageHeader title="Announcements"
        sub="Every exchange filing across your portfolio, ranked by what it means for you. Routine paperwork is collapsed, not deleted." />
      <div className="px-4 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-center gap-2.5">
          <Segmented options={WINDOWS.map((w) => ({ key: w.key, label: w.label }))} value={win} onChange={setWin} />
          {win === "custom" && (
            <div className="flex items-center gap-1.5 text-[12.5px]">
              <input type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)}
                className="h-8 rounded-[6px] border border-line bg-surface px-2" aria-label="From" />
              <span className="text-faint">to</span>
              <input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)}
                className="h-8 rounded-[6px] border border-line bg-surface px-2" aria-label="To" />
            </div>
          )}
          <div className="ml-auto flex items-center gap-2">
            <select value={sym} onChange={(e) => setSym(e.target.value)} aria-label="Company"
              className="h-8 rounded-[var(--radius-sm)] border border-line bg-surface px-2 text-[12.5px]">
              <option value="">All companies</option>
              {pf?.holdings.map((h) => <option key={h.symbol} value={h.symbol}>{h.symbol}</option>)}
            </select>
            <Segmented options={[{ key: "priority", label: "Priority" }, { key: "time", label: "Latest" }]} value={sort} onChange={setSort} />
          </div>
        </div>
        <Chips options={chips} value={cat} onChange={setCat} className="mt-3" />
        {all && (
          <p className="mt-3 text-[12.5px] text-muted">
            {all.total} item{all.total === 1 ? "" : "s"} {win === "custom" ? `from ${dateShort(start)} to ${dateShort(end)}` : `in the last ${WINDOWS.find((w) => w.key === win)?.label}`}:
            {" "}{all.items.length} worth reading, {all.routine.length} routine.
          </p>
        )}
        <div className="mt-3 flex flex-col gap-2.5 pb-8">
          {error ? <ErrorBox error={error} onRetry={() => mutate()} /> : !data ? <FeedSkeleton n={6} /> : (
            <>
              {data.items.length === 0 && (
                <Empty title="Nothing material in this window"
                  body={data.routine.length ? "Only routine filings came in. They're listed below." : "Try a longer window, or check Settings for data-source status."} />
              )}
              {data.items.map((i) => <FeedRow key={i.id} item={i} />)}
              <RoutineGroup items={data.routine} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
