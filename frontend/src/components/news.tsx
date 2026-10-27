"use client";
import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useApi } from "@/lib/api";
import { ago, when } from "@/lib/format";
import { Empty, Panel, Skeleton } from "./ui";

type Story = {
  id: number; title: string; url: string; source: string | null; time: string; latest: string;
  company: { symbol: string; name: string }; also: { source: string | null; url: string }[];
};
type News = { stories: Story[]; total: number; checked: string | null; status: string | null; sample: boolean };

function StoryRow({ s, showSymbol }: { s: Story; showSymbol: boolean }) {
  const others = Array.from(new Set(s.also.map((a) => a.source).filter(Boolean))) as string[];
  return (
    <li className="py-3 first:pt-1 last:pb-0">
      <div className="flex items-center gap-2 text-[11.5px] text-faint">
        {showSymbol && (
          <Link href={`/research/${s.company.symbol}`} className="rounded bg-surface-2 px-1.5 py-0.5 font-semibold text-muted hover:text-text">{s.company.symbol}</Link>
        )}
        <span className="truncate">{s.source ?? "News"}</span>
        <span className="shrink-0">· {when(s.time)}</span>
      </div>
      <a href={s.url} target="_blank" rel="noreferrer" className="group mt-1 block text-[13.5px] font-medium leading-snug hover:text-accent">
        {s.title}
        <ExternalLink className="ml-1 inline size-3 -translate-y-px text-faint group-hover:text-accent" />
      </a>
      {others.length > 0 && (
        <p className="mt-1 text-[11.5px] text-faint">Also reported by {others.slice(0, 3).join(", ")}{others.length > 3 ? ` and ${others.length - 3} more` : ""}</p>
      )}
    </li>
  );
}

export function NewsPanel({ symbol, hours = 48, limit = 6, className, title = "In the news" }: {
  symbol?: string; hours?: number; limit?: number; className?: string; title?: string;
}) {
  const q = `/api/news?hours=${hours}&limit=${limit}${symbol ? `&symbol=${symbol}` : ""}`;
  const { data, error } = useApi<News>(q, { refreshInterval: 5 * 60000 });
  return (
    <Panel className={className} title={title}
      action={data?.total ? <span className="text-[11.5px] text-faint">{data.total} stor{data.total === 1 ? "y" : "ies"}, {hours < 48 ? `${hours}h` : `${Math.round(hours / 24)}d`}</span> : null}>
      {error ? <p className="text-[12.5px] text-muted">Headlines didn't load.</p> : !data ? <Skeleton className="h-40" /> : data.stories.length === 0 ? (
        <Empty title="No headlines yet"
          body={data.status === "failed" ? "The news source couldn't be reached from this machine. FINN will retry on the next refresh." : "FINN checks Google News for your companies every 30 minutes."} />
      ) : (
        <ul className="divide-y divide-line">
          {data.stories.map((s) => <StoryRow key={s.id} s={s} showSymbol={!symbol} />)}
        </ul>
      )}
      <p className="mt-3 text-[11px] leading-relaxed text-faint">
        Headlines via Google News{data?.checked ? `, checked ${ago(data.checked)}` : ""}. Same story from several publishers is shown once.
        News is secondary: FINN links out to it but never uses it as research evidence.
      </p>
    </Panel>
  );
}
