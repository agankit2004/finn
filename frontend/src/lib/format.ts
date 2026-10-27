const IST = "Asia/Kolkata";

/** ₹12,48,231 — Indian digit grouping. */
export function inr(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return "₹" + v.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function price(v: number | null | undefined): string {
  return inr(v, 2);
}

/** Amounts already in ₹ crore. Large values switch to lakh crore. */
export function crore(v: number | null | undefined, opts: { short?: boolean } = {}): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  if (opts.short && a >= 100000) return `₹${(v / 100000).toLocaleString("en-IN", { maximumFractionDigits: 2 })} L cr`;
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: a >= 100 ? 0 : 1 })} cr`;
}

export function num(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function pct(v: number | null | undefined, digits = 1, signed = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = v.toFixed(digits);
  return (signed && v > 0 ? "+" : "") + s + "%";
}

export function toneOf(v: number | null | undefined): "up" | "down" | "flat" {
  if (v === null || v === undefined || Math.abs(v) < 0.005) return "flat";
  return v > 0 ? "up" : "down";
}

function istParts(d: Date) {
  const f = new Intl.DateTimeFormat("en-IN", { timeZone: IST, year: "numeric", month: "2-digit", day: "2-digit" });
  return f.format(d);
}

/** "Today · 4:15 PM", "Yesterday · 9:40 AM", "24 Oct · 11:20 AM" (IST). */
export function when(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const day = istParts(d);
  const today = istParts(now);
  const yest = istParts(new Date(now.getTime() - 86400000));
  const time = d.toLocaleTimeString("en-IN", { timeZone: IST, hour: "numeric", minute: "2-digit", hour12: true }).toUpperCase();
  const label =
    day === today ? "Today" : day === yest ? "Yesterday"
      : d.toLocaleDateString("en-IN", { timeZone: IST, day: "numeric", month: "short", ...(d.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}) });
  return withTime ? `${label}, ${time}` : label;
}

export function dateShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length <= 10 ? iso + "T12:00:00+05:30" : iso);
  return d.toLocaleDateString("en-IN", { timeZone: IST, day: "numeric", month: "short", year: "numeric" });
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function greeting(): string {
  const h = Number(new Date().toLocaleString("en-IN", { timeZone: IST, hour: "numeric", hour12: false }));
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export const CATEGORY_TAG: Record<string, string> = {
  results: "tag-results", management_change: "tag-mgmt", "M&A": "tag-ma", price: "tag-price", fund_raise: "tag-fund",
  litigation: "tag-legal", credit_rating: "tag-rating", capex: "tag-capex", press_release: "tag-press",
  earnings_call: "tag-call", investor_meetings: "tag-call", dividend: "tag-corp", bonus_split: "tag-corp",
  insider_trading: "tag-legal", pledging: "tag-legal", agm_egm: "tag-routine", postal_ballot: "tag-routine",
  unclassified: "tag-routine",
};

export const FILTERS: { key: string; label: string }[] = [
  { key: "all", label: "All" },
  { key: "results", label: "Results" },
  { key: "price", label: "Price" },
  { key: "M&A", label: "M&A" },
  { key: "management_change", label: "Management" },
  { key: "fund_raise", label: "Fund raise" },
  { key: "litigation", label: "Litigation" },
  { key: "credit_rating", label: "Ratings" },
  { key: "capex", label: "Capex" },
  { key: "press_release", label: "Press" },
  { key: "dividend", label: "Dividend" },
  { key: "earnings_call", label: "Concalls" },
];
