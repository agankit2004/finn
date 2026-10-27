"use client";
import { ChevronRight, FileText, Settings, Wallet } from "lucide-react";
import Link from "next/link";
import { PageHeader } from "@/components/shell";

const LINKS = [
  { href: "/announcements", label: "Announcements", sub: "The full digest, with any time window", icon: FileText },
  { href: "/portfolio", label: "Portfolio", sub: "Holdings, value and 52-week ranges", icon: Wallet },
  { href: "/settings", label: "Settings", sub: "Theme, data sources and AI usage", icon: Settings },
];

export default function More() {
  return (
    <div>
      <PageHeader title="More" />
      <ul className="mx-4 divide-y divide-line overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface sm:mx-6">
        {LINKS.map(({ href, label, sub, icon: Icon }) => (
          <li key={href}>
            <Link href={href} className="flex items-center gap-3 px-4 py-3.5">
              <Icon className="size-[18px] text-muted" />
              <span className="flex-1"><span className="block text-[14px] font-medium">{label}</span><span className="block text-[12px] text-muted">{sub}</span></span>
              <ChevronRight className="size-4 text-faint" />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
