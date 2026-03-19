export function PageState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-3xl border border-dashed border-border bg-card px-6 py-10 text-center shadow-panel">
      <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-50">{title}</h2>
      <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{body}</p>
    </div>
  );
}
