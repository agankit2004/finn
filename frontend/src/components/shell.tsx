"use client";
import clsx from "clsx";
import { Bell, ChevronRight, FileText, Home, LayoutGrid, Menu, Moon, Search, Settings, Sun, Wallet, Microscope, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useApi, type FeedItem, type Status } from "@/lib/api";
import { ItemDetail } from "./item-detail";

const NAV = [
  { href: "/", label: "Home", icon: Home },
  { href: "/portfolio", label: "Portfolio", icon: Wallet },
  { href: "/announcements", label: "Announcements", icon: FileText },
  { href: "/research", label: "Company research", icon: Microscope },
  { href: "/alerts", label: "Alerts", icon: Bell },
];

function isActive(path: string, href: string) {
  return href === "/" ? path === "/" : path.startsWith(href);
}

// ---- theme ----------------------------------------------------------------------------------------
export type ThemePref = "system" | "light" | "dark";
export function useTheme(): [ThemePref, (t: ThemePref) => void] {
  const [t, setT] = useState<ThemePref>("system");
  useEffect(() => {
    try { setT((localStorage.getItem("finn-theme") as ThemePref) || "system"); } catch {}
  }, []);
  const set = useCallback((v: ThemePref) => {
    setT(v);
    try { localStorage.setItem("finn-theme", v); } catch {}
    if (v === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", v);
  }, []);
  return [t, set];
}

export const themeScript = `try{var t=localStorage.getItem('finn-theme');if(t&&t!=='system')document.documentElement.setAttribute('data-theme',t)}catch(e){}`;

// ---- item sheet (detail drawer on desktop, bottom sheet on mobile) ------------------------------
const SheetCtx = createContext<{ open: (item: FeedItem) => void }>({ open: () => {} });
export const useItemSheet = () => useContext(SheetCtx);

function ItemSheet({ item, onClose }: { item: FeedItem | null; onClose: () => void }) {
  useEffect(() => {
    if (!item) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", k); document.body.style.overflow = ""; };
  }, [item, onClose]);
  if (!item) return null;
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal aria-label={item.title}>
      <button className="anim-fade absolute inset-0 bg-[#050a14]/50 backdrop-blur-[1px]" onClick={onClose} aria-label="Close" />
      <div className={clsx(
        "absolute flex flex-col bg-surface shadow-2xl",
        "inset-x-0 bottom-0 top-[6vh] rounded-t-[20px] anim-sheet",
        "md:inset-y-0 md:left-auto md:right-0 md:top-0 md:w-[520px] md:rounded-none md:border-l md:border-line md:anim-drawer")}>
        <div className="flex items-center justify-between border-b border-line px-4 py-2.5 md:px-5">
          <div className="mx-auto h-1 w-10 rounded-full bg-line-strong md:hidden" />
          <button onClick={onClose} className="absolute right-3 top-2 rounded-md p-1.5 text-muted hover:bg-surface-2 md:static md:ml-auto" aria-label="Close">
            <X className="size-4.5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto overscroll-contain pb-safe">
          <ItemDetail item={item} onNavigate={onClose} />
        </div>
      </div>
    </div>
  );
}

// ---- search ----------------------------------------------------------------------------------------
export function CompanySearch({ dark, autoFocus, className, placeholder }: { dark?: boolean; autoFocus?: boolean; className?: string; placeholder?: string }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const router = useRouter();
  const { data } = useApi<{ results: { symbol: string; name: string; in_portfolio: boolean; has_dossier: boolean }[] }>(
    q.trim().length >= 1 ? `/api/companies/search?q=${encodeURIComponent(q.trim())}` : null, { keepPreviousData: false });
  const results = data?.results ?? [];
  const go = (sym: string) => { setOpen(false); setQ(""); router.push(`/research/${sym.toUpperCase()}`); };
  const exact = /^[A-Za-z0-9&-]{2,20}$/.test(q.trim()) && !results.some((r) => r.symbol === q.trim().toUpperCase());
  const total = results.length + (exact ? 1 : 0);
  return (
    <div className={clsx("relative", className)}>
      <div className={clsx("flex h-10 items-center gap-2 rounded-[10px] border px-3",
        dark ? "border-ink-line bg-ink-2 text-ink-text" : "border-line bg-surface")}>
        <Search className={clsx("size-4 shrink-0", dark ? "text-ink-muted" : "text-faint")} />
        <input
          value={q} autoFocus={autoFocus}
          onChange={(e) => { setQ(e.target.value); setOpen(true); setHi(0); }}
          onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(total - 1, h + 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(0, h - 1)); }
            if (e.key === "Enter" && q.trim()) {
              const pick = results[hi]?.symbol ?? q.trim();
              go(pick);
            }
          }}
          placeholder={placeholder ?? "Search any NSE company, e.g. RELIANCE"}
          className={clsx("h-full min-w-0 flex-1 bg-transparent text-[13.5px] outline-none", dark ? "placeholder:text-ink-muted" : "placeholder:text-faint")}
          aria-label="Search companies" autoComplete="off" spellCheck={false}
        />
      </div>
      {open && q.trim() && total > 0 && (
        <ul className="absolute inset-x-0 top-11 z-40 overflow-hidden rounded-[10px] border border-line bg-surface py-1 text-text shadow-xl">
          {results.map((r, i) => (
            <li key={r.symbol}>
              <button onMouseDown={() => go(r.symbol)} onMouseEnter={() => setHi(i)}
                className={clsx("flex w-full items-center gap-3 px-3 py-2 text-left", hi === i && "bg-surface-2")}>
                <span className="w-24 shrink-0 text-[13px] font-semibold">{r.symbol}</span>
                <span className="flex-1 truncate text-[13px] text-muted">{r.name}</span>
                {r.in_portfolio && <span className="text-[11px] text-faint">Holding</span>}
                {r.has_dossier && <span className="text-[11px] text-accent">Dossier</span>}
              </button>
            </li>
          ))}
          {exact && (
            <li>
              <button onMouseDown={() => go(q.trim())} onMouseEnter={() => setHi(results.length)}
                className={clsx("flex w-full items-center gap-2 px-3 py-2 text-left text-[13px]", hi === results.length && "bg-surface-2")}>
                Research <b>{q.trim().toUpperCase()}</b> on NSE
              </button>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

// ---- shell -----------------------------------------------------------------------------------------
function Logo({ className }: { className?: string }) {
  return (
    <span className={clsx("flex items-center gap-2 font-semibold tracking-[-0.02em]", className)}>
      <svg viewBox="0 0 24 24" className="size-[22px]" aria-hidden>
        <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="2.4" />
        <path d="M12 2a10 10 0 0 1 10 10h-10z" fill="var(--accent)" />
      </svg>
      FINN
    </span>
  );
}

function Sidebar({ unseen, name }: { unseen: number; name: string }) {
  const path = usePathname();
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-[232px] flex-col bg-ink px-3 py-5 text-ink-text lg:flex">
      <Link href="/" className="px-2.5 text-[17px]"><Logo /></Link>
      <nav className="mt-7 flex flex-col gap-0.5">
        {NAV.map(({ href, label, icon: Icon }) => (
          <Link key={href} href={href}
            className={clsx("flex h-10 items-center gap-3 rounded-[10px] px-2.5 text-[13.5px] transition-colors",
              isActive(path, href) ? "bg-ink-3 font-medium text-ink-text" : "text-ink-muted hover:bg-ink-2 hover:text-ink-text")}>
            <Icon className="size-[18px]" strokeWidth={1.8} />
            <span className="flex-1">{label}</span>
            {href === "/alerts" && unseen > 0 && (
              <span className="num rounded-full bg-accent px-1.5 text-[11px] font-semibold leading-5 text-white">{unseen}</span>
            )}
          </Link>
        ))}
      </nav>
      <div className="mt-auto flex flex-col gap-0.5">
        <Link href="/settings" className={clsx("flex h-10 items-center gap-3 rounded-[10px] px-2.5 text-[13.5px]",
          isActive(path, "/settings") ? "bg-ink-3 text-ink-text" : "text-ink-muted hover:bg-ink-2 hover:text-ink-text")}>
          <Settings className="size-[18px]" strokeWidth={1.8} /> Settings
        </Link>
        <div className="mt-3 flex items-center gap-2.5 border-t border-ink-line px-2.5 pt-4">
          <span className="grid size-8 place-items-center rounded-full bg-ink-3 text-[13px] font-semibold">{(name || "Y").slice(0, 1).toUpperCase()}</span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium">{name || "You"}</span>
            <span className="block text-[11.5px] text-ink-muted">Demo portfolio</span>
          </span>
        </div>
      </div>
    </aside>
  );
}

function BottomNav({ unseen }: { unseen: number }) {
  const path = usePathname();
  const items = [
    { href: "/", label: "Home", icon: Home },
    { href: "/portfolio", label: "Portfolio", icon: Wallet },
    { href: "/research", label: "Research", icon: Microscope },
    { href: "/alerts", label: "Alerts", icon: Bell },
    { href: "/more", label: "More", icon: LayoutGrid },
  ];
  const moreActive = ["/more", "/settings", "/announcements"].some((p) => path.startsWith(p));
  return (
    <nav className="pb-safe fixed inset-x-0 bottom-0 z-30 border-t border-ink-line bg-ink/95 backdrop-blur lg:hidden" aria-label="Primary">
      <div className="mx-auto grid h-[60px] max-w-xl grid-cols-5">
        {items.map(({ href, label, icon: Icon }) => {
          const on = href === "/more" ? moreActive : isActive(path, href);
          return (
            <Link key={href} href={href} className={clsx("relative flex flex-col items-center justify-center gap-1 text-[10.5px]",
              on ? "text-ink-text" : "text-ink-muted")}>
              <Icon className="size-[20px]" strokeWidth={on ? 2.2 : 1.7} />
              {label}
              {href === "/alerts" && unseen > 0 && (
                <span className="num absolute left-1/2 top-1.5 ml-1.5 rounded-full bg-accent px-1 text-[9.5px] font-semibold leading-4 text-white">{unseen}</span>
              )}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

function MobileTop() {
  const path = usePathname();
  if (path === "/") return null; // Home has its own dark hero header
  return (
    <header className="sticky top-0 z-20 flex h-12 items-center justify-between border-b border-line bg-surface/90 px-4 backdrop-blur lg:hidden">
      <Link href="/" className="text-[15px]"><Logo /></Link>
      <Link href="/alerts" className="rounded-md p-1.5 text-muted" aria-label="Alerts"><Bell className="size-[18px]" /></Link>
    </header>
  );
}

function SampleBanner() {
  return (
    <div className="bg-warn px-4 py-1.5 text-center text-[12px] font-medium text-[#1a1203]">
      Sample data. These prices, filings and numbers are synthetic, for testing the interface only.
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [item, setItem] = useState<FeedItem | null>(null);
  const { data: status } = useApi<Status>("/api/status", { refreshInterval: 60000 });
  const { data: alerts } = useApi<{ unseen: number }>("/api/alerts", { refreshInterval: 60000 });
  const [name, setName] = useState("");
  useEffect(() => {
    try { setName(localStorage.getItem("finn-name") || ""); } catch {}
  }, []);
  const displayName = name || status?.user_name || "";
  const open = useCallback((i: FeedItem) => setItem(i), []);
  const close = useCallback(() => setItem(null), []);
  return (
    <SheetCtx.Provider value={{ open }}>
      <NameCtx.Provider value={displayName}>
        <Sidebar unseen={alerts?.unseen ?? 0} name={displayName} />
        <div className="min-h-dvh pb-[76px] lg:pb-0 lg:pl-[232px]">
          {status?.sample_mode && <SampleBanner />}
          <MobileTop />
          {children}
        </div>
        <BottomNav unseen={alerts?.unseen ?? 0} />
        <ItemSheet item={item} onClose={close} />
      </NameCtx.Provider>
    </SheetCtx.Provider>
  );
}

const NameCtx = createContext("");
export const useUserName = () => useContext(NameCtx);

export function PageHeader({ title, sub, action }: { title: string; sub?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 px-4 pt-5 pb-4 sm:px-6 lg:px-8 lg:pt-8">
      <div className="min-w-0">
        <h1 className="text-[20px] font-semibold tracking-[-0.02em] lg:text-[22px]">{title}</h1>
        {sub && <div className="mt-0.5 text-[13px] text-muted">{sub}</div>}
      </div>
      {action}
    </div>
  );
}

export function ThemeToggle() {
  const [t, set] = useTheme();
  return (
    <div className="inline-flex rounded-[var(--radius-sm)] bg-surface-2 p-0.5">
      {(["system", "light", "dark"] as ThemePref[]).map((v) => (
        <button key={v} onClick={() => set(v)} aria-pressed={t === v}
          className={clsx("flex h-8 items-center gap-1.5 rounded-[6px] px-3 text-[12.5px] font-medium capitalize",
            t === v ? "bg-surface shadow-[0_1px_2px_rgba(15,23,42,0.08)]" : "text-muted")}>
          {v === "light" ? <Sun className="size-3.5" /> : v === "dark" ? <Moon className="size-3.5" /> : <Menu className="size-3.5" />}
          {v}
        </button>
      ))}
    </div>
  );
}

export { ChevronRight };
