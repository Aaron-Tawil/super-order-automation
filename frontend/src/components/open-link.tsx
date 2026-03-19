import { ExternalLink } from "lucide-react";

import { cn } from "@/lib/utils";

export function OpenLink({
  href,
  label,
  tone = "primary",
}: {
  href: string;
  label: string;
  tone?: "primary" | "secondary";
}) {
  return (
    <div className="flex items-center gap-2">
      <a
        className={cn(
          "rounded-full px-4 py-2 text-sm transition",
          tone === "primary"
            ? "bg-slate-900 text-white hover:bg-slate-800 dark:bg-cyan-400/15 dark:text-cyan-100 dark:hover:bg-cyan-400/25"
            : "border border-slate-200 text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900",
        )}
        href={href}
      >
        {label}
      </a>
      <a
        aria-label={`${label} בלשונית חדשה`}
        className="rounded-full border border-slate-200 p-2 text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-900"
        href={href}
        rel="noreferrer"
        target="_blank"
      >
        <ExternalLink className="size-4" />
      </a>
    </div>
  );
}
