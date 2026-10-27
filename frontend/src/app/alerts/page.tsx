"use client";
import clsx from "clsx";
import { Check, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { FeedRow, FeedSkeleton } from "@/components/feed";
import { PageHeader } from "@/components/shell";
import { Button, Empty, ErrorBox, Panel, Segmented } from "@/components/ui";
import { post, useApi, type FeedItem, type Portfolio } from "@/lib/api";

type Rules = {
  price_pct: number; volume_mult: number; price_enabled: boolean; volume_enabled: boolean; categories: string[];
  overrides: Record<string, { price_pct?: number; volume_mult?: number }>; all_categories: { key: string; label: string }[];
};

function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}
      className={clsx("relative h-5 w-9 shrink-0 rounded-full transition-colors", on ? "bg-accent" : "bg-line-strong")}>
      <span className={clsx("absolute left-0.5 top-0.5 size-4 rounded-full bg-white shadow transition-transform", on ? "translate-x-4" : "translate-x-0")} />
    </button>
  );
}

function Threshold({ label, help, value, onChange, min, max, step, unit, enabled, onToggle }: {
  label: string; help: string; value: number; onChange: (v: number) => void; min: number; max: number; step: number; unit: string;
  enabled: boolean; onToggle: (v: boolean) => void;
}) {
  return (
    <div className={clsx("rounded-[var(--radius)] border border-line p-4", !enabled && "opacity-60")}>
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <p className="text-[13.5px] font-semibold">{label}</p>
          <p className="text-[12.5px] text-muted">{help}</p>
        </div>
        <Toggle on={enabled} onChange={onToggle} label={label} />
      </div>
      <div className="mt-3 flex items-center gap-3">
        <input type="range" min={min} max={max} step={step} value={value} disabled={!enabled}
          onChange={(e) => onChange(Number(e.target.value))} className="flex-1 accent-[var(--accent)]" aria-label={`${label} threshold`} />
        <div className="flex items-center rounded-[var(--radius-sm)] border border-line bg-surface">
          <input type="number" min={min} max={max} step={step} value={value} disabled={!enabled}
            onChange={(e) => onChange(Number(e.target.value))} className="num h-8 w-16 bg-transparent px-2 text-right text-[13px] outline-none" aria-label={`${label} value`} />
          <span className="pr-2 text-[12.5px] text-muted">{unit}</span>
        </div>
      </div>
    </div>
  );
}

function RulesEditor() {
  const { data, error, mutate } = useApi<Rules>("/api/alerts/rules", { revalidateOnFocus: false });
  const { data: pf } = useApi<Portfolio>("/api/portfolio");
  const [r, setR] = useState<Rules | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [ovSym, setOvSym] = useState("");
  useEffect(() => { if (data && !r) setR(data); }, [data, r]);
  if (error) return <ErrorBox error={error} />;
  if (!r) return <div className="skeleton h-80" />;
  const dirty = JSON.stringify({ ...r, all_categories: undefined }) !== JSON.stringify({ ...data, all_categories: undefined });

  async function save() {
    setSaving(true);
    try {
      const out = await post<Rules>("/api/alerts/rules", { ...r, all_categories: undefined }, "PUT");
      setR(out); mutate(out, false); setSaved(true); setTimeout(() => setSaved(false), 2000);
    } finally { setSaving(false); }
  }
  const set = (patch: Partial<Rules>) => setR({ ...r, ...patch });

  return (
    <div className="flex flex-col gap-3">
      <Threshold label="Price move" help="Alert when a holding closes up or down more than this in one day."
        value={r.price_pct} onChange={(v) => set({ price_pct: v })} min={0.5} max={15} step={0.5} unit="%"
        enabled={r.price_enabled} onToggle={(v) => set({ price_enabled: v })} />
      <Threshold label="Unusual volume" help="Alert when the day's volume is this many times its 20-day average."
        value={r.volume_mult} onChange={(v) => set({ volume_mult: v })} min={1.2} max={6} step={0.1} unit="×"
        enabled={r.volume_enabled} onToggle={(v) => set({ volume_enabled: v })} />

      <div className="rounded-[var(--radius)] border border-line p-4">
        <p className="text-[13.5px] font-semibold">Filings you care about</p>
        <p className="text-[12.5px] text-muted">Material filings in these categories raise an alert and rank higher in your brief.</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {r.all_categories.map((c) => {
            const on = r.categories.includes(c.key);
            return (
              <button key={c.key} aria-pressed={on}
                onClick={() => set({ categories: on ? r.categories.filter((x) => x !== c.key) : [...r.categories, c.key] })}
                className={clsx("inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12.5px] font-medium",
                  on ? "border-accent bg-accent-soft text-accent" : "border-line text-muted hover:text-text")}>
                {on && <Check className="size-3" />}{c.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="rounded-[var(--radius)] border border-line p-4">
        <p className="text-[13.5px] font-semibold">Per-stock thresholds</p>
        <p className="text-[12.5px] text-muted">A volatile small-cap and a utility shouldn't share one definition of unusual.</p>
        <ul className="mt-3 space-y-2">
          {Object.entries(r.overrides).map(([sym, ov]) => (
            <li key={sym} className="flex flex-wrap items-center gap-2 text-[13px]">
              <span className="w-28 font-semibold">{sym}</span>
              <label className="flex items-center gap-1 text-muted">±
                <input type="number" step={0.5} min={0.5} value={ov.price_pct ?? r.price_pct}
                  onChange={(e) => set({ overrides: { ...r.overrides, [sym]: { ...ov, price_pct: Number(e.target.value) } } })}
                  className="num h-8 w-16 rounded-[6px] border border-line bg-surface px-2 text-right" aria-label={`${sym} price threshold`} />%</label>
              <label className="flex items-center gap-1 text-muted">
                <input type="number" step={0.1} min={1.2} value={ov.volume_mult ?? r.volume_mult}
                  onChange={(e) => set({ overrides: { ...r.overrides, [sym]: { ...ov, volume_mult: Number(e.target.value) } } })}
                  className="num h-8 w-16 rounded-[6px] border border-line bg-surface px-2 text-right" aria-label={`${sym} volume threshold`} />× vol</label>
              <button onClick={() => { const o = { ...r.overrides }; delete o[sym]; set({ overrides: o }); }}
                className="ml-auto rounded p-1 text-faint hover:text-down" aria-label={`Remove ${sym} override`}><X className="size-3.5" /></button>
            </li>
          ))}
        </ul>
        <div className="mt-3 flex items-center gap-2">
          <select value={ovSym} onChange={(e) => setOvSym(e.target.value)} aria-label="Stock"
            className="h-8 rounded-[var(--radius-sm)] border border-line bg-surface px-2 text-[12.5px]">
            <option value="">Choose a holding</option>
            {pf?.holdings.filter((h) => !r.overrides[h.symbol]).map((h) => <option key={h.symbol}>{h.symbol}</option>)}
          </select>
          <Button size="sm" variant="outline" disabled={!ovSym} onClick={() => {
            set({ overrides: { ...r.overrides, [ovSym]: { price_pct: r.price_pct, volume_mult: r.volume_mult } } }); setOvSym("");
          }}><Plus className="size-3.5" />Add</Button>
        </div>
      </div>

      <div className="sticky bottom-[76px] flex items-center justify-end gap-2 rounded-[var(--radius)] bg-bg/90 py-2 backdrop-blur lg:bottom-0">
        {saved && <span className="text-[12.5px] text-up">Saved. Alerts and ranking updated.</span>}
        <Button variant="ghost" disabled={!dirty} onClick={() => setR(data!)}>Discard</Button>
        <Button onClick={save} loading={saving} disabled={!dirty}>Save alert settings</Button>
      </div>
    </div>
  );
}

export default function AlertsPage() {
  const [days, setDays] = useState<"3" | "7" | "30">("7");
  const { data, error, mutate } = useApi<{ items: FeedItem[]; unseen: number }>(`/api/alerts?days=${days}`);
  return (
    <div className="mx-auto max-w-[1200px]">
      <PageHeader title="Alerts" sub="You decide what unusual means. FINN checks every price update and filing against it." />
      <div className="grid gap-6 px-4 pb-10 sm:px-6 lg:grid-cols-[minmax(0,1fr)_400px] lg:px-8">
        <Panel pad={false} className="h-fit" title="Triggered"
          action={<div className="flex items-center gap-2">
            {(data?.unseen ?? 0) > 0 && <Button size="sm" variant="ghost" onClick={async () => { await post("/api/alerts/seen"); mutate(); }}>Mark all seen</Button>}
            <Segmented options={[{ key: "3", label: "3d" }, { key: "7", label: "7d" }, { key: "30", label: "30d" }]} value={days} onChange={setDays} />
          </div>}>
          <div className="flex flex-col gap-2.5 px-4 pb-4 sm:px-5 sm:pb-5">
            {error ? <ErrorBox error={error} /> : !data ? <FeedSkeleton /> : data.items.length === 0 ? (
              <Empty title="No alerts in this period" body="Nothing crossed your thresholds. Tighten them on the right if you want to hear more." />
            ) : data.items.map((i) => (
              <div key={i.id} className="relative">
                {!i.seen && <span className="absolute -left-2 top-5 size-1.5 rounded-full bg-accent" aria-label="Unseen" />}
                <FeedRow item={i} compact />
              </div>
            ))}
          </div>
        </Panel>
        <div>
          <h2 className="mb-3 text-[15px] font-semibold">What counts as unusual</h2>
          <RulesEditor />
        </div>
      </div>
    </div>
  );
}
