"use client";
import useSWR, { SWRConfiguration } from "swr";

/** Backend base URL. Defaults to the same host on port 8000, so opening the app from a phone on the
 *  same Wi-Fi (http://192.168.x.x:3000) automatically talks to http://192.168.x.x:8000. */
export function apiBase(): string {
  const env = process.env.NEXT_PUBLIC_API_URL;
  if (env) return env.replace(/\/$/, "");
  if (typeof window !== "undefined") return `${window.location.protocol}//${window.location.hostname}:8000`;
  return "http://localhost:8000";
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handle(r: Response) {
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {}
    throw new ApiError(r.status, msg);
  }
  return r.json();
}

export const fetcher = (path: string) =>
  fetch(apiBase() + path, { cache: "no-store" })
    .catch(() => {
      throw new ApiError(0, "Can't reach the FINN server. Is the backend running on port 8000?");
    })
    .then(handle);

export async function post<T = any>(path: string, body?: unknown, method = "POST"): Promise<T> {
  const r = await fetch(apiBase() + path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }).catch(() => {
    throw new ApiError(0, "Can't reach the FINN server. Is the backend running on port 8000?");
  });
  return handle(r);
}

export function useApi<T = any>(path: string | null, opts?: SWRConfiguration) {
  return useSWR<T>(path, fetcher, { revalidateOnFocus: true, keepPreviousData: true, ...opts });
}

export const fileUrl = (docId: number, page?: number | null) =>
  `${apiBase()}/api/documents/${docId}/file${page ? `#page=${page}` : ""}`;
export const annFileUrl = (annId: number) => `${apiBase()}/api/announcements/${annId}/file`;

// ---- types --------------------------------------------------------------------------------------
export type Growth = { pct: number | null; label: string };
export type ResultRow = {
  metric: string; label: string; current: number | null; previous: number | null; year_ago: number | null;
  qoq: Growth; yoy: Growth;
};
export type Person = {
  name: string; change: string; role?: string; effective_date?: string | null; reason?: string | null;
  profile?: string | null; prior_roles?: string[]; qualifications?: string[]; page?: number | null;
};
export type FeedItem = {
  id: string; type: "announcement" | "price" | "volume"; announcement_id?: number; alert_id?: number;
  category: string; category_label: string; subtype?: string | null; classified_by?: string | null;
  importance: number; reasons: string[]; routine: boolean; title: string; subject?: string; summary?: string | null;
  structured?: any; enrich_status?: string | null; enrich_error?: string | null; time: string | null;
  exchange: string; has_file?: boolean; source_url?: string | null;
  source?: { name: string; kind: string; url: string | null; label: string | null };
  company: { symbol: string; name: string };
  price: { close?: number | null; change_pct?: number | null; date?: string | null; spark: number[] };
  sample?: boolean; seen?: boolean; alert_kind?: string;
};
export type Feed = {
  window: { since: string; until: string; hours: number }; items: FeedItem[]; routine: FeedItem[];
  counts: Record<string, number>; total: number; high_importance: number;
};
export type Holding = {
  symbol: string; name: string; sector?: string; quantity: number; close: number | null; change_pct: number | null;
  change_abs: number | null; value: number; weight: number | null; volume_mult: number | null; as_of: string | null;
  spark: number[]; high_52w: number | null; low_52w: number | null; source: string | null;
};
export type Portfolio = {
  holdings: Holding[]; total_value: number; day_change_abs: number; day_change_pct: number | null;
  history: { date: string; value: number }[]; movers: string[]; as_of: string | null; demo: boolean;
};
export type Status = {
  sample_mode: boolean; user_name: string;
  llm: { enabled: boolean; fast_model: string; smart_model: string; groq: boolean };
  runs: Record<string, { last_run: string | null; status: string | null; detail: string | null; last_success: string | null }>;
  prices: { as_of: string | null; expected_session: string; stale: boolean; kind: string };
  announcements: { total: number; classified_by: Record<string, number> };
  ledger: { calls: number; cache_hits: number; input_tokens: number; output_tokens: number;
    by_purpose: Record<string, { calls: number; cache_hits: number; tokens: number; models: string[] }> };
  server_time: string;
};
export type Job = { id: number; status: string; step: string | null; progress: number; log: { t: string; msg: string }[]; error: string | null };
export type Cite = { kind: string; doc_id?: number | null; page?: number | null; title?: string; doc_type?: string; period?: string | null; snippet?: string };
export type Statement = { text: string; cites: string[]; verified: boolean; reason?: string | null; stance?: string };
