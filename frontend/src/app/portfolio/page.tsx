"use client";
import clsx from "clsx";
import { Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { RangeChart } from "@/components/charts";
import { PageHeader } from "@/components/shell";
import { Button, Delta, Empty, ErrorBox, Panel, Segmented, Skeleton, Sparkline } from "@/components/ui";
import { post, useApi, type Holding, type Portfolio } from "@/lib/api";
import { dateShort, inr, num, price, toneOf } from "@/lib/format";

function RangeBar({ lo, hi, v }: { lo: number | null; hi: number | null; v: number | null }) {
  if (lo == null || hi == null || v == null || hi <= lo) return <span className="text-faint">—</span>;
  const p = Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  return (
    <div className="w-24" title={`52-week range ${price(lo)} to ${price(hi)}`}>
      <div className="relative h-1 rounded-full bg-line">
        <span className="absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-text" style={{ left: `${p}%` }} />
      </div>
      <div className="num mt-1 flex justify-between text-[10.5px] text-faint"><span>{num(lo)}</span><span>{num(hi)}</span></div>
    </div>
  );
}

function AddHolding({ onDone }: { onDone: () => void }) {
  const [sym, setSym] = useState("");
  const [qty, setQty] = useState("10");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <form className="flex flex-wrap items-center gap-2" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true); setErr(null);
      try { await post("/api/portfolio/holdings", { symbol: sym, quantity: Number(qty) || 0 }); setSym(""); onDone(); }
      catch (e: any) { setErr(e.message); } finally { setBusy(false); }
    }}>
      <input value={sym} onChange={(e) => setSym(e.target.value.toUpperCase())} placeholder="NSE symbol" required
        className="h-9 w-32 rounded-[var(--radius-sm)] border border-line bg-surface px-2.5 text-[13px] uppercase" aria-label="NSE symbol" />
      <input value={qty} onChange={(e) => setQty(e.target.value)} type="number" min="0" step="1"
        className="num h-9 w-20 rounded-[var(--radius-sm)] border border-line bg-surface px-2.5 text-[13px]" aria-label="Quantity" />
      <Button type="submit" size="sm" loading={busy}><Plus className="size-3.5" />Add</Button>
      {err && <span className="w-full text-[12px] text-down">{err}</span>}
    </form>
  );
}

export default function PortfolioPage() {
  const { data, error, mutate } = useApi<Portfolio>("/api/portfolio");
  const [sort, setSort] = useState<"value" | "move" | "name">("value");
  const [adding, setAdding] = useState(false);
  const rows = useMemo(() => {
    const h = [...(data?.holdings ?? [])];
    if (sort === "move") h.sort((a, b) => Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0));
    if (sort === "name") h.sort((a, b) => a.symbol.localeCompare(b.symbol));
    return h;
  }, [data, sort]);

  async function remove(h: Holding) {
    if (!confirm(`Remove ${h.symbol} from the portfolio? Its filings will stop appearing in your brief.`)) return;
    await post(`/api/portfolio/holdings/${h.symbol}`, undefined, "DELETE");
    mutate();
  }

  return (
    <div className="mx-auto max-w-[1200px]">
      <PageHeader title="Portfolio"
        sub={data ? <>Demo portfolio with illustrative quantities. End-of-day prices as of {dateShort(data.as_of)}.</> : "Loading…"}
        action={<Button variant="outline" size="sm" onClick={() => setAdding((a) => !a)}><Plus className="size-3.5" />Add company</Button>} />
      <div className="flex flex-col gap-5 px-4 pb-8 sm:px-6 lg:px-8">
        {adding && <Panel><AddHolding onDone={() => { setAdding(false); mutate(); }} /><p className="mt-2 text-[12px] text-faint">Any NSE symbol. FINN starts tracking its prices and filings right away.</p></Panel>}
        {error && <ErrorBox error={error} onRetry={() => mutate()} />}
        <Panel>
          {!data ? <Skeleton className="h-72" /> : (
            <>
              <div className="flex flex-wrap items-end gap-x-6 gap-y-1">
                <p className="num text-[30px] font-semibold tracking-[-0.025em]">{inr(data.total_value)}</p>
                <p className="pb-1.5 text-[13px]"><Delta value={data.day_change_pct} digits={2} /> <span className="text-muted">({inr(data.day_change_abs)}) on the last session</span></p>
              </div>
              <div className="mt-4"><RangeChart data={data.history} height={240} defaultRange="3M" /></div>
              <p className="mt-2 text-[11.5px] text-faint">Value of current holdings at each day's closing price. Days missing a price for any holding are left out.</p>
            </>
          )}
        </Panel>

        <Panel pad={false} title={`Holdings${data ? ` (${data.holdings.length})` : ""}`}
          action={<Segmented options={[{ key: "value", label: "Value" }, { key: "move", label: "Day move" }, { key: "name", label: "A–Z" }]} value={sort} onChange={setSort} />}>
          {!data ? <div className="p-5"><Skeleton className="h-48" /></div> : rows.length === 0 ? (
            <Empty title="No holdings yet" body="Add an NSE symbol to start tracking it." />
          ) : (
            <>
              <table className="num hidden w-full text-[13px] md:table">
                <thead className="border-y border-line bg-surface-2 text-[11.5px] text-muted">
                  <tr>
                    <th className="px-5 py-2 text-left font-medium">Company</th>
                    <th className="px-3 py-2 text-right font-medium">Qty</th>
                    <th className="px-3 py-2 text-right font-medium">Close</th>
                    <th className="px-3 py-2 text-right font-medium">Day</th>
                    <th className="px-3 py-2 text-right font-medium">Value</th>
                    <th className="px-3 py-2 text-right font-medium">Weight</th>
                    <th className="px-3 py-2 text-left font-medium">52-week range</th>
                    <th className="px-3 py-2 text-left font-medium">30 days</th>
                    <th className="w-10" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((h) => (
                    <tr key={h.symbol} className="group border-b border-line last:border-0 hover:bg-surface-2/60">
                      <td className="px-5 py-2.5">
                        <Link href={`/research/${h.symbol}`} className="block">
                          <span className="font-semibold">{h.symbol}</span>
                          <span className="block max-w-[220px] truncate text-[12px] text-muted">{h.name}</span>
                        </Link>
                      </td>
                      <td className="px-3 py-2.5 text-right">{num(h.quantity)}</td>
                      <td className="px-3 py-2.5 text-right">{price(h.close)}</td>
                      <td className="px-3 py-2.5 text-right">
                        <Delta value={h.change_pct} digits={2} />
                        {h.volume_mult != null && h.volume_mult >= 1.8 && <span className="block text-[11px] text-warn">{h.volume_mult.toFixed(1)}× vol</span>}
                      </td>
                      <td className="px-3 py-2.5 text-right font-medium">{inr(h.value)}</td>
                      <td className="px-3 py-2.5 text-right text-muted">{h.weight?.toFixed(1)}%</td>
                      <td className="px-3 py-2.5"><RangeBar lo={h.low_52w} hi={h.high_52w} v={h.close} /></td>
                      <td className="px-3 py-2.5"><Sparkline data={h.spark} width={80} height={26} /></td>
                      <td className="pr-3">
                        <button onClick={() => remove(h)} className="rounded p-1.5 text-faint opacity-0 hover:bg-surface-2 hover:text-down group-hover:opacity-100 focus:opacity-100" aria-label={`Remove ${h.symbol}`}>
                          <Trash2 className="size-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <ul className="divide-y divide-line border-t border-line md:hidden">
                {rows.map((h) => (
                  <li key={h.symbol}>
                    <Link href={`/research/${h.symbol}`} className="flex items-center gap-3 px-4 py-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-[14px] font-semibold">{h.symbol}</p>
                        <p className="num truncate text-[12px] text-muted">{num(h.quantity)} × {price(h.close)} · {h.weight?.toFixed(1)}%</p>
                      </div>
                      <Sparkline data={h.spark} width={64} height={28} />
                      <div className="num w-24 text-right">
                        <p className="text-[13.5px] font-medium">{inr(h.value)}</p>
                        <Delta value={h.change_pct} digits={2} className={clsx("text-[12.5px]", toneOf(h.change_pct) === "flat" && "text-muted")} />
                      </div>
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
