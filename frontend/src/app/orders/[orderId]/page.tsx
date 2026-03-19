"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, FileText, Sparkles } from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { LoadingBar } from "@/components/loading-bar";
import { MetricCard } from "@/components/metric-card";
import { OpenLink } from "@/components/open-link";
import { PageState } from "@/components/page-state";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";

export default function OrderPage() {
  const params = useParams<{ orderId: string }>();
  const orderId = params.orderId;
  const queryClient = useQueryClient();
  const [playgroundPrompt, setPlaygroundPrompt] = useState(
    "סכם את הבעיות האפשריות בהזמנה והצע בדיקות ידניות לפני אישור.",
  );

  const order = useQuery({
    queryKey: ["order", orderId],
    queryFn: () => api.getOrder(orderId),
  });

  const toggleTest = useMutation({
    mutationFn: (isTest: boolean) => api.updateOrderTestFlag(orderId, isTest),
    onMutate: async (isTest) => {
      await queryClient.cancelQueries({ queryKey: ["order", orderId] });
      const previousOrder = queryClient.getQueryData(["order", orderId]);
      queryClient.setQueryData(["order", orderId], (current: any) => (current ? { ...current, is_test: isTest } : current));
      queryClient.setQueriesData({ queryKey: ["orders"] }, (current: any) =>
        current
          ? {
              ...current,
              items: current.items.map((item: any) => (item.order_id === orderId ? { ...item, is_test: isTest } : item)),
            }
          : current,
      );
      return { previousOrder };
    },
    onError: (_error, _variables, context) => {
      if (context?.previousOrder) {
        queryClient.setQueryData(["order", orderId], context.previousOrder);
      }
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["order", orderId] });
      await queryClient.invalidateQueries({ queryKey: ["orders"] });
    },
  });

  const playgroundContext = useMemo(() => {
    if (!order.data) {
      return "";
    }
    const preview = {
      order_id: order.data.order_id,
      supplier: `${order.data.supplier_name} (${order.data.supplier_code})`,
      invoice_number: order.data.invoice_number,
      warnings: order.data.warnings,
      first_items: order.data.line_items.slice(0, 5),
      notes: order.data.notes,
      math_reasoning: order.data.math_reasoning,
      qty_reasoning: order.data.qty_reasoning,
    };
    return JSON.stringify(preview, null, 2);
  }, [order.data]);

  if (order.isLoading) {
    return (
      <AppShell>
        <PageState title="טוען הזמנה" body="מכין את פרטי ההזמנה, הקבצים להורדה, והקשר למגרש המשחקים." />
      </AppShell>
    );
  }

  if (!order.data) {
    return (
      <AppShell>
        <PageState title="הזמנה לא נמצאה" body="הקישור תקין אך לא נמצאה הזמנה מתאימה ב-Firestore." />
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="grid gap-4 md:grid-cols-4">
          <MetricCard label="ספק" value={order.data.supplier_name} />
          <MetricCard label="חשבונית" value={order.data.invoice_number} />
          <MetricCard label="סטטוס" value={order.data.status} />
          <MetricCard label="עלות עיבוד ₪" value={order.data.processing_cost_ils.toFixed(3)} />
        </div>

        <div className="rounded-[2rem] border border-white/70 bg-white/90 p-5 shadow-panel dark:border-slate-800 dark:bg-slate-950/90">
          <LoadingBar active={order.isFetching || toggleTest.isPending} />
        </div>

        <div className="grid gap-6 md:grid-cols-[2fr_1fr]">
          <div className="rounded-[2rem] border border-white/70 bg-white/90 p-6 shadow-panel dark:border-slate-800 dark:bg-slate-950/90">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-50">שורות פריטים</h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{formatDateTime(order.data.created_at)}</p>
              </div>
              <div className="flex flex-wrap gap-3">
                <OpenLink href={order.data.export_url} label="הורד אקסל" tone="primary" />
                <OpenLink href={order.data.source_file_url} label="הורד קובץ מקור" tone="secondary" />
              </div>
            </div>

            <div className="mt-5 overflow-x-auto">
              <table className="min-w-full text-right text-sm text-slate-700 dark:text-slate-200">
                <thead className="border-b border-slate-200 text-slate-500 dark:border-slate-800 dark:text-slate-400">
                  <tr>
                    <th className="px-3 py-3">קוד פריט</th>
                    <th className="px-3 py-3">ברקוד</th>
                    <th className="px-3 py-3">תיאור</th>
                    <th className="px-3 py-3">כמות</th>
                    <th className="px-3 py-3">מחיר נטו</th>
                  </tr>
                </thead>
                <tbody>
                  {order.data.line_items.map((item, index) => (
                    <tr key={`${item.barcode}-${index}`} className="border-b border-slate-100 dark:border-slate-800">
                      <td className="px-3 py-3">{item.item_code}</td>
                      <td className="px-3 py-3">{item.barcode}</td>
                      <td className="px-3 py-3">{item.description}</td>
                      <td className="px-3 py-3">{item.quantity}</td>
                      <td className="px-3 py-3">{item.final_net_price}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-[2rem] border border-white/70 bg-white/90 p-5 shadow-panel dark:border-slate-800 dark:bg-slate-950/90">
              <div className="text-sm text-slate-500 dark:text-slate-400">מטא-דאטה</div>
              <div className="mt-3 space-y-2 text-sm text-slate-700 dark:text-slate-200">
                <div>שולח: {order.data.sender}</div>
                <div>נושא: {order.data.subject}</div>
                <div>קובץ: {order.data.filename}</div>
              </div>
              <label className="mt-5 flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
                <input
                  checked={order.data.is_test}
                  disabled={toggleTest.isPending}
                  onChange={(event) => toggleTest.mutate(event.target.checked)}
                  type="checkbox"
                />
                <span>{toggleTest.isPending ? "שומר שינוי..." : order.data.is_test ? "מסומן כטסט" : "מסומן כאמיתי"}</span>
              </label>
            </div>

            {order.data.warnings.length > 0 ? (
              <div className="rounded-[2rem] border border-rose-200 bg-rose-50 p-5 shadow-panel dark:border-rose-900/50 dark:bg-rose-950/40">
                <div className="text-sm font-semibold text-rose-700 dark:text-rose-300">אזהרות</div>
                <ul className="mt-3 space-y-2 text-sm text-rose-800 dark:text-rose-200">
                  {order.data.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {order.data.notes || order.data.math_reasoning || order.data.qty_reasoning ? (
              <div className="rounded-[2rem] border border-slate-200 bg-slate-50 p-5 shadow-panel dark:border-slate-800 dark:bg-slate-900/70">
                <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">תובנות AI</div>
                <div className="mt-3 space-y-3 text-sm text-slate-700 dark:text-slate-200">
                  {order.data.notes ? <p>{order.data.notes}</p> : null}
                  {order.data.math_reasoning ? <p>{order.data.math_reasoning}</p> : null}
                  {order.data.qty_reasoning ? <p>{order.data.qty_reasoning}</p> : null}
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <div className="rounded-[2rem] border border-white/70 bg-white/90 p-6 shadow-panel dark:border-slate-800 dark:bg-slate-950/90">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <Sparkles className="size-5 text-slate-600 dark:text-slate-300" />
              <div>
                <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-50">Playground</h3>
                <p className="text-sm text-slate-500 dark:text-slate-400">בדוק פרומפטים והקשר להזמנה לפני שנחבר פעולה חיה.</p>
              </div>
            </div>
            <button
              className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-4 py-2 text-sm text-slate-700 dark:border-slate-700 dark:text-slate-200"
              onClick={async () => navigator.clipboard.writeText(playgroundContext)}
              type="button"
            >
              <Copy className="size-4" />
              העתק הקשר JSON
            </button>
          </div>

          <div className="mt-5 grid gap-5 lg:grid-cols-[1fr_1fr]">
            <div className="space-y-3">
              <label className="text-sm text-slate-600 dark:text-slate-300">פרומפט</label>
              <textarea
                className="min-h-40 w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                onChange={(event) => setPlaygroundPrompt(event.target.value)}
                value={playgroundPrompt}
              />
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-2 flex items-center gap-2 font-medium text-slate-800 dark:text-slate-100">
                  <FileText className="size-4" />
                  הצעה מוכנה
                </div>
                <pre className="whitespace-pre-wrap text-slate-600 dark:text-slate-300">{`${playgroundPrompt}\n\nContext:\n${playgroundContext}`}</pre>
              </div>
            </div>

            <div className="space-y-3">
              <label className="text-sm text-slate-600 dark:text-slate-300">תצוגת הקשר</label>
              <pre className="min-h-40 overflow-x-auto rounded-2xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
                {playgroundContext}
              </pre>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
