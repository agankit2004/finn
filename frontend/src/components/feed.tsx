"use client";
import clsx from "clsx";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { FeedItem } from "@/lib/api";
import { price, toneOf, when } from "@/lib/format";
import { useItemSheet } from "./shell";
import { Delta, Signal, Sparkline, Tag } from "./ui";

export function FeedRow({ item, compact }: { item: FeedItem; compact?: boolean }) {
  const { open } = useItemSheet();
  const t = toneOf(item.price?.change_pct);
  return (
    <button onClick={() => open(item)}
      className={clsx("group flex w-full items-stretch gap-4 rounded-[var(--radius)] border border-line bg-surface text-left transition-colors hover:border-line-strong hover:bg-surface-2/60",
        compact ? "px-3.5 py-3" : "px-4 py-3.5")}>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[12px] text-faint">
          <Tag category={item.category} label={item.category_label} />
          <span>{when(item.time)}</span>
          {item.type !== "announcement" && <span>· EOD</span>}
          <Signal score={item.importance} className="ml-auto sm:ml-1" />
        </div>
        <p className={clsx("mt-1.5 font-semibold leading-snug tracking-[-0.01em] text-text", compact ? "text-[14px]" : "text-[15px]")}>{item.title}</p>
        {item.summary ? (
          <p className="mt-1 line-clamp-2 text-[13px] text-muted">{item.summary}</p>
        ) : item.enrich_status === "needs_key" ? (
          <p className="mt-1 text-[12.5px] text-faint">Add a Gemini key to get FINN's read of this filing.</p>
        ) : null}
        <div className="mt-1.5 flex items-center gap-2 text-[12px] sm:hidden">
          <span className="font-semibold">{item.company.symbol}</span>
          <span className="num text-muted">{price(item.price?.close)}</span>
          <Delta value={item.price?.change_pct} digits={1} />
        </div>
      </div>
      <div className="hidden w-[190px] shrink-0 items-center gap-3 border-l border-line pl-4 sm:flex">
        <div className="min-w-0 flex-1">
          <p className="text-[12.5px] font-semibold">{item.company.symbol}</p>
          <p className="num text-[14px] font-medium">{price(item.price?.close)}</p>
          <Delta value={item.price?.change_pct} className="text-[12.5px]" />
        </div>
        <Sparkline data={item.price?.spark ?? []} width={84} height={36} tone={t} />
      </div>
      <ChevronRight className="hidden size-4 self-center text-faint max-sm:block" />
    </button>
  );
}

export function RoutineGroup({ items }: { items: FeedItem[] }) {
  const [open, setOpen] = useState(false);
  const { open: openItem } = useItemSheet();
  if (!items.length) return null;
  const syms = Array.from(new Set(items.map((i) => i.company.symbol)));
  return (
    <div className="rounded-[var(--radius)] border border-dashed border-line-strong">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-3 px-4 py-3 text-left" aria-expanded={open}>
        <span className="min-w-0 flex-1">
          <span className="text-[13.5px] font-medium">{items.length} routine filing{items.length > 1 ? "s" : ""} hidden</span>
          <span className="block truncate text-[12px] text-faint">
            Trading-window closures, ESOP allotments, compliance certificates and similar, from {syms.slice(0, 5).join(", ")}{syms.length > 5 ? ` +${syms.length - 5}` : ""}
          </span>
        </span>
        <ChevronDown className={clsx("size-4 text-faint transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ul className="anim-fade border-t border-line">
          {items.map((i) => (
            <li key={i.id}>
              <button onClick={() => openItem(i)} className="flex w-full items-center gap-3 px-4 py-2 text-left hover:bg-surface-2">
                <span className="w-24 shrink-0 text-[12.5px] font-semibold">{i.company.symbol}</span>
                <span className="flex-1 truncate text-[12.5px] text-muted">{i.subject ?? i.title}</span>
                <span className="hidden shrink-0 text-[11.5px] text-faint sm:block">{when(i.time)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function FeedSkeleton({ n = 4 }: { n?: number }) {
  return (
    <div className="flex flex-col gap-2.5">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="rounded-[var(--radius)] border border-line bg-surface p-4">
          <div className="skeleton h-4 w-40" />
          <div className="skeleton mt-3 h-4 w-3/4" />
          <div className="skeleton mt-2 h-3 w-1/2" />
        </div>
      ))}
    </div>
  );
}
