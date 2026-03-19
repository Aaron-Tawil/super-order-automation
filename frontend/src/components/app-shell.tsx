"use client";

import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import Link from "next/link";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/inbox", label: "תיבת הזמנות" },
  { href: "/upload", label: "העלאה ידנית" },
  { href: "/suppliers", label: "ניהול ספקים" },
  { href: "/items", label: "ניהול פריטים" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: api.getSession,
  });

  useEffect(() => {
    if (session.isLoading) {
      return;
    }
    if (!session.data?.authenticated) {
      router.replace("/login");
    }
  }, [router, session.data?.authenticated, session.isLoading]);

  if (session.isLoading) {
    return <div className="px-8 py-10 text-slate-600">טוען חיבור מאובטח...</div>;
  }

  if (!session.data?.authenticated) {
    return null;
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,#f8fafc,#e2e8f0_60%,#cbd5e1)] dark:bg-[radial-gradient(circle_at_top,#1e293b,#0f172a_58%,#020617)]">
      <div className="mx-auto max-w-7xl px-4 py-6 md:px-6">
        <div className="mb-6 rounded-4xl border border-white/80 bg-white/85 p-4 shadow-panel backdrop-blur-sm dark:border-slate-800 dark:bg-slate-950/85">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="text-xs uppercase tracking-[0.3em] text-slate-500 dark:text-slate-400">Order Console</div>
              <h1 className="mt-2 text-2xl font-semibold text-slate-900 dark:text-slate-50">מערכת אוטומציה להזמנות</h1>
            </div>
            <div className="flex items-center gap-3 text-sm text-slate-600 dark:text-slate-300">
              <span>{session.data.email}</span>
              <button
                className="rounded-full border border-slate-200 px-4 py-2 text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
                onClick={async () => {
                  await api.logout();
                  router.replace("/login");
                }}
                type="button"
              >
                התנתק
              </button>
            </div>
          </div>
          <div className="mt-5 flex flex-wrap gap-3">
            {navItems.map((item) => {
              const active = pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  className={cn(
                    "rounded-full px-4 py-2 text-sm transition",
                    active
                      ? "bg-slate-900 text-white dark:border dark:border-cyan-500/40 dark:bg-cyan-400/15 dark:text-cyan-100"
                      : "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800",
                  )}
                  href={item.href}
                >
                  {item.label}
                </Link>
              );
            })}
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}
