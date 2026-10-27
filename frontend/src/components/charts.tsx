"use client";
import { useMemo, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, ComposedChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { dateShort, inr, num, pct } from "@/lib/format";
import { Delta, Segmented } from "./ui";

const RANGES = [
  { key: "1W", label: "1W", days: 7 },
  { key: "1M", label: "1M", days: 31 },
  { key: "3M", label: "3M", days: 92 },
  { key: "1Y", label: "1Y", days: 366 },
  { key: "ALL", label: "All", days: 100000 },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

function sliceRange<T extends { date: string }>(data: T[], key: RangeKey): T[] {
  if (!data.length) return data;
  const days = RANGES.find((r) => r.key === key)!.days;
  const last = new Date(data[data.length - 1].date).getTime();
  return data.filter((d) => last - new Date(d.date).getTime() <= days * 86400000);
}

function TooltipBox({ active, payload, fmt }: any) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-[8px] border border-line bg-surface px-2.5 py-1.5 text-[12px] shadow-lg">
      <p className="text-faint">{dateShort(p.date)}</p>
      <p className="num font-semibold">{fmt(p.value ?? p.close)}</p>
    </div>
  );
}

/** Price/value area chart with range tabs. Shows the change over the visible range. */
export function RangeChart({ data, valueKey = "value", height = 200, fmt = (v: number) => inr(v), defaultRange = "1M" as RangeKey, compact }: {
  data: { date: string; [k: string]: any }[]; valueKey?: string; height?: number; fmt?: (v: number) => string;
  defaultRange?: RangeKey; compact?: boolean;
}) {
  const [range, setRange] = useState<RangeKey>(defaultRange);
  const visible = useMemo(() => sliceRange(data, range), [data, range]);
  const first = visible[0]?.[valueKey], last = visible[visible.length - 1]?.[valueKey];
  const change = first && last ? (last / first - 1) * 100 : null;
  const color = (change ?? 0) >= 0 ? "var(--up)" : "var(--down)";
  const gid = `rc-${valueKey}-${height}`;
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <Segmented options={RANGES.map((r) => ({ key: r.key, label: r.label }))} value={range} onChange={setRange} />
        {change !== null && (
          <span className="text-[12px] text-muted"><Delta value={change} /> {range === "ALL" ? "all time" : `over ${range}`}</span>
        )}
      </div>
      <div style={{ height }} className="mt-3 -ml-2">
        {visible.length > 1 ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={visible} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor={color} stopOpacity={0.2} />
                  <stop offset="1" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              {!compact && <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="0" />}
              <XAxis dataKey="date" tickLine={false} axisLine={false} minTickGap={40} tick={{ fill: "var(--faint)", fontSize: 11 }}
                tickFormatter={(d) => new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} hide={compact} />
              <YAxis domain={["auto", "auto"]} orientation="right" tickLine={false} axisLine={false} width={compact ? 0 : 64}
                tick={{ fill: "var(--faint)", fontSize: 11 }} tickFormatter={(v) => num(v)} hide={compact} />
              <Tooltip content={<TooltipBox fmt={fmt} />} cursor={{ stroke: "var(--line-strong)" }} />
              <Area type="monotone" dataKey={valueKey} stroke={color} strokeWidth={1.75} fill={`url(#${gid})`} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="grid h-full place-items-center text-[12.5px] text-faint">Not enough price history yet</div>
        )}
      </div>
    </div>
  );
}

export function TrajectoryChart({ rows, revLabel = "Revenue" }: { rows: any[]; revLabel?: string }) {
  if (!rows?.length) return null;
  return (
    <div className="h-[220px] -ml-2">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "var(--faint)", fontSize: 11 }} />
          <YAxis yAxisId="v" tickLine={false} axisLine={false} width={58} tick={{ fill: "var(--faint)", fontSize: 11 }}
            tickFormatter={(v) => (v >= 100000 ? `${(v / 100000).toFixed(1)}L` : num(v))} />
          <YAxis yAxisId="m" orientation="right" tickLine={false} axisLine={false} width={36} tick={{ fill: "var(--faint)", fontSize: 11 }}
            tickFormatter={(v) => `${v}%`} />
          <Tooltip
            content={({ active, payload }: any) => {
              if (!active || !payload?.length) return null;
              const p = payload[0].payload;
              return (
                <div className="num rounded-[8px] border border-line bg-surface px-2.5 py-1.5 text-[12px] shadow-lg">
                  <p className="font-semibold">{p.label}</p>
                  <p>{revLabel}: ₹{num(p.revenue)} cr</p>
                  <p>PAT: ₹{num(p.pat)} cr</p>
                  {p.ebitda_margin != null && <p>EBITDA margin: {p.ebitda_margin}%</p>}
                </div>
              );
            }} />
          <Bar yAxisId="v" dataKey="revenue" fill="var(--accent)" fillOpacity={0.22} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          <Bar yAxisId="v" dataKey="pat" fill="var(--accent)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
          <Line yAxisId="m" dataKey="ebitda_margin" stroke="var(--warn)" strokeWidth={1.75} dot={{ r: 2.5 }} isAnimationActive={false} connectNulls />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

const DONUT = ["#2f6bff", "#12995a", "#8b5cf6", "#c27c0e", "#0e8fb0", "#8d96a6", "#d9434a"];

export function SegmentDonut({ segments }: { segments: { name: string; share_pct: number | null; revenue: number }[] }) {
  const data = segments.filter((s) => s.share_pct).sort((a, b) => (b.share_pct ?? 0) - (a.share_pct ?? 0));
  if (!data.length) return null;
  return (
    <div className="flex items-center gap-5">
      <div className="size-[120px] shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="share_pct" nameKey="name" innerRadius={38} outerRadius={58} paddingAngle={1.5} stroke="none" isAnimationActive={false}>
              {data.map((_, i) => <Cell key={i} fill={DONUT[i % DONUT.length]} />)}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="min-w-0 flex-1 space-y-1.5 text-[12.5px]">
        {data.map((s, i) => (
          <li key={s.name} className="flex items-center gap-2">
            <span className="size-2 shrink-0 rounded-full" style={{ background: DONUT[i % DONUT.length] }} />
            <span className="flex-1 truncate">{s.name}</span>
            <span className="num font-medium">{pct(s.share_pct, 0, false)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function MiniBars({ data }: { data: { label: string; value: number | null }[] }) {
  return (
    <div className="h-[120px] -ml-2">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "var(--faint)", fontSize: 11 }} />
          <Bar dataKey="value" radius={[3, 3, 0, 0]} isAnimationActive={false}>
            {data.map((d, i) => <Cell key={i} fill={(d.value ?? 0) >= 0 ? "var(--up)" : "var(--down)"} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
