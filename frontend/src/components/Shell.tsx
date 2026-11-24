"use client";

import { Activity, Bell, BookOpen, ClipboardCheck, FolderSearch, LayoutDashboard, LogOut, MessageSquareText, Moon, Settings, ShieldCheck, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api, BASE, useApi, useMe } from "@/lib/api";
import type { Role } from "@/lib/types";
import { Loading, ToastProvider } from "./ui";

const NAV: { href: string; label: string; icon: typeof Bell; roles: Role[]; count?: "alerts" | "approvals" }[] = [
  { href: "/overview/", label: "Overview", icon: LayoutDashboard, roles: ["viewer", "analyst", "admin"] },
  { href: "/ask/", label: "Ask", icon: MessageSquareText, roles: ["analyst", "admin"] },
  { href: "/investigations/", label: "Investigations", icon: FolderSearch, roles: ["viewer", "analyst", "admin"] },
  { href: "/alerts/", label: "Alerts", icon: Bell, roles: ["viewer", "analyst", "admin"], count: "alerts" },
  { href: "/approvals/", label: "Approvals", icon: ClipboardCheck, roles: ["analyst", "admin"], count: "approvals" },
  { href: "/catalog/", label: "Data catalogue", icon: BookOpen, roles: ["viewer", "analyst", "admin"] },
  { href: "/usage/", label: "Usage", icon: Activity, roles: ["analyst", "admin"] },
  { href: "/evaluation/", label: "Evaluation", icon: ShieldCheck, roles: ["viewer", "analyst", "admin"] },
  { href: "/admin/", label: "Administration", icon: Settings, roles: ["admin"] },
];

function useTheme() {
  const [theme, setTheme] = useState("light");
  useEffect(() => setTheme(document.documentElement.dataset.theme ?? "light"), []);
  return [theme, () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch { /* private mode */ }
    setTheme(next);
  }] as const;
}

export function Shell({ children }: { children: ReactNode }) {
  const { user, signedOut, isLoading } = useMe();
  const router = useRouter();
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const [theme, toggleTheme] = useTheme();
  const canAct = user && user.role !== "viewer";
  const alerts = useApi<{ unacknowledged: number }>(user ? "/api/alerts/events?open_only=true&limit=1" : null, { refreshInterval: 60_000 });
  const approvals = useApi<{ approvals: unknown[] }>(canAct ? "/api/approvals?status=pending" : null, { refreshInterval: 30_000 });
  const counts = { alerts: alerts.data?.unacknowledged ?? 0, approvals: approvals.data?.approvals.length ?? 0 };

  useEffect(() => { if (signedOut) router.replace("/login/"); }, [signedOut, router]);
  useEffect(() => setOpen(false), [path]);

  if (isLoading || !user) return <Loading rows={6} label="Signing in" />;
  const signOut = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    window.location.href = `${BASE}/login/`;
  };
  return (
    <ToastProvider>
      <div className="shell">
        <header className="masthead" data-open={open}>
          <div className="masthead__inner">
            <div className="masthead__bar">
              <Link href="/overview/" className="masthead__wordmark">FinOps Agent</Link>
              <button className="btn btn--sm menu-btn" onClick={() => setOpen(!open)} aria-expanded={open} aria-controls="main-menu">Menu</button>
            </div>
            <div className="masthead__drop" id="main-menu">
              <nav aria-label="Main" className="masthead__nav">
                {NAV.filter((n) => n.roles.includes(user.role)).map(({ href, label, icon: Icon, count }) => (
                  <Link key={href} href={href} className="navlink" aria-current={path.startsWith(href.slice(0, -1)) ? "page" : undefined}>
                    <Icon aria-hidden />
                    {label}
                    {count && counts[count] > 0 && <span className="navlink__count">{counts[count]}</span>}
                  </Link>
                ))}
              </nav>
              <div className="masthead__account">
                <div className="masthead__who">
                  <span>{user.name || user.email}</span>
                  <span className="label measured">{user.email}</span>
                </div>
                <span className="chip">{user.role}</span>
                <button className="btn btn--quiet btn--sm" onClick={toggleTheme}>
                  {theme === "dark" ? <Sun aria-hidden /> : <Moon aria-hidden />}
                  {theme === "dark" ? "Light theme" : "Dark theme"}
                </button>
                <button className="btn btn--sm" onClick={signOut}><LogOut aria-hidden />Sign out</button>
              </div>
            </div>
          </div>
        </header>
        <main className="main">{children}</main>
      </div>
    </ToastProvider>
  );
}

export function Page({ title, lede, actions, children }: { title: string; lede?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="page">
      <header className={`page__head${title.length > 60 ? " page__title--long" : ""}`}>
        <div>
          <h1>{title}</h1>
          {lede && <p className="lede">{lede}</p>}
        </div>
        {actions && <div className="page__actions">{actions}</div>}
      </header>
      {children}
    </div>
  );
}
