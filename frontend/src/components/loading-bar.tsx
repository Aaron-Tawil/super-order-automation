export function LoadingBar({
  active,
  label = "מעדכן נתונים...",
}: {
  active: boolean;
  label?: string;
}) {
  if (!active) {
    return null;
  }

  return (
    <div className="inline-flex items-center gap-3 rounded-full border border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
      <span className="inline-block size-2 animate-pulse rounded-full bg-cyan-500" />
      <span>{label}</span>
    </div>
  );
}
