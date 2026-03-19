"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { LoadingBar } from "@/components/loading-bar";
import { MetricCard } from "@/components/metric-card";
import { PageState } from "@/components/page-state";
import { api } from "@/lib/api";
import type { OrdersResponse } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

function InboxSkeleton() {
  return (
    <div className="overflow-hidden rounded-[2rem] border border-white/70 bg-white/90 shadow-panel dark:border-slate-800 dark:bg-slate-950/90">
      <div className="space-y-3 p-5">
        {Array.from({ length: 5 }).map((_, index) => (
          <div
            key={index}
            className="h-14 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-900"
          />
        ))}
      </div>
    </div>
  );
}

export default function InboxPage() {
  const queryClient = useQueryClient();
  const [includeTest, setIncludeTest] = useState(false);
  const [selectedSupplier, setSelectedSupplier] = useState("");
  const [page, setPage] = useState(1);

  const supplierParams = useMemo(() => {
    const nextParams = new URLSearchParams();
    nextParams.set("page", "1");
    nextParams.set("page_size", "100");
    return nextParams;
  }, []);

  const suppliers = useQuery({
    queryKey: ["supplier-options", supplierParams.toString()],
    queryFn: () => api.getSuppliers(supplierParams),
  });

  const params = useMemo(() => {
    const nextParams = new URLSearchParams();
    if (selectedSupplier) nextParams.set("supplier", selectedSupplier);
    if (includeTest) nextParams.set("include_test", "true");
    nextParams.set("page", String(page));
    nextParams.set("page_size", "10");
    return nextParams;
  }, [includeTest, page, selectedSupplier]);

  const orders = useQuery({
    queryKey: ["orders", params.toString()],
    queryFn: () => api.getOrders(params),
    placeholderData: keepPreviousData,
  });

  const toggleTest = useMutation({
    mutationFn: ({ orderId, isTest }: { orderId: string; isTest: boolean }) => api.updateOrderTestFlag(orderId, isTest),
    onMutate: async ({ orderId, isTest }) => {
      await queryClient.cancelQueries({ queryKey: ["orders"] });
      const snapshots = queryClient.getQueriesData<OrdersResponse>({ queryKey: ["orders"] });
      snapshots.forEach(([key, value]) => {
        if (!value) return;
        queryClient.setQueryData<OrdersResponse>(key, {
          ...value,
          items: value.items.map((item) => (item.order_id === orderId ? { ...item, is_test: isTest } : item)),
        });
      });
      queryClient.setQueryData(["order", orderId], (current: any) =>
        current ? { ...current, is_test: isTest } : current,
      );
      return { snapshots };
    },
    onError: (_error, _variables, context) => {
      context?.snapshots.forEach(([key, value]) => queryClient.setQueryData(key, value));
    },
    onSettled: async (_data, _error, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["orders"] });
      await queryClient.invalidateQueries({ queryKey: ["order", variables.orderId] });
    },
  });

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="grid gap-4 md:grid-cols-5">
          <MetricCard label="סה״כ" value={orders.data?.metrics.total ?? 0} />
          <MetricCard label="הושלמו" value={orders.data?.metrics.completed ?? 0} tone="success" />
          <MetricCard label="לבדיקה" value={orders.data?.metrics.needs_review ?? 0} />
          <MetricCard label="נכשלו" value={orders.data?.metrics.failed ?? 0} tone="danger" />
          <MetricCard label="ספק לא מזוהה" value={orders.data?.metrics.unknown_supplier ?? 0} />
        </div>

        <div className="rounded-[2rem] border border-white/70 bg-white/85 p-5 shadow-panel backdrop-blur dark:border-slate-800 dark:bg-slate-950/85">
          <div className="grid gap-3 md:grid-cols-[minmax(0,320px)_auto]">
            <select
              className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              onChange={(event) => {
                setSelectedSupplier(event.target.value);
                setPage(1);
              }}
              value={selectedSupplier}
            >
              <option value="">כל הספקים</option>
              {suppliers.data?.items.map((supplier) => (
                <option key={supplier.code} value={supplier.code}>
                  {supplier.name} ({supplier.code})
                </option>
              ))}
            </select>
            <label className="flex items-center justify-center gap-2 rounded-2xl border border-slate-200 px-4 py-3 text-sm text-slate-700 dark:border-slate-700 dark:text-slate-200">
              <input
                checked={includeTest}
                onChange={(event) => {
                  setIncludeTest(event.target.checked);
                  setPage(1);
                }}
                type="checkbox"
              />
              כולל הזמנות טסט
            </label>
          </div>

          <div className="mt-4 flex items-center justify-between gap-3">
            <LoadingBar active={orders.isFetching || suppliers.isFetching} label="מעדכן תיבת הזמנות..." />
            <div className="text-sm text-slate-500 dark:text-slate-400">
              מציג {orders.data?.items.length ?? 0} מתוך {orders.data?.total_items ?? 0} הזמנות
            </div>
          </div>
        </div>

        {!orders.data && orders.isLoading ? (
          <InboxSkeleton />
        ) : orders.data?.items.length ? (
          <div className="overflow-hidden rounded-[2rem] border border-white/70 bg-white/90 shadow-panel dark:border-slate-800 dark:bg-slate-950/90">
            <div className="overflow-x-auto">
              <table className="min-w-full text-right">
                <thead className="bg-slate-950 text-sm text-white dark:bg-slate-900 dark:text-slate-200">
                  <tr>
                    <th className="px-4 py-3">נוצר</th>
                    <th className="px-4 py-3">סטטוס</th>
                    <th className="px-4 py-3">ספק</th>
                    <th className="px-4 py-3">חשבונית</th>
                    <th className="px-4 py-3">שורות</th>
                    <th className="px-4 py-3">אזהרות</th>
                    <th className="px-4 py-3">טסט</th>
                    <th className="px-4 py-3">פעולות</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.data.items.map((order) => {
                    const isPending = toggleTest.isPending && toggleTest.variables?.orderId === order.order_id;
                    return (
                      <tr key={order.order_id} className="border-b border-slate-100 text-sm text-slate-700 dark:border-slate-800 dark:text-slate-200">
                        <td className="px-4 py-4">{formatDateTime(order.created_at)}</td>
                        <td className="px-4 py-4">{order.status}</td>
                        <td className="px-4 py-4">
                          {order.supplier_name} ({order.supplier_code})
                        </td>
                        <td className="px-4 py-4">{order.invoice_number}</td>
                        <td className="px-4 py-4">{order.line_items_count}</td>
                        <td className="px-4 py-4">{order.warnings_count}</td>
                        <td className="px-4 py-4">
                          <label className="inline-flex items-center gap-2">
                            <input
                              checked={order.is_test}
                              disabled={isPending}
                              onChange={(event) =>
                                toggleTest.mutate({ orderId: order.order_id, isTest: event.target.checked })
                              }
                              type="checkbox"
                            />
                            <span className="text-xs text-slate-500 dark:text-slate-400">
                              {isPending ? "שומר..." : order.is_test ? "טסט" : "אמיתי"}
                            </span>
                          </label>
                        </td>
                        <td className="px-4 py-4">
                          <a
                            className="rounded-full bg-slate-900 px-4 py-2 text-sm text-white transition hover:bg-slate-800 dark:bg-cyan-400/15 dark:text-cyan-100 dark:hover:bg-cyan-400/25"
                            href={`/orders/${order.order_id}`}
                            rel="noreferrer"
                            target="_blank"
                          >
                            פתח הזמנה
                          </a>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-4 py-4 text-sm dark:border-slate-800">
              <div className="text-slate-500 dark:text-slate-400">
                עמוד {orders.data.page} מתוך {orders.data.total_pages}
              </div>
              <div className="flex items-center gap-2">
                <button
                  className="rounded-full border border-slate-200 px-4 py-2 disabled:opacity-40 dark:border-slate-700"
                  disabled={orders.data.page <= 1 || orders.isFetching}
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  type="button"
                >
                  הקודם
                </button>
                <button
                  className="rounded-full border border-slate-200 px-4 py-2 disabled:opacity-40 dark:border-slate-700"
                  disabled={orders.data.page >= orders.data.total_pages || orders.isFetching}
                  onClick={() => setPage((current) => current + 1)}
                  type="button"
                >
                  הבא
                </button>
              </div>
            </div>
          </div>
        ) : (
          <PageState title="אין תוצאות" body="לא נמצאו הזמנות לסינון הנוכחי." />
        )}
      </div>
    </AppShell>
  );
}
