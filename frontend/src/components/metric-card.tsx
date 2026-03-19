import { cn } from "@/lib/utils";

export function MetricCard({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number | string;
  tone?: "default" | "success" | "danger";
}) {
  return (
    <div
      className={cn(
        "rounded-3xl border border-border bg-card px-5 py-4 shadow-panel",
        tone === "success" && "border-emerald-200",
        tone === "danger" && "border-rose-200",
      )}
    >
      <div className="text-sm text-slate-500 dark:text-slate-400">{label}</div>
      <div className="mt-2 text-3xl font-semibold text-slate-900 dark:text-slate-50">{value}</div>
    </div>
  );
}
