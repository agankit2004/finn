"use client";
import clsx from "clsx";
import { AlertTriangle, Loader2 } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { CATEGORY_TAG, pct, toneOf } from "@/lib/format";

export function Panel({ children, className, title, action, pad = true, id }: {
  children: ReactNode; className?: string; title?: ReactNode; action?: ReactNode; pad?: boolean; id?: string;
}) {
  return (
    <section id={id} className={clsx("rounded-[var(--radius-lg)] border border-line bg-surface", className)}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 px-4 pt-4 pb-2 sm:px-5">
          {typeof title === "string" ? <h2 className="text-[15px] font-semibold tracking-[-0.01em]">{title}</h2> : title}
          {action}
        </header>
      )}
      <div className={clsx(pad && "px-4 pb-4 sm:px-5 sm:pb-5", !title && !action && pad && "pt-4 sm:pt-5")}>{children}</div>
    </section>
  );
}

export function Tag({ category, label, className }: { category: string; label: string; className?: string }) {
  return (
    <span className={clsx("tag inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[11.5px] font-medium leading-4",
      CATEGORY_TAG[category] ?? "tag-routine", className)}>
      <span className="size-1.5 rounded-full bg-current" aria-hidden />
      {label}
    </span>
  );
}

export function Delta({ value, className, digits = 1, suffix }: { value: number | null | undefined; className?: string; digits?: number; suffix?: string }) {
  const t = toneOf(value);
  return (
    <span className={clsx("num font-medium", t === "up" && "text-up", t === "down" && "text-down", t === "flat" && "text-muted", className)}>
      {pct(value, digits)}{suffix}
    </span>
  );
}

export function Sparkline({ data, width = 96, height = 32, tone, className }: {
  data: number[]; width?: number; height?: number; tone?: "up" | "down" | "flat"; className?: string;
}) {
  if (!data || data.length < 2) return <div style={{ width, height }} className={className} />;
  const min = Math.min(...data), max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => [(i / (data.length - 1)) * width, height - 2 - ((v - min) / span) * (height - 4)]);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
  const t = tone ?? (data[data.length - 1] >= data[0] ? "up" : "down");
  const color = t === "up" ? "var(--up)" : t === "down" ? "var(--down)" : "var(--faint)";
  const id = `sg${Math.round(data[0] * 1000)}${data.length}${t}`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={className} aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.18" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${d}L${width},${height}L0,${height}Z`} fill={`url(#${id})`} />
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/** Importance as four ticks: what FINN thinks this is worth, at a glance. */
export function Signal({ score, className }: { score: number; className?: string }) {
  const level = score >= 85 ? 4 : score >= 70 ? 3 : score >= 50 ? 2 : score >= 30 ? 1 : 0;
  return (
    <span className={clsx("inline-flex items-end gap-[2px]", className)} title={`Importance ${score}/100`} aria-label={`Importance ${score} of 100`}>
      {[0, 1, 2, 3].map((i) => (
        <span key={i} className={clsx("w-[3px] rounded-[1px]", i < level ? (level >= 3 ? "bg-accent" : "bg-muted") : "bg-line-strong")}
          style={{ height: 5 + i * 3 }} />
      ))}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton", className)} />;
}

export function Empty({ title, body, action }: { title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-10 text-center">
      <p className="text-[14px] font-medium">{title}</p>
      {body && <div className="mt-1 max-w-sm text-[13px] text-muted">{body}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: any; onRetry?: () => void }) {
  return (
    <div className="flex items-start gap-3 rounded-[var(--radius)] border border-down/25 bg-down/5 p-3.5 text-[13px]">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-down" />
      <div className="flex-1">
        <p className="font-medium">{error?.status === 0 ? "FINN server not reachable" : "Something didn't load"}</p>
        <p className="mt-0.5 text-muted">{String(error?.message ?? error)}</p>
      </div>
      {onRetry && <Button size="sm" variant="ghost" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function Button({ children, onClick, variant = "primary", size = "md", className, disabled, href, type, loading }: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "ghost" | "outline" | "ink";
  size?: "sm" | "md"; className?: string; disabled?: boolean; href?: string; type?: "button" | "submit"; loading?: boolean;
}) {
  const cls = clsx(
    "inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-sm)] font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none",
    size === "sm" ? "h-8 px-2.5 text-[12.5px]" : "h-10 px-3.5 text-[13.5px]",
    variant === "primary" && "bg-accent text-white hover:brightness-110",
    variant === "ghost" && "text-muted hover:bg-surface-2 hover:text-text",
    variant === "outline" && "border border-line bg-surface hover:bg-surface-2",
    variant === "ink" && "bg-ink-3 text-ink-text hover:bg-ink-line",
    className);
  if (href) return <Link href={href} className={cls} onClick={onClick}>{children}</Link>;
  return (
    <button type={type ?? "button"} onClick={onClick} disabled={disabled || loading} className={cls}>
      {loading && <Loader2 className="size-3.5 animate-spin" />}
      {children}
    </button>
  );
}

export function Chips<T extends string>({ options, value, onChange, className, dark }: {
  options: { key: T; label: string; count?: number }[]; value: T; onChange: (v: T) => void; className?: string; dark?: boolean;
}) {
  return (
    <div className={clsx("scrollbar-none -mx-1 flex gap-1.5 overflow-x-auto px-1", className)} role="tablist">
      {options.map((o) => {
        const on = o.key === value;
        return (
          <button key={o.key} role="tab" aria-selected={on} onClick={() => onChange(o.key)}
            className={clsx("h-8 shrink-0 rounded-full px-3 text-[12.5px] font-medium transition-colors",
              dark
                ? on ? "bg-ink-text text-ink" : "bg-ink-3 text-ink-muted hover:text-ink-text"
                : on ? "bg-text text-surface" : "border border-line bg-surface text-muted hover:text-text")}>
            {o.label}
            {o.count !== undefined && o.count > 0 && <span className={clsx("num ml-1.5", on ? "opacity-70" : "text-faint")}>{o.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

export function Segmented<T extends string>({ options, value, onChange, className }: {
  options: { key: T; label: string }[]; value: T; onChange: (v: T) => void; className?: string;
}) {
  return (
    <div className={clsx("inline-flex rounded-[var(--radius-sm)] bg-surface-2 p-0.5", className)} role="tablist">
      {options.map((o) => (
        <button key={o.key} role="tab" aria-selected={o.key === value} onClick={() => onChange(o.key)}
          className={clsx("h-7 rounded-[6px] px-2.5 text-[12px] font-medium transition-colors",
            o.key === value ? "bg-surface text-text shadow-[0_1px_2px_rgba(15,23,42,0.08)]" : "text-muted hover:text-text")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Stat({ label, value, sub, className }: { label: string; value: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div className={clsx("min-w-0", className)}>
      <p className="text-[12px] text-muted">{label}</p>
      <p className="num mt-0.5 truncate text-[15px] font-semibold">{value}</p>
      {sub && <div className="mt-0.5 text-[12px] text-muted">{sub}</div>}
    </div>
  );
}
